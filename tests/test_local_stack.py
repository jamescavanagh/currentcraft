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
        self.assertEqual(set(config['volumes']), {'postgres_data','nats_data','blob_data'})

    def test_image_explicit_copies_exclude_secrets_and_private_references(self):
        dockerfile = (ROOT / 'deploy/local/Dockerfile').read_text()
        self.assertNotIn('COPY . ', dockerfile)
        self.assertNotIn('COPY references', dockerfile)
        self.assertNotIn('COPY local', dockerfile)
        self.assertIn("'.[postgres,nats,api]'", dockerfile)
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
        self.assertEqual(api['user'], '0:0')  # staging only; launch_api drops privileges
        self.assertEqual(set(api['secrets']), {'pg_app', 'nats_token', 'api_token'})
        self.assertEqual(api['volumes'], ['blob_data:/srv/datamesh/blobs'])
        self.assertEqual(api['depends_on'], {'bootstrap': {'condition': 'service_completed_successfully'}})
        self.assertEqual(api['ports'], ['127.0.0.1:${CURRENTCRAFT_API_PORT-${DATAMESH_API_PORT:-8000}}:8000'])
        self.assertEqual(api['cap_drop'], ['ALL'])
        self.assertEqual(set(api['cap_add']), {'CHOWN', 'SETUID', 'SETGID', 'DAC_OVERRIDE'})
        self.assertEqual(api['security_opt'], ['no-new-privileges:true'])
        self.assertTrue(api['tmpfs'][0].startswith('/run/currentcraft:'))
        self.assertIn('noexec,nosuid,nodev', api['tmpfs'][0])
        self.assertIn('/readyz', api['healthcheck']['test'][-1])
        self.assertIn('assert r.status == 200', api['healthcheck']['test'][-1])
        self.assertEqual(config['secrets']['api_token']['file'], '../../local/compose-secrets/api_token')
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

    def test_staged_secrets_are_private_and_owned_by_api_uid(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'secret', return_value='a' * 64), \
                patch.object(runtime.os, 'fchown') as owner, \
                patch.object(runtime.os, 'chown') as directory_owner:
            stage = runtime.stage_api_secrets(temp)
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            self.assertEqual(owner.call_count, 3)
            for args in owner.call_args_list:
                self.assertEqual(args.args[1:], (10001, 10001))
            directory_owner.assert_called_once_with(stage, 10001, 10001)
            for name in ('api_token', 'pg_app', 'nats_token'):
                self.assertEqual((stage / name).stat().st_mode & 0o777, 0o400)
                self.assertEqual((stage / name).read_text(), 'a' * 64 + '\n')

    def test_api_launch_stages_then_drops_privilege_before_exec(self):
        order = Mock()
        with patch.object(runtime.os, 'geteuid', side_effect=[0, 10001]), \
                patch.object(runtime.os, 'getuid', return_value=10001), \
                patch.object(runtime.os, 'getgid', return_value=10001), \
                patch.object(runtime.os, 'environ', {}), \
                patch.object(runtime, 'stage_api_secrets', order.stage), \
                patch.object(runtime.os, 'setgroups', order.groups), \
                patch.object(runtime.os, 'setgid', order.gid), \
                patch.object(runtime.os, 'setuid', order.uid), \
                patch.object(runtime.os, 'execv', order.execute):
            order.stage.return_value = Path('/run/currentcraft/api-synthetic')
            runtime.launch_api()
            self.assertEqual([c[0] for c in order.mock_calls], ['stage', 'groups', 'gid', 'uid', 'execute'])
            order.groups.assert_called_once_with([])
            order.gid.assert_called_once_with(10001)
            order.uid.assert_called_once_with(10001)
            argv = order.execute.call_args.args[1]
            self.assertIn('0.0.0.0', argv)
            self.assertIn('--no-access-log', argv)
            self.assertNotIn('/run/secrets', ' '.join(argv))
            self.assertEqual(runtime.os.environ['DATAMESH_API_TOKEN_FILE'],
                             '/run/currentcraft/api-synthetic/api_token')

    def test_api_launch_fails_closed_without_secret_or_privilege(self):
        for error in (OSError('synthetic-sensitive-detail'), ValueError('synthetic-sensitive-detail')):
            with patch.object(runtime.os, 'geteuid', return_value=0), \
                    patch.object(runtime, 'stage_api_secrets', side_effect=error), \
                    patch.object(runtime.os, 'execv') as execute:
                with self.assertRaises(RuntimeError) as raised:
                    runtime.launch_api()
                self.assertNotIn('synthetic-sensitive-detail', str(raised.exception))
                execute.assert_not_called()
        with patch.object(runtime.os, 'geteuid', return_value=10001), \
                patch.object(runtime, 'stage_api_secrets') as stage:
            with self.assertRaises(RuntimeError):
                runtime.launch_api()
            stage.assert_not_called()

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
                    patch.object(stack, 'api_smoke') as smoke, \
                    patch('sys.argv', ['local_stack.py', action]):
                stack.main()
                self.assertIn(call('up', '-d', '--build', 'worker', 'api'), compose.call_args_list)
                if action in ('smoke', 'api-smoke'):
                    smoke.assert_called_once_with()
                else:
                    smoke.assert_not_called()
                if action == 'smoke':
                    self.assertIn(call('--profile', 'tools', 'run', '--rm', 'smoke'), compose.call_args_list)
                else:
                    self.assertNotIn(call('--profile', 'tools', 'run', '--rm', 'smoke'), compose.call_args_list)
