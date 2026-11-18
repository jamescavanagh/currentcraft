"""Deterministic OpenAPI contract generator and drift checker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.interfaces.http.app import create_app  # noqa: E402


def render_openapi_bytes() -> bytes:
    schema = create_app().openapi()
    serialized = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return serialized.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify docs/contracts/OPENAPI.json."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify docs/contracts/OPENAPI.json matches generated OpenAPI schema.",
    )
    args = parser.parse_args()

    target = REPO_ROOT / "docs" / "contracts" / "OPENAPI.json"
    expected = render_openapi_bytes()

    if args.check:
        if not target.is_file():
            print(f"Missing OpenAPI contract: {target}", file=sys.stderr)
            return 1
        actual = target.read_bytes()
        if actual != expected:
            print(
                f"Stale OpenAPI contract: {target}. Run `python scripts/gen_openapi.py`.",
                file=sys.stderr,
            )
            return 1
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
