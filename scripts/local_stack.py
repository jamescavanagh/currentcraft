"""Manage the local NATS + PostgreSQL Compose stack. Requires Docker Engine and Compose v2.

Secrets are generated locally, never printed or bundled. `down` retains named volumes; no delete-volumes command.
"""
import argparse
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


def api_smoke(directory=SECRET_DIR, environ=None, timeout=60):
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
    wrong = ('0' if token[0] != '0' else '1') + token[1:]
    deadline = time.monotonic() + timeout
    base = 'http://127.0.0.1:' + str(port)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'config', 'up', 'smoke', 'api-smoke', 'status', 'logs', 'down'))
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
    elif args.action == 'api-smoke':
        start_stack()
        api_smoke()
    elif args.action == 'status':
        compose('ps', '-a')
    elif args.action == 'logs':
        compose('logs', '--tail', '100', 'bootstrap', 'worker', 'api', 'postgres', 'nats')
    elif args.action == 'down':
        compose('down')
        print('Named volumes and local secrets retained. Do not remove or regenerate secrets while reusing these volumes.')


if __name__ == '__main__':
    main()
