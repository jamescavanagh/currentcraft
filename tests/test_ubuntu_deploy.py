"""Non-mutating checks only. Does not claim an executed Ubuntu deployment."""
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'deploy_postgres_ubuntu.sh'


class UbuntuDeploy(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], capture_output=True, text=True)

    def test_bash_syntax(self):
        r = subprocess.run(['bash', '-n', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_help(self):
        r = self.run_script('--help')
        self.assertEqual(r.returncode, 0)
        self.assertIn('--pgvector', r.stdout)

    def test_dry_run(self):
        r = self.run_script('--dry-run', '--port', '5543', '--pgvector')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('5543', r.stdout)
        self.assertIn('CREATE EXTENSION', r.stdout)

    def test_invalid_options(self):
        for args in [('--port',), ('--port', '22', '--dry-run'), ('--port', '65536', '--dry-run'),
                     ('--port', '5433;false', '--dry-run'), ('--unknown',)]:
            self.assertNotEqual(self.run_script(*args).returncode, 0)
