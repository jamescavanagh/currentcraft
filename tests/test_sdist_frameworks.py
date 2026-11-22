"""Build an sdist, unpack it, and run framework tests without checkout imports."""
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_release import candidates

REQUIRED = (
    'references/public/framework.synthetic.v1.json',
    'references/public/framework.meta.synthetic.v1.json',
    'tests/fixtures/framework_profiles/framework.meta.synthetic.v1.json',
    'tests/fixtures/framework_profiles/synthetic_profiles.json',
)
MODULES = (
    'tests.test_synthetic_meta_ref',
    'tests.test_synthetic_meta_framework',
    'tests.integration.test_public_framework_fixture',
    'tests.test_framework_profiles',
)
CHILD = r'''
import importlib, os, pathlib, sys, unittest
root = pathlib.Path(sys.argv[1]).resolve()
os.chdir(root)
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'src'))
modules = sys.argv[2:]
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for name in modules:
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), 'test module escaped sdist'
    tests = loader.loadTestsFromModule(module)
    assert tests.countTestCases() > 0, 'empty framework module'
    suite.addTests(tests)
assert not loader.errors, 'test import errors'
# Existing framework tests import app classes. They must come from the unpacked
# source, never an installed checkout or another copy on PYTHONPATH.
for name, module in tuple(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        file = getattr(module, '__file__', None)
        if file:
            assert pathlib.Path(file).resolve().is_relative_to(root / 'src'), 'app import escaped sdist'
result = unittest.TextTestRunner(verbosity=1).run(suite)
if not result.wasSuccessful() or result.skipped or result.expectedFailures:
    raise SystemExit(1)
print('UNPACKED_SDIST_FRAMEWORK_TESTS_PASSED', result.testsRun)
'''


def clean_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ('PYTHONPATH', 'PYTHONHOME') and not k.startswith('GIT_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


class UnpackedSdistFrameworkTests(unittest.TestCase):
    def test_frameworks_run_from_unpacked_sdist_without_checkout_fallback(self):
        with TemporaryDirectory(prefix='framework-sdist-') as temp:
            work = Path(temp)
            build_root = work / 'source'
            build_root.mkdir()
            # Copy only declared public source. Never copy local REF or secrets.
            for source in candidates(ROOT):
                self.assertFalse(source.is_symlink(), 'symlink in public source')
                destination = build_root / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            # Fictional canaries test exclusion without touching real private data.
            forbidden = (
                'references/private/sdist-test-canary.json',
                'references/public/unreviewed-sdist-test-canary.json',
                '.env',
                'data/sdist-test-canary.txt',
            )
            for relative in forbidden:
                target = build_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('SYNTHETIC_SDIST_EXCLUSION_CANARY\n')
            dist = work / 'dist'
            dist.mkdir()
            build = subprocess.run(
                [sys.executable, '-I', '-c',
                 'from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])',
                 str(dist)], cwd=build_root, env=clean_env(),
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout[-3000:] + build.stderr[-3000:])
            archives = list(dist.glob('*.tar.gz'))
            self.assertEqual(len(archives), 1)
            unpack = work / 'unpacked'
            unpack.mkdir()
            with tarfile.open(archives[0], 'r:gz') as archive:
                members = archive.getmembers()
                tops = set()
                names = set()
                self.assertLess(len(members), 20000)
                self.assertLess(sum(m.size for m in members), 100_000_000)
                for member in members:
                    path = PurePosixPath(member.name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertTrue(member.isdir() or member.isfile(), 'archive links or special files forbidden')
                    tops.add(path.parts[0])
                    if len(path.parts) > 1:
                        names.add('/'.join(path.parts[1:]))
                self.assertEqual(len(tops), 1)
                for relative in REQUIRED:
                    self.assertIn(relative, names, 'required fixture missing from sdist: ' + relative)
                for relative in forbidden:
                    self.assertNotIn(relative, names, 'canary was packaged: ' + relative)
                self.assertFalse(any(name.startswith('references/private/') or name.startswith('data/')
                                     or name.split('/')[-1].startswith('.env') for name in names))
                archive.extractall(unpack, filter='data')
            unpacked_root = unpack / next(iter(tops))
            # Remove the staging source to make accidental build-tree reads fail.
            shutil.rmtree(build_root)
            child = subprocess.run(
                [sys.executable, '-I', '-c', CHILD, str(unpacked_root), *MODULES],
                cwd=unpacked_root, env=clean_env(), capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(child.returncode, 0, child.stdout[-4000:] + child.stderr[-4000:])
            self.assertIn('UNPACKED_SDIST_FRAMEWORK_TESTS_PASSED', child.stdout)


if __name__ == '__main__':
    unittest.main()
