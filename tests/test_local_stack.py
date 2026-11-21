"""Static and secret-generation checks. Full stack deployment requires the compose-smoke CI job."""
import importlib.util
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock, call
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('local_stack', ROOT / 'scripts/local_stack.py')
stack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stack)
_runtime_spec = importlib.util.spec_from_file_location('local_runtime', ROOT / 'deploy/local/runtime.py')
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


class LocalCompose(unittest.TestCase):
    def test_secret_generation_is_idempotent_and_not_in_compose(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = stack.initialize(root)
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            stack.initialize(root)
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            config = (directory / 'nats.conf').read_text()
            self.assertIn((directory / 'nats_token').read_text().strip(), config)
            self.assertNotEqual(before['pg_admin'], before['pg_app'])
            compose = (ROOT / 'deploy/local/compose.json').read_text()
            for name in ('pg_admin','pg_app','nats_token','pseudonym_salt','api_token'):
                self.assertNotIn(before[name].decode().strip(), compose)
            self.assertEqual((directory / 'api_token').stat().st_mode & 0o777, 0o600)
            self.assertRegex(before['api_token'].decode(), r'^[0-9a-f]{64}\n$')

    def test_symlink_or_corrupt_secret_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = stack.initialize(root)
            (directory / 'pg_app').chmod(0o600)
            (directory / 'pg_app').write_text('bad')
            with self.assertRaises(ValueError):
                stack.initialize(root)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'local').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(ValueError):
                stack.initialize(root)

    def test_stack_contract(self):
        config = json.loads((ROOT / 'deploy/local/compose.json').read_text())
        services = config['services']
        self.assertEqual(services['postgres']['image'], 'postgres:18')
        self.assertIn('postgres_data:/var/lib/postgresql', services['postgres']['volumes'])
        for name in ('postgres', 'nats'):
            self.assertTrue(all(p.startswith('127.0.0.1:') for p in services[name]['ports']))
        self.assertEqual(services['worker']['depends_on']['bootstrap']['condition'], 'service_completed_successfully')
        self.assertEqual(services['worker']['user'], '10001:10001')
        self.assertEqual(services['nats']['user'], '10001:10001')
        self.assertEqual(services['prepare']['user'], '0:0')
        self.assertEqual(services['prepare']['secrets'] if 'secrets' in services['prepare'] else [], [])
        self.assertNotIn('pg_admin', services['worker']['secrets'])
        self.assertEqual(services['bootstrap']['restart'], 'no')
        self.assertIn('blob_data:/srv/datamesh/blobs', services['worker']['volumes'])
        self.assertEqual(set(config['volumes']), {'postgres_data','nats_data','blob_data','api_secrets'})

    def test_image_explicit_copies_exclude_secrets_and_private_references(self):
        dockerfile = (ROOT / 'deploy/local/Dockerfile').read_text()
        self.assertNotIn('COPY . ', dockerfile)
        self.assertNotIn('COPY references', dockerfile)
        self.assertNotIn('COPY local', dockerfile)
        self.assertIn("'.[postgres,nats,api]'", dockerfile)
        self.assertIn('install -d -o 10001 -g 10001 -m 0700 /run/currentcraft-secrets', dockerfile)
        ignore = (ROOT / '.dockerignore').read_text()
        self.assertTrue(ignore.startswith('**\n'))
        self.assertNotIn('!references', ignore)

    def test_init_shell_syntax(self):
        subprocess.run(['bash', '-n', str(ROOT / 'deploy/local/init_postgres.sh')], check=True)

    def test_runtime_and_helper_compile(self):
        for rel in ('deploy/local/runtime.py', 'scripts/local_stack.py'):
            compile((ROOT / rel).read_text(), rel, 'exec')

    def test_api_service_contract_and_unchanged_storage_identities(self):
        config = json.loads((ROOT / 'deploy/local/compose.json').read_text())
        api = config['services']['api']
        self.assertEqual(config['name'], 'datamesh-local')
        self.assertEqual(api['image'], config['services']['worker']['image'])
        self.assertEqual(api['command'], ['api'])
        helper = config['services']['api-secrets']
        for service in (api, helper):
            self.assertEqual(service['user'], '10001:10001')
            self.assertEqual(service['cap_drop'], ['ALL'])
            self.assertEqual(service['security_opt'], ['no-new-privileges:true'])
            self.assertNotIn('cap_add', service)
            self.assertNotIn('secrets', service)
        self.assertEqual(api['volumes'], ['blob_data:/srv/datamesh/blobs',
                                         'api_secrets:/run/currentcraft-secrets:ro'])
        self.assertEqual(helper['volumes'], ['api_secrets:/run/currentcraft-secrets'])
        self.assertEqual(helper['command'], ['provision-api-secrets'])
        self.assertEqual(helper['network_mode'], 'none')
        self.assertEqual(api['depends_on'], {'bootstrap': {'condition': 'service_completed_successfully'}})
        self.assertEqual(api['ports'], ['127.0.0.1:${CURRENTCRAFT_API_PORT-${DATAMESH_API_PORT:-8000}}:8000'])
        self.assertIn('/readyz', api['healthcheck']['test'][-1])
        self.assertIn('assert r.status == 200', api['healthcheck']['test'][-1])
        self.assertNotIn('api_token', config['secrets'])
        self.assertEqual(api['environment']['CURRENTCRAFT_PG_DATABASE'], 'datamesh')
        self.assertEqual(api['environment']['CURRENTCRAFT_PG_USER'], 'datamesh_app')
        self.assertEqual(api['environment']['CURRENTCRAFT_PG_PORT'], '5432')

    def test_api_token_exclusive_owner_only_and_never_printed(self):
        with tempfile.TemporaryDirectory() as temp:
            output = io.StringIO()
            original = os.open
            with patch.object(stack.os, 'open', wraps=original) as opened, contextlib.redirect_stdout(output):
                directory = stack.initialize(Path(temp))
            token = directory / 'api_token'
            self.assertIn(call(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), opened.call_args_list)
            self.assertEqual(output.getvalue(), '')
            before = token.read_bytes()
            token.chmod(0o644)
            stack.initialize(Path(temp))
            self.assertEqual(token.read_bytes(), before)
            self.assertEqual(token.stat().st_mode & 0o777, 0o600)
            token.write_text('bad')
            with self.assertRaisesRegex(ValueError, 'invalid existing generated secret'):
                stack.initialize(Path(temp))

    def test_api_token_symlink_refused_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = stack.initialize(root)
            target = root / 'synthetic-token'
            target.write_text('synthetic')
            (directory / 'api_token').unlink()
            (directory / 'api_token').symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'symlink secret file'):
                stack.initialize(root)
            self.assertEqual(target.read_text(), 'synthetic')

    def test_preferred_and_legacy_names_and_empty_precedence(self):
        for suffix in ('API_PORT', 'PG_PORT', 'NATS_PORT', 'WORKBOOK_PROFILES',
                       'INPUT_FILE', 'INPUT_FORMAT', 'SOURCE_ID', 'MAPPING', 'BINDING_FILE',
                       'API_TOKEN_FILE', 'PG_APP_FILE', 'NATS_TOKEN_FILE', 'NATS_SERVERS',
                       'PG_HOST', 'PG_DATABASE', 'PG_USER', 'DEPENDENCY_TIMEOUT_SECONDS'):
            old, new = 'DATAMESH_' + suffix, 'CURRENTCRAFT_' + suffix
            for supplied, expected in (({old: 'legacy'}, 'legacy'), ({new: 'preferred'}, 'preferred'),
                                       ({old: 'legacy', new: 'preferred'}, 'preferred'),
                                       ({old: 'legacy', new: ''}, '')):
                with self.subTest(suffix=suffix, supplied=supplied):
                    original = dict(supplied)
                    self.assertEqual(stack.configuration_environment(supplied)[old], expected)
                    bridged = dict(supplied)
                    runtime.configuration_bridge(bridged)
                    self.assertEqual(bridged[old], expected)
                    self.assertEqual(supplied, original)
        config = json.loads((ROOT / 'deploy/local/compose.json').read_text())
        for service, suffix, default, internal in (('api', 'API_PORT', 8000, 8000),
                                                   ('postgres', 'PG_PORT', 5433, 5432),
                                                   ('nats', 'NATS_PORT', 4222, 4222)):
            self.assertEqual(config['services'][service]['ports'][0],
                             f'127.0.0.1:${{CURRENTCRAFT_{suffix}-${{DATAMESH_{suffix}:-{default}}}}}:{internal}')
        for service in ('publisher', 'worker'):
            for name, expression in config['services'][service]['environment'].items():
                self.assertTrue(name.startswith('CURRENTCRAFT_'))
                self.assertIn('${' + name + '-${DATAMESH_', expression)

    def test_nonroot_provisioning_is_private_atomic_and_idempotent(self):
        # Exercise real files under the test runner's nonroot identity.
        values = dict(zip(runtime.API_SECRETS, ('a' * 64, 'b' * 64, 'c' * 64)))
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'API_UID', os.getuid()), \
                patch.object(runtime, 'API_GID', os.getgid()):
            directory = Path(temp)
            payload = json.dumps(values).encode()
            runtime.provision_api_secrets(payload, directory)
            before = {p.name: p.stat().st_ino for p in directory.iterdir()}
            runtime.provision_api_secrets(payload, directory)
            self.assertEqual(before, {p.name: p.stat().st_ino for p in directory.iterdir()})
            self.assertEqual(set(before), set(runtime.API_SECRETS))
            for name, value in values.items():
                self.assertEqual((directory / name).read_text(), value + '\n')
                self.assertEqual((directory / name).stat().st_mode & 0o777, 0o400)

    def test_nonroot_provisioning_refuses_malformed_input_before_any_write(self):
        valid = dict.fromkeys(runtime.API_SECRETS, 'a' * 64)
        invalid = (b'x' * 4097, b'not-json', b'[]', b'{}',
                   json.dumps(dict(valid, extra='a' * 64)).encode(),
                   json.dumps(dict(valid, api_token='bad')).encode())
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'API_UID', os.getuid()), \
                patch.object(runtime, 'API_GID', os.getgid()):
            for payload in invalid:
                with self.assertRaisesRegex(RuntimeError, 'provisioning failed'):
                    runtime.provision_api_secrets(payload, Path(temp))
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_nonroot_provisioning_refuses_rotation_symlinks_and_bad_permissions(self):
        values = dict.fromkeys(runtime.API_SECRETS, 'a' * 64)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'API_UID', os.getuid()), \
                patch.object(runtime, 'API_GID', os.getgid()):
            directory = Path(temp)
            payload = json.dumps(values).encode()
            runtime.provision_api_secrets(payload, directory)
            with self.assertRaises(RuntimeError):
                runtime.provision_api_secrets(json.dumps(dict(values, api_token='b' * 64)).encode(), directory)
            token = directory / 'api_token'
            self.assertEqual(token.read_text().strip(), 'a' * 64)
            token.chmod(0o644)
            with self.assertRaises(RuntimeError):
                runtime.provision_api_secrets(payload, directory)
            token.unlink()
            token.symlink_to(directory / 'pg_app')
            with self.assertRaises(RuntimeError):
                runtime.provision_api_secrets(payload, directory)
            self.assertEqual((directory / 'pg_app').read_text().strip(), 'a' * 64)

    def test_api_launch_validates_nonroot_and_execs_without_privilege_calls(self):
        values = dict.fromkeys(runtime.API_SECRETS, 'a' * 64)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'API_UID', os.getuid()), \
                patch.object(runtime, 'API_GID', os.getgid()), \
                patch.object(runtime, 'API_SECRET_DIR', Path(temp)), \
                patch.object(runtime.os, 'environ', {}), \
                patch.object(runtime.os, 'execv') as execute, \
                patch.object(runtime.os, 'setuid') as setuid, \
                patch.object(runtime.os, 'setgid') as setgid, \
                patch.object(runtime.os, 'chown') as chown:
            runtime.provision_api_secrets(json.dumps(values).encode(), Path(temp))
            runtime.launch_api()
            argv = execute.call_args.args[1]
            self.assertIn('0.0.0.0', argv)
            self.assertIn('--no-access-log', argv)
            self.assertEqual(runtime.os.environ['DATAMESH_API_TOKEN_FILE'], str(Path(temp) / 'api_token'))
            setuid.assert_not_called()
            setgid.assert_not_called()
            chown.assert_not_called()

    def test_api_and_provisioner_fail_closed_with_root_or_wrong_identity(self):
        for uid in (0, 12345):
            with patch.object(runtime.os, 'geteuid', return_value=uid), \
                    patch.object(runtime.os, 'execv') as execute:
                with self.assertRaises(RuntimeError):
                    runtime.launch_api()
                with self.assertRaises(RuntimeError):
                    runtime.provision_api_secrets(b'{}', Path('/nonexistent'))
                execute.assert_not_called()

    def test_host_provisioner_streams_secrets_only_on_stdin(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = stack.initialize(Path(temp))
            output = io.StringIO()
            with patch.object(stack.subprocess, 'run') as run, \
                    patch.object(stack, 'configuration_environment', return_value={}), \
                    contextlib.redirect_stdout(output):
                stack.provision_api_secrets(directory)
            args, kwargs = run.call_args
            self.assertEqual(args[0][-4:], ['--rm', '--no-deps', '-T', 'api-secrets'])
            self.assertEqual(kwargs['timeout'], 60)
            self.assertTrue(kwargs['capture_output'])
            values = json.loads(kwargs['input'])
            self.assertEqual(set(values), {'api_token', 'pg_app', 'nats_token'})
            for name, value in values.items():
                self.assertEqual(value, (directory / name).read_text().strip())
                self.assertNotIn(value, ' '.join(args[0]))
                self.assertNotIn(value, str(kwargs['env']))
                self.assertNotIn(value, output.getvalue())

    def test_provisioning_failure_prevents_api_start_and_sanitizes_output(self):
        for error in (subprocess.CalledProcessError(1, ['docker'], output=b'synthetic-sensitive-detail'),
                      subprocess.TimeoutExpired(['docker'], 60, output=b'synthetic-sensitive-detail')):
            with patch.object(stack, 'compose') as compose, \
                    patch.object(stack, 'provision_api_secrets', side_effect=RuntimeError('provision failed')):
                with self.assertRaises(RuntimeError):
                    stack.start_stack()
                self.assertEqual(compose.call_args_list, [call('build', 'prepare')])
            with tempfile.TemporaryDirectory() as temp:
                directory = stack.initialize(Path(temp))
                with patch.object(stack.subprocess, 'run', side_effect=error):
                    with self.assertRaises(RuntimeError) as raised:
                        stack.provision_api_secrets(directory)
                    self.assertNotIn('synthetic-sensitive-detail', str(raised.exception))

    def test_host_provisioner_refuses_bad_source_before_container_start(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = stack.initialize(Path(temp))
            (directory / 'api_token').write_text('invalid')
            with patch.object(stack.subprocess, 'run') as run:
                with self.assertRaises(RuntimeError):
                    stack.provision_api_secrets(directory)
                run.assert_not_called()

    def test_provisioner_stdin_is_bounded(self):
        stdin = Mock()
        stdin.buffer.read.return_value = b'{}'
        with patch.object(runtime, 'require_api_identity'), \
                patch.object(runtime.sys, 'stdin', stdin), \
                patch.object(runtime, 'provision_api_secrets') as provision:
            import asyncio
            asyncio.run(runtime.main('provision-api-secrets'))
            stdin.buffer.read.assert_called_once_with(4097)
            provision.assert_called_once_with(b'{}')

    def test_root_prepare_and_unrelated_runtime_behavior_stay_unchanged(self):
        source = (ROOT / 'deploy/local/runtime.py').read_text()
        api_source = source[source.index('def require_api_identity'):source.index('def secret(')]
        for forbidden in ('os.chown(', 'os.fchown(', 'os.setuid(', 'os.setgid(', 'os.setgroups('):
            self.assertNotIn(forbidden, api_source)
        config = json.loads((ROOT / 'deploy/local/compose.json').read_text())
        self.assertEqual(config['services']['prepare']['user'], '0:0')

    def test_shell_smoke_checks_both_auth_failures_and_success_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = stack.initialize(Path(temp))
            token = (directory / 'api_token').read_text().strip()
            output = io.StringIO()
            with patch.object(stack, 'shell_status', side_effect=[200, 200, 401, 401, 200]) as status, \
                    contextlib.redirect_stdout(output):
                stack.api_smoke(directory, {'CURRENTCRAFT_API_PORT': '8123', 'DATAMESH_API_PORT': '8999'})
            self.assertEqual([c.args[0] for c in status.call_args_list],
                             ['http://127.0.0.1:8123' + p for p in
                              ('/healthz', '/readyz', '/v1/auth/check', '/v1/auth/check', '/v1/auth/check')])
            self.assertIsNone(status.call_args_list[2].args[1])
            self.assertNotEqual(status.call_args_list[3].args[1], token)
            self.assertEqual(status.call_args_list[4].args[1], token)
            self.assertNotIn(token, output.getvalue())
            self.assertIn('PASS:', output.getvalue())

    def test_shell_smoke_bounded_failure_and_invalid_port(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = stack.initialize(Path(temp))
            with patch.object(stack.time, 'monotonic', side_effect=[0, 0, 0, 61, 61]), \
                    patch.object(stack.time, 'sleep'), patch.object(stack, 'shell_status', return_value=503):
                with self.assertRaisesRegex(RuntimeError, 'timed out'):
                    stack.api_smoke(directory, {})
            for value in ('', '0', '65536', 'invalid'):
                with self.assertRaisesRegex(ValueError, 'invalid local API port'):
                    stack.api_smoke(directory, {'CURRENTCRAFT_API_PORT': value, 'DATAMESH_API_PORT': '8000'})

    def test_http_probe_disables_proxies_and_redirects_and_hides_error_body(self):
        from urllib.error import HTTPError
        response = Mock()
        response.__enter__ = Mock(return_value=Mock(status=200))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(stack, 'build_opener', return_value=opener) as build:
            self.assertEqual(stack.shell_status('http://127.0.0.1:8000/healthz', None, 2), 200)
            self.assertIsInstance(build.call_args.args[0], stack.ProxyHandler)
            self.assertEqual(build.call_args.args[0].proxies, {})
            self.assertIsInstance(build.call_args.args[1], stack.NoRedirect)
            self.assertIsNone(stack.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.invalid'))
            error = HTTPError('http://127.0.0.1', 401, 'synthetic', {}, None)
            opener.open.side_effect = error
            self.assertEqual(stack.shell_status('http://127.0.0.1:8000/v1/auth/check', None, 2), 401)

    def test_cli_up_smoke_and_api_smoke_start_separate_api_service(self):
        for action in ('up', 'smoke', 'api-smoke'):
            with patch.object(stack, 'initialize'), patch.object(stack, 'compose') as compose, \
                    patch.object(stack, 'provision_api_secrets') as provision, \
                    patch.object(stack, 'api_smoke') as smoke, \
                    patch.object(stack, 'api_upload_smoke') as upload, \
                    patch('sys.argv', ['local_stack.py', action]):
                stack.main()
                self.assertEqual(compose.call_args_list[0], call('build', 'prepare'))
                provision.assert_called_once_with()
                self.assertIn(call('up', '-d', 'worker', 'api'), compose.call_args_list)
                if action in ('smoke', 'api-smoke'):
                    smoke.assert_called_once_with()
                    upload.assert_called_once_with()
                else:
                    smoke.assert_not_called()
                    upload.assert_not_called()
                if action == 'smoke':
                    self.assertIn(call('--profile', 'tools', 'run', '--rm', 'smoke'), compose.call_args_list)
                else:
                    self.assertNotIn(call('--profile', 'tools', 'run', '--rm', 'smoke'), compose.call_args_list)


class HttpUploadSmoke(unittest.TestCase):
    """Host-probe controls only; these are not real PostgreSQL/NATS acceptance."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = stack.initialize(self.root)
        self.token = (self.directory / 'api_token').read_text().strip()
        self.event = 'intake_' + 'a' * 32
        self.source = 'source_' + 'b' * 32
        self.content = b'Currentcraft synthetic HTTP upload smoke. Source record, not approved work.\n'

    def receipt(self, duplicate=False, **changes):
        import hashlib
        return dict({'event_id': self.event, 'stream': 'DM_RAW', 'sequence': 7,
                     'duplicate': duplicate, 'source_id': self.source,
                     'content_sha256': hashlib.sha256(self.content).hexdigest(),
                     'status_url': '/v1/intake/' + self.event,
                     'detail': 'Durably queued; not extracted. No work approval is implied.'}, **changes)

    def status(self, state='processed', **changes):
        return dict({'event_id': self.event, 'status': state,
                     'detail': 'Processed means committed source occurrences, not approved work.'}, **changes)

    def response(self, body, status=200, raw=False):
        response = Mock()
        response.status = status
        response.read.return_value = body if raw else json.dumps(body).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def run_probe(self, responses, *, timeout=2):
        opener = Mock()
        opener.open.side_effect = responses
        output = io.StringIO()
        with patch.object(stack, 'build_opener', return_value=opener) as build, \
                patch.object(stack.time, 'sleep'), contextlib.redirect_stdout(output):
            stack.api_upload_smoke(self.directory, {'CURRENTCRAFT_API_PORT': '8123'}, timeout)
        return opener, build, output.getvalue()

    def good_responses(self, pending=True):
        responses = [self.response(self.receipt(), 202)]
        if pending:
            responses.append(self.response(self.status('pending')))
        responses += [self.response(self.status()), self.response(self.receipt(True), 202),
                      self.response(self.status())]
        return responses

    def test_real_http_request_shape_polling_retry_and_safe_output(self):
        responses = self.good_responses()
        opener, build, output = self.run_probe(responses)
        self.assertIsInstance(build.call_args.args[0], stack.ProxyHandler)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], stack.NoRedirect)
        requests = [c.args[0] for c in opener.open.call_args_list]
        self.assertEqual([r.get_method() for r in requests], ['POST', 'GET', 'GET', 'POST', 'GET'])
        self.assertEqual([r.full_url for r in requests],
                         ['http://127.0.0.1:8123' + p for p in
                          ('/v1/intake/documents', '/v1/intake/' + self.event,
                           '/v1/intake/' + self.event, '/v1/intake/documents',
                           '/v1/intake/' + self.event)])
        self.assertEqual(requests[0].data, requests[3].data)
        self.assertIn(b'name="source_id"', requests[0].data)
        self.assertIn(b'name="format"\r\n\r\ntext\r\n', requests[0].data)
        self.assertIn(self.content, requests[0].data)
        for request, called in zip(requests, opener.open.call_args_list):
            self.assertEqual(request.get_header('Authorization'), 'Bearer ' + self.token)
            self.assertGreater(called.kwargs['timeout'], 0)
            self.assertLessEqual(called.kwargs['timeout'], 2)
        for response in responses:
            response.read.assert_called_once_with(8193)
            response.__exit__.assert_called_once()
        self.assertIn('PASS: real HTTP upload', output)
        for secret in (self.token, self.event, self.source, self.content.decode().strip()):
            self.assertNotIn(secret, output)

    def test_immediately_processed_is_valid_worker_race(self):
        opener, _, _ = self.run_probe(self.good_responses(pending=False))
        self.assertEqual(opener.open.call_count, 4)

    def test_every_invocation_has_fresh_source_bytes(self):
        first, _, _ = self.run_probe(self.good_responses(False))
        second, _, _ = self.run_probe(self.good_responses(False))
        self.assertNotEqual(first.open.call_args_list[0].args[0].data,
                            second.open.call_args_list[0].args[0].data)

    def test_receipt_validates_digest_stream_handles_sequence_and_fields(self):
        bad = ({'content_sha256': '0' * 64}, {'stream': 'OTHER'}, {'event_id': 'raw-event'},
               {'event_id': None}, {'source_id': 'raw-source'}, {'sequence': True},
               {'sequence': 0}, {'duplicate': 'false'}, {'detail': 'accepted'}, {'extra': 'no'})
        for values in bad:
            with self.subTest(values=values), self.assertRaisesRegex(RuntimeError, 'invalid durable receipt'):
                self.run_probe([self.response(self.receipt(**values), 202)])
        with self.assertRaisesRegex(RuntimeError, 'fresh submission'):
            self.run_probe([self.response(self.receipt(True), 202)])

    def test_untrusted_status_urls_are_rejected_before_poll(self):
        for path in ('https://example.invalid/steal', '//example.invalid/steal',
                     'http://127.0.0.1:9999/steal', '/v1/intake/' + self.event + '?next=bad',
                     '/v1/intake/' + self.event + '/elsewhere', '/v1/auth/check'):
            opener = Mock()
            opener.open.return_value = self.response(self.receipt(status_url=path), 202)
            with self.subTest(path=path), patch.object(stack, 'build_opener', return_value=opener):
                with self.assertRaisesRegex(RuntimeError, 'invalid durable receipt'):
                    stack.api_upload_smoke(self.directory, {})
            self.assertEqual(opener.open.call_count, 1)

    def test_quarantine_and_invalid_worker_status_fail_closed(self):
        for values in ({'status': 'quarantined'}, {'status': 'unknown'},
                       {'event_id': 'intake_' + 'c' * 32}, {'detail': 'approved'}, {'extra': 1}):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                self.run_probe([self.response(self.receipt(), 202), self.response(self.status(**values))])

    def test_retry_requires_same_receipt_sequence_and_processed_status(self):
        changes = ({'event_id': 'intake_' + 'c' * 32,
                    'status_url': '/v1/intake/intake_' + 'c' * 32},
                   {'source_id': 'source_' + 'c' * 32}, {'sequence': 8}, {'duplicate': False})
        for values in changes:
            retry = self.receipt(True)
            retry.update(values)
            responses = [self.response(self.receipt(), 202), self.response(self.status()),
                         self.response(retry, 202)]
            with self.subTest(values=values), self.assertRaisesRegex(RuntimeError, 'retry'):
                self.run_probe(responses)
        with self.assertRaisesRegex(RuntimeError, 'retry'):
            self.run_probe([self.response(self.receipt(), 202), self.response(self.status()),
                            self.response(self.receipt(True), 202), self.response(self.status('pending'))])

    def test_pending_polling_has_one_bounded_deadline(self):
        import itertools
        ticks = itertools.count(0, 0.25)
        with patch.object(stack.time, 'monotonic', side_effect=lambda: next(ticks)):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                self.run_probe([self.response(self.receipt(), 202), self.response(self.status('pending'))],
                               timeout=1)

    def test_bad_json_oversize_and_reflected_token_never_leak(self):
        for raw in (b'not-json', b'[]', b'x' * 8193,
                    json.dumps({'leaked': self.token}).encode()):
            with self.subTest(kind=raw[:10]), self.assertRaises(RuntimeError) as raised:
                self.run_probe([self.response(raw, 202, raw=True)])
            self.assertEqual(str(raised.exception), 'HTTP intake smoke request failed')
            self.assertNotIn(self.token, str(raised.exception))

    def test_http_errors_redirects_transport_and_non202_fail_safely(self):
        from urllib.error import HTTPError, URLError
        for code in (301, 302, 401, 413, 422, 500, 503):
            error = HTTPError('http://127.0.0.1:8123/private', code, self.token, {}, None)
            with self.subTest(code=code), self.assertRaisesRegex(RuntimeError, '^HTTP intake smoke request failed$'):
                self.run_probe([error])
        with self.assertRaisesRegex(RuntimeError, '^HTTP intake smoke request failed$'):
            self.run_probe([URLError(self.token)])
        with self.assertRaisesRegex(RuntimeError, '^HTTP intake smoke request failed$'):
            self.run_probe([self.response(self.receipt(), 200)])

    def test_invalid_timeout_port_or_token_refused_without_http(self):
        for timeout in (0, -1, float('nan'), float('inf'), True, '60'):
            with self.subTest(timeout=timeout), patch.object(stack, 'build_opener') as build:
                with self.assertRaises(ValueError):
                    stack.api_upload_smoke(self.directory, {}, timeout)
                build.assert_not_called()
        for port in ('', '0', '65536', 'not-a-port'):
            with self.subTest(port=port), patch.object(stack, 'build_opener') as build:
                with self.assertRaises(ValueError):
                    stack.api_upload_smoke(self.directory, {'CURRENTCRAFT_API_PORT': port})
                build.assert_not_called()
        (self.directory / 'api_token').write_text('invalid')
        with patch.object(stack, 'build_opener') as build, self.assertRaises(ValueError):
            stack.api_upload_smoke(self.directory, {})
        build.assert_not_called()

    def test_loopback_http_wire_probe_against_controlled_server(self):
        # Exercises multipart urllib transport, NOT the application/DB/broker stack.
        import email.parser
        import email.policy
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        outer = self
        uploads = []
        polls = []
        errors = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                try:
                    outer.assertEqual(self.path, '/v1/intake/documents')
                    outer.assertEqual(self.headers['Authorization'], 'Bearer ' + outer.token)
                    body = self.rfile.read(int(self.headers['Content-Length']))
                    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                        ('Content-Type: ' + self.headers['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
                    fields = {p.get_param('name', header='content-disposition'): p.get_payload(decode=True)
                              for p in message.iter_parts()}
                    outer.assertEqual(fields['format'], b'text')
                    outer.assertRegex(fields['source_id'].decode(), r'^synthetic-http-smoke-[0-9a-f]{32}$')
                    outer.assertEqual(fields['file'], outer.content)
                    uploads.append(body)
                    self.reply(202, outer.receipt(len(uploads) > 1))
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    self.reply(500, {})

            def do_GET(self):
                try:
                    outer.assertEqual(self.path, '/v1/intake/' + outer.event)
                    outer.assertEqual(self.headers['Authorization'], 'Bearer ' + outer.token)
                    polls.append(self.path)
                    self.reply(200, outer.status('pending' if len(polls) == 1 else 'processed'))
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    self.reply(500, {})

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                stack.api_upload_smoke(self.directory, {'CURRENTCRAFT_API_PORT': str(server.server_port)}, 5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(len(uploads), 2)
        self.assertEqual(uploads[0], uploads[1])
        self.assertEqual(len(polls), 3)
        self.assertIn('PASS: real HTTP upload', output.getvalue())
        self.assertNotIn(self.token, output.getvalue())
