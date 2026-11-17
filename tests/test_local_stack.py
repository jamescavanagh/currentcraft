"""Static and secret-generation checks. Full stack deployment requires the compose-smoke CI job."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('local_stack', ROOT / 'scripts/local_stack.py')
stack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stack)


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
            for name in ('pg_admin','pg_app','nats_token','pseudonym_salt'):
                self.assertNotIn(before[name].decode().strip(), compose)

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
        self.assertIn("'.[postgres,nats]'", dockerfile)
        ignore = (ROOT / '.dockerignore').read_text()
        self.assertTrue(ignore.startswith('**\n'))
        self.assertNotIn('!references', ignore)

    def test_init_shell_syntax(self):
        subprocess.run(['bash', '-n', str(ROOT / 'deploy/local/init_postgres.sh')], check=True)

    def test_runtime_and_helper_compile(self):
        for rel in ('deploy/local/runtime.py', 'scripts/local_stack.py'):
            compile((ROOT / rel).read_text(), rel, 'exec')
