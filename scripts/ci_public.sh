#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
python3 scripts/check_release.py
python3 scripts/gen_contract_docs.py --check
python3 scripts/gen_gauge_contract_docs.py --check
python3 scripts/gen_agency_contract_docs.py --check
python3 scripts/gen_domain_scaffold_docs.py --check
python3 scripts/gen_persistence_docs.py --check
python3 scripts/gen_openapi.py --check
python3 -m unittest discover -s tests -t . -v
