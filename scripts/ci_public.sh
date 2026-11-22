#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
export DATAMESH_REQUIRE_API_TESTS=1
# Explicit modules prevent discovery from silently losing or skipping API coverage.
python3 - <<'API_TESTS'
import os
import sys
import unittest

if os.environ.get("DATAMESH_REQUIRE_API_TESTS") != "1":
    raise SystemExit("Required API-test guard is not enabled")
modules = (
    "tests.test_http_e2e", "tests.test_http_api", "tests.test_http_settings",
    "tests.test_http_layering", "tests.test_http_document_projection",
    "tests.test_http_documents", "tests.test_http_intake",
    "tests.test_intake_parser_limits", "tests.test_intake_receipts",
    "tests.test_intake_wiring",
)
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for name in modules:
    required = loader.loadTestsFromName(name)
    if required.countTestCases() == 0:
        raise SystemExit("Required API module contains no tests: " + name)
    suite.addTests(required)
if loader.errors:
    raise SystemExit("Required API modules failed to import:\n" + "\n".join(loader.errors))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped or result.expectedFailures:
    raise SystemExit("Required API tests must pass without skips or expected failures")
print("PASS: required API tests executed without skips (DATAMESH_REQUIRE_API_TESTS=1)")
API_TESTS
# The L-system loader gate was once skipped until the loader existed; it may never skip again.
python3 - <<'LSYS_TESTS'
import unittest

modules = ("tests.test_lsys_resource_symbols", "tests.test_lsys_grammar", "tests.domain.test_needs_and_scope")
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for name in modules:
    required = loader.loadTestsFromName(name)
    if required.countTestCases() == 0:
        raise SystemExit("Required L-system module contains no tests: " + name)
    suite.addTests(required)
if loader.errors:
    raise SystemExit("Required L-system modules failed to import:\n" + "\n".join(loader.errors))
result = unittest.TextTestRunner(verbosity=1).run(suite)
if not result.wasSuccessful() or result.skipped or result.expectedFailures:
    raise SystemExit("Required L-system tests must pass without skips or expected failures")
print("PASS: required L-system tests executed without skips")
LSYS_TESTS
python3 scripts/check_release.py
python3 scripts/gen_contract_docs.py --check
python3 scripts/gen_gauge_contract_docs.py --check
python3 scripts/gen_agency_contract_docs.py --check
python3 scripts/gen_feature_graph_docs.py --check
python3 scripts/gen_six_type_docs.py --check
python3 scripts/gen_domain_scaffold_docs.py --check
python3 scripts/gen_persistence_docs.py --check
python3 scripts/gen_readiness_contract_docs.py --check
python3 scripts/gen_openapi.py --check
# Line and branch coverage of src/app (config: [tool.coverage.*] in pyproject.toml). Report-only, no floor yet.
# CI sets DATAMESH_REQUIRE_COVERAGE=1 so a missing coverage install fails instead of silently not measuring.
if python3 -c "import coverage" 2>/dev/null; then
  python3 -m coverage erase
  python3 -m coverage run -m unittest discover -s tests -t . -v
  python3 -m coverage report
  python3 -m coverage xml -q -o coverage.xml
  python3 -m coverage json -q -o coverage.json
elif [ "${DATAMESH_REQUIRE_COVERAGE:-0}" = "1" ]; then
  echo "coverage is required (DATAMESH_REQUIRE_COVERAGE=1) but not installed" >&2
  exit 1
else
  echo "NOTE: coverage not installed; tests run unmeasured"
  python3 -m unittest discover -s tests -t . -v
fi
