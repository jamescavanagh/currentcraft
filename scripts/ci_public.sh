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
python3 scripts/check_release.py
python3 scripts/gen_contract_docs.py --check
python3 scripts/gen_gauge_contract_docs.py --check
python3 scripts/gen_agency_contract_docs.py --check
python3 scripts/gen_domain_scaffold_docs.py --check
python3 scripts/gen_persistence_docs.py --check
python3 scripts/gen_readiness_contract_docs.py --check
python3 scripts/gen_openapi.py --check
python3 -m unittest discover -s tests -t . -v
