"""Manage the local NATS + PostgreSQL Compose stack. Requires Docker Engine and Compose v2.

Secrets are generated locally, never printed or bundled. `down` retains named volumes; no delete-volumes command.
"""
import argparse
import hashlib
import math
import re
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / 'deploy/local/compose.json'
SECRET_DIR = ROOT / 'local/compose-secrets'


def initialize(root=ROOT):
    directory = root / 'local/compose-secrets'
    if (root / 'local').is_symlink() or directory.is_symlink():
        raise ValueError('refusing symlink secret directory')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    (root / 'local/intake').mkdir(exist_ok=True, mode=0o755)
    values = {}
    for name in ('pg_admin', 'pg_app', 'nats_token', 'pseudonym_salt', 'api_token'):
        path = directory / name
        if path.is_symlink():
            raise ValueError('refusing symlink secret file')
        if not path.exists():
            # Exclusive create; never rotate an existing volume's password or pseudonym salt on reruns.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600 if name == 'api_token' else 0o444)
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32) + '\n')
        value = path.read_text().strip()
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid existing generated secret; restore it, do not silently rotate')
        path.chmod(0o600 if name == 'api_token' else 0o444)
        values[name] = value
    # Compose file-backed secrets retain host ownership/mode. Nonroot application containers need read access;
    # the enclosing host directory is 0700. These are local development secrets, not a secret-manager substitute.
    config = ('server_name: datamesh-local\nport: 4222\n'
              'authorization { token: "' + values['nats_token'] + '" }\n'
              'jetstream {\n  store_dir: "/data"\n  max_memory_store: 64MB\n  max_file_store: 2GB\n}\n')
    target = directory / 'nats.conf'
    if target.is_symlink():
        raise ValueError('refusing symlink NATS configuration')
    if target.exists() and target.read_text() != config:
        raise ValueError('existing NATS configuration differs; review manually')
    if not target.exists():
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, 'w') as stream:
            stream.write(config)
    target.chmod(0o444)
    return directory


def configuration_environment(environ=None):
    """Preferred values win by presence; do not turn explicit empty values into fallbacks."""
    env = dict(os.environ if environ is None else environ)
    for name, value in tuple(env.items()):
        if name.startswith('CURRENTCRAFT_'):
            env['DATAMESH_' + name[len('CURRENTCRAFT_'):]] = value
    return env


def compose(*args):
    subprocess.run(['docker', 'compose', '-f', str(COMPOSE), *args], cwd=ROOT,
                   env=configuration_environment(), check=True)


def provision_api_secrets(directory=SECRET_DIR):
    """Stream only validated secrets to the nonroot helper; never echo container output."""
    try:
        values = {}
        for name in ('api_token', 'pg_app', 'nats_token'):
            path = directory / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('invalid source secret')
            value = path.read_text().strip()
            if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('invalid source secret')
            values[name] = value
        payload = json.dumps(values).encode()
        subprocess.run(['docker', 'compose', '-f', str(COMPOSE), '--profile', 'tools',
                        'run', '--rm', '--no-deps', '-T', 'api-secrets'],
                       cwd=ROOT, env=configuration_environment(), input=payload,
                       capture_output=True, timeout=60, check=True)
    except Exception:
        raise RuntimeError('local API secret provisioning failed; API startup not attempted') from None


def start_stack():
    compose('build', 'prepare')
    provision_api_secrets()
    compose('up', '-d', 'worker', 'api')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def shell_status(url, token, timeout):
    # Ignore host proxies and refuse redirects so a bearer token cannot leave localhost.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    headers = {} if token is None else {'Authorization': 'Bearer ' + token}
    try:
        with opener.open(Request(url, headers=headers), timeout=timeout) as response:
            return response.status
    except HTTPError as exc:
        exc.close()
        return exc.code
    except (URLError, OSError):
        return None


def _api_target(directory, environ):
    env = configuration_environment(environ)
    try:
        port = int(env.get('DATAMESH_API_PORT', '8000'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError('invalid local API port') from None
    token = (directory / 'api_token').read_text().strip()
    if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('invalid local API token file')
    return "http://127.0.0.1:" + str(port), token


def api_smoke(directory=SECRET_DIR, environ=None, timeout=60):
    base, token = _api_target(directory, environ)
    wrong = ('0' if token[0] != '0' else '1') + token[1:]
    deadline = time.monotonic() + timeout
    checks = (('/healthz', None, 200), ('/readyz', None, 200),
              ('/v1/auth/check', None, 401), ('/v1/auth/check', wrong, 401),
              ('/v1/auth/check', token, 200))
    while time.monotonic() < deadline:
        passed = True
        for path, bearer, expected in checks:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or shell_status(base + path, bearer, min(4, remaining)) != expected:
                passed = False
                break
        if passed:
            print('PASS: API liveness, readiness, and shared-token positive/negative authentication.')
            return
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    raise RuntimeError('API shell smoke timed out; inspect API/bootstrap status')


def _smoke_json(opener, base, token, path, deadline, *, body=None, boundary=None):
    """Bound response bytes/time and never include HTTP bodies or exceptions in errors."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError('HTTP intake smoke timed out')
    headers = {'Authorization': 'Bearer ' + token}
    if body is not None:
        headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
    request = Request(base + path, data=body, headers=headers)
    try:
        with opener.open(request, timeout=min(4, remaining)) as response:
            if response.status != (202 if body is not None else 200):
                raise ValueError('unexpected status')
            raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError('response too large')
        result = json.loads(raw)
        if not isinstance(result, dict) or token in raw.decode('utf-8'):
            raise ValueError('invalid response')
        return result
    except HTTPError as error:
        error.close()
        raise RuntimeError('HTTP intake smoke request failed') from None
    except Exception:
        raise RuntimeError('HTTP intake smoke request failed') from None


def api_upload_smoke(directory=SECRET_DIR, environ=None, timeout=60):
    """Real loopback HTTP -> durable queue -> worker -> processed, never a stand-in."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('invalid HTTP smoke timeout')
    base, token = _api_target(directory, environ)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    source = 'synthetic-http-smoke-' + secrets.token_hex(16)
    content = b'Currentcraft synthetic HTTP upload smoke. Source record, not approved work.\n'
    digest = hashlib.sha256(content).hexdigest()
    boundary = 'currentcraft-smoke-' + secrets.token_hex(16)
    parts = []
    for name, value in (('format', 'text'), ('source_id', source)):
        parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + name +
                      '"\r\n\r\n' + value + '\r\n').encode('ascii'))
    parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; '
                  'filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n').encode('ascii') +
                 content + ('\r\n--' + boundary + '--\r\n').encode('ascii'))
    body = b''.join(parts)

    def upload():
        receipt = _smoke_json(opener, base, token, '/v1/intake/documents', deadline,
                              body=body, boundary=boundary)
        if (set(receipt) != {'event_id', 'stream', 'sequence', 'duplicate', 'source_id',
                             'content_sha256', 'status_url', 'detail'} or
                not isinstance(receipt['event_id'], str) or
                re.fullmatch(r'intake_[0-9a-f]{32}', receipt['event_id']) is None or
                not isinstance(receipt['source_id'], str) or
                re.fullmatch(r'source_[0-9a-f]{32}', receipt['source_id']) is None or
                receipt['status_url'] != '/v1/intake/' + receipt['event_id'] or
                receipt['stream'] != 'DM_RAW' or receipt['content_sha256'] != digest or
                type(receipt['sequence']) is not int or receipt['sequence'] < 1 or
                type(receipt['duplicate']) is not bool or
                not isinstance(receipt['detail'], str) or 'not extracted' not in receipt['detail'] or
                source in json.dumps(receipt)):
            raise RuntimeError('HTTP intake smoke received an invalid durable receipt')
        return receipt

    def status(receipt):
        # Never follow an unvalidated status URL, even to another loopback endpoint.
        result = _smoke_json(opener, base, token,
                             '/v1/intake/' + receipt['event_id'], deadline)
        if (set(result) != {'event_id', 'status', 'detail'} or
                result['event_id'] != receipt['event_id'] or
                result['status'] not in ('pending', 'processed', 'quarantined') or
                not isinstance(result['detail'], str) or 'not approved work' not in result['detail'] or
                source in json.dumps(result)):
            raise RuntimeError('HTTP intake smoke received an invalid worker status')
        if result['status'] == 'quarantined':
            raise RuntimeError('HTTP intake smoke was quarantined by the worker')
        return result['status']

    first = upload()
    if first['duplicate']:
        raise RuntimeError('HTTP intake smoke did not create a fresh submission')
    while time.monotonic() < deadline:
        if status(first) == 'processed':
            break
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    else:
        raise RuntimeError('HTTP intake smoke timed out waiting for worker processing')
    retry = upload()
    if (not retry['duplicate'] or any(retry[key] != first[key] for key in
            ('event_id', 'source_id', 'status_url', 'stream', 'sequence', 'content_sha256')) or
            status(retry) != 'processed'):
        raise RuntimeError('HTTP intake smoke retry did not preserve the processed receipt')
    if time.monotonic() >= deadline:
        raise RuntimeError('HTTP intake smoke timed out')
    print('PASS: real HTTP upload -> durable queue -> worker -> processed; identical retry retained receipt. '
          'Source occurrences, not approved work.')


def _release_command(argv, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError('evidence deadline')
    result = subprocess.run(argv, cwd=ROOT, env=configuration_environment(),
                            capture_output=True, text=True, check=True,
                            timeout=min(20, remaining))
    if len(result.stdout) > 65536:
        raise RuntimeError('evidence output limit')
    return result.stdout.strip()


def release_evidence(timeout=120):
    """Allowlisted runtime facts only; never full inspect, environments or secrets."""
    try:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('invalid evidence timeout')
        deadline = time.monotonic() + timeout
        def run(*args):
            return _release_command(list(args), deadline)
        def service(name, *args):
            return run('docker', 'compose', '-f', str(COMPOSE), 'exec', '-T', name, *args)
        revision = run('git', 'rev-parse', 'HEAD')
        if re.fullmatch(r'[0-9a-f]{40}', revision) is None:
            raise ValueError('invalid revision')
        declared = (ROOT / 'src/app/_version.py').read_text().strip()
        version = re.fullmatch(r'__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"', declared).group(1)
        packages = ('datamesh-agency-toolkit', 'psycopg', 'nats-py', 'fastapi',
                    'uvicorn', 'starlette', 'pydantic', 'python-multipart')
        probe = ('import importlib.metadata as m,json,platform; '
                 'print(json.dumps(dict(python=platform.python_version(),'
                 'packages={n:m.version(n) for n in ' + repr(packages) + '})))')
        runtime = json.loads(service('api', 'python', '-c', probe))
        if (set(runtime) != {'python', 'packages'} or not isinstance(runtime['packages'], dict) or
                set(runtime['packages']) != set(packages) or
                runtime['packages']['datamesh-agency-toolkit'] != version):
            raise ValueError('runtime metadata mismatch')
        for value in [runtime['python'], *runtime['packages'].values()]:
            if not isinstance(value, str) or re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]{0,79}', value) is None:
                raise ValueError('invalid package version')
        postgres = re.fullmatch(r'postgres \(PostgreSQL\) ([0-9]+(?:\.[0-9]+){1,2})(?: [^\r\n]*)?',
                                service('postgres', 'postgres', '--version')).group(1)
        nats = re.fullmatch(r'nats-server: v([0-9]+(?:\.[0-9]+){2})',
                            service('nats', 'nats-server', '--version')).group(1)
        if not postgres.startswith('18.') or not nats.startswith('2.11.'):
            raise ValueError('unexpected server release line')
        images = {}
        for name in ('postgres', 'nats', 'api'):
            cid = run('docker', 'compose', '-f', str(COMPOSE), 'ps', '-q', name)
            if re.fullmatch(r'[0-9a-f]{12,64}', cid) is None:
                raise ValueError('container resolution failed')
            image_id = run('docker', 'inspect', '--format', '{{.Image}}', cid)
            if re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) is None:
                raise ValueError('invalid image id')
            digests = json.loads(run('docker', 'image', 'inspect', '--format',
                                    '{{json .RepoDigests}}', image_id))
            if digests is None and name == 'api':
                digests = []  # An unpublished local image has no registry digest.
            if not isinstance(digests, list) or (name != 'api' and not digests):
                raise ValueError('missing server repository digest')
            repository = name if name != 'api' else 'datamesh-local-app'
            pattern = r'(?:(?:docker\.io|index\.docker\.io)/)?(?:library/)?' + repository + r'@sha256:[0-9a-f]{64}'
            if any(not isinstance(d, str) or re.fullmatch(pattern, d) is None for d in digests):
                raise ValueError('invalid repository digest')
            images[name] = {'image_id': image_id, 'repository_digests': sorted(digests)}
        if time.monotonic() >= deadline:
            raise RuntimeError('evidence deadline')
        evidence = {'schema': 'currentcraft-release-evidence/v1', 'checkout_sha': revision,
                    'package_version': version, 'servers': {'postgresql': postgres, 'nats': nats},
                    'runtime': runtime, 'images': images}
    except Exception:
        raise RuntimeError('release environment evidence collection failed') from None
    print('RELEASE_EVIDENCE ' + json.dumps(evidence, sort_keys=True))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'config', 'up', 'smoke', 'api-smoke', 'evidence', 'status', 'logs', 'down'))
    args = parser.parse_args()
    if args.action in ('init', 'config', 'up', 'smoke', 'api-smoke'):
        initialize()
    if args.action == 'init':
        print('Local secrets ready under git-ignored local/compose-secrets. Values not printed. Existing secrets retained.')
    elif args.action == 'config':
        compose('config', '--quiet')
    elif args.action == 'up':
        start_stack()
        compose('ps', '-a')
    elif args.action == 'smoke':
        start_stack()
        compose('--profile', 'tools', 'run', '--rm', 'smoke')
        api_smoke()
        api_upload_smoke()
        release_evidence()
    elif args.action == 'api-smoke':
        start_stack()
        api_smoke()
        api_upload_smoke()
        release_evidence()
    elif args.action == 'evidence':
        release_evidence()
    elif args.action == 'status':
        compose('ps', '-a')
    elif args.action == 'logs':
        compose('logs', '--tail', '100', 'bootstrap', 'worker', 'api', 'postgres', 'nats')
    elif args.action == 'down':
        compose('down')
        print('Named volumes and local secrets retained. Do not remove or regenerate secrets while reusing these volumes.')


if __name__ == '__main__':
    main()
