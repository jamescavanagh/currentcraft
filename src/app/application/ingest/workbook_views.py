"""Read-only projections over workbook source occurrences. Pydantic/stdlib only; no I/O.

wbs_outline() gives the explicit hierarchy column a task tool needs to import a WBS (code, parent code, level),
derived per revision. It is a view for review and later import, not an importer and not a business identity.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import DomainObject

OUTLINE_COLUMNS = ("wbs_code", "parent_wbs_code", "wbs_level", "name", "row_kind", "phase_code", "subsystem_code",
                   "subsystem_state", "hierarchy_basis", "parent_status", "labor_hours_known", "roles_with_input",
                   "labor_sources", "responsible_party", "responsibility_raw", "locator")


def wbs_outline(objects: Iterable[DomainObject]) -> list[dict]:
    """Phases and task occurrences in sheet order, one row each, with an explicit hierarchy column."""
    rows = []
    for o in objects:
        if o.kind not in ("phase_scope", "wbs_task"):
            continue
        f = o.fields
        row = {k: f.get(k) for k in OUTLINE_COLUMNS if k != "name"}
        row["name"] = o.title
        if o.kind == "phase_scope":
            row["row_kind"] = "phase"
        rows.append((f.get("row") or 0, row))
    return [r for _, r in sorted(rows, key=lambda x: x[0])]
