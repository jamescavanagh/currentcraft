"""Acceptance tests for docs/pipelines/XLSX_WORKBOOK.md. Synthetic workbook and profile only; no enterprise data.

A private check runs only when DATAMESH_PRIVATE_WORKBOOK and DATAMESH_PRIVATE_PROFILE point at local files.
"""
import io
import os
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application.ingest import IngestConfig, IntakeBinding, RawItem, WorkbookProfile, wbs_outline  # noqa: E402
from app.infrastructure.ingest import build_ingest, put_raw, shift_formula  # noqa: E402

WHEN = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
CFG = IngestConfig(pseudonym_salt="synthetic-salt-0123456789")
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
STYLE = {None: 0, "bold": 1, "bolditalic": 2, "indent3": 3, "indent4": 4}
STYLES_XML = (f'<?xml version="1.0"?><styleSheet {NS.split(" xmlns:r")[0]}><fonts count="3"><font/><font><b/></font><font><b/><i/></font></fonts>'
              '<cellXfs count="5"><xf fontId="0"/><xf fontId="1"/><xf fontId="2"/>'
              '<xf fontId="0"><alignment indent="3"/></xf><xf fontId="0"><alignment indent="4"/></xf></cellXfs></styleSheet>')
BINDING = IntakeBinding(subject_kind="project", subject_namespace="erp.project", subject_ref="PRJ-SYNTH-1",
                        document_type="EST", revision_label="Round 1")


def _cell(ref, v, style=None):
    """v: str literal, number, ('=', formula, cached) or None."""
    s = f' s="{STYLE[style]}"' if style else ""
    if isinstance(v, tuple):
        _, f, cached = v
        val = "" if cached is None else f"<v>{escape(str(cached))}</v>"
        return f'<c r="{ref}"{s}><f>{escape(f)}</f>{val}</c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{s}><v>{v}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escape(v)}</t></is></c>'


def xlsx(sheets, styles=None) -> bytes:
    """Minimal SpreadsheetML package: {sheet: {A1: value}}; styles {sheet: {A1: style}}."""
    styles = styles or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # fixed entry timestamps: the same sheets always give the same bytes (0.9.9; was wall-clock, a flake)
        put = lambda name, text: z.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), text)  # noqa: E731
        names = list(sheets)
        put("xl/workbook.xml", f'<?xml version="1.0"?><workbook {NS}><sheets>' + "".join(
            f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
        put("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
            f'<Relationship Id="rId{i + 1}" Type="worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names))) + "</Relationships>")
        put("xl/styles.xml", STYLES_XML)
        for i, n in enumerate(names):
            rows = {}
            for ref, v in sheets[n].items():
                r = int("".join(ch for ch in ref if ch.isdigit()))
                rows.setdefault(r, []).append(_cell(ref, v, styles.get(n, {}).get(ref)))
            body = "".join(f'<row r="{r}">{"".join(cs)}</row>' for r, cs in sorted(rows.items()))
            put(f"xl/worksheets/sheet{i + 1}.xml", f'<?xml version="1.0"?><worksheet {NS}><sheetData>{body}</sheetData></worksheet>')
    return buf.getvalue()


BLOCKS = ("CDE", "FGH", "IJK", "LMN")    # R-100-26 internal, R-200-26 internal, OUT-1 contract, VEND vendor


def grid_row(r, label, inputs=None, resp=None):
    row = {f"B{r}": label, f"O{r}": ("=", "SUM(" + ",".join(f"{b[2]}{r}" for b in BLOCKS) + ")", 0)}
    for b, (cnt, hrs, tot) in enumerate(BLOCKS):
        row[f"{tot}{r}"] = ("=", f"{cnt}{r}*{hrs}{r}", 0)
        if inputs and b in inputs:
            c, h = inputs[b]
            if c is not None:
                row[f"{cnt}{r}"] = c
            if h is not None:
                row[f"{hrs}{r}"] = h
    if resp:
        row[f"P{r}"] = resp
    return row


ROWS = [  # (row, label, inputs, responsibility, style)
    (4, "Stage 1 - Discovery", None, None, "bold"),
    (5, "Site walk", {0: (2, 8)}, None, None),                       # explicit 16 h, stale cached total
    (6, "Kickoff", {1: (0, 4)}, None, None),                          # explicit zero
    (7, "Survey notes", {0: (1, None)}, None, None),                  # partial
    (8, "(copy this line above)", None, None, "bold"),
    (9, "Stage 1 Totals:", None, None, "bold"),
    (10, "Stage 2 - Design", None, None, "bold"),
    (11, "Site walk", None, None, None),                              # same label, other phase, blank
    (12, "*** Break down by sub-systems ***", None, None, "bolditalic"),
    (13, "Subsystem A (ex: RTR)", None, None, "indent3"),             # placeholder: example code never resolves
    (14, "Patch router", {0: (1, 2)}, None, "indent4"),               # leaf by indent, proposed parent 13
    (15, "NET", None, None, "indent3"),                               # sub-system, code resolved
    (16, "NET - configure VLANs", None, None, "indent3"),             # leaf by name code, proposed parent 15
    (17, "Design review", None, None, None),                          # plain: back to stem
    (18, "Install", {2: (1, 6)}, "Our Team", None),                   # contract hours, internal responsibility
    (19, "Vendor commissioning", {3: (1, 4)}, "Vendor", None),        # vendor hours priced elsewhere
    (20, "Stage 2 Totals:", None, None, "bold"),
    (21, "Stage 3 - Close", None, None, None),                        # phase text without bold
    (22, "Wrap up", None, "Drop Down", None),
    (23, "Stage 3 Totals:", None, None, "bold"),
]


def workbook(**over):
    grid = {"B1": "Effort Grid", "B2": "Rate", "C2": ("=", "Rates!C2", 100), "F2": ("=", "Rates!C3", 150),
            "B3": "Task", "C3": "R-100-26\nTechnician", "F3": "R-200-26\nEngineer", "I3": "OUT-1\nContract", "L3": "VEND\nVendor"}
    gstyle = {}
    for r, label, inputs, resp, style in ROWS:
        grid.update(grid_row(r, label, inputs, resp))
        if style:
            gstyle[f"B{r}"] = style
    rates = {"A1": "Code", "C1": "Rate", "A2": "R-100-26", "B2": "Technician", "C2": 100, "A3": "R-200-26", "B3": "Engineer", "C3": 150,
             "A4": "OUT-1", "B4": "Contract", "C4": 90,
             "E2": ("=", "Grid!E9", 0), "F2": ("=", "Grid!E20", 0), "E3": ("=", "Grid!H9", 0), "F3": ("=", "Grid!E20", 0)}
    trips = {"A1": "Code", "A2": "R-100", "B2": "Field Tech", "A3": "X-9", "B3": "Unknown", "C3": 300}
    codes = {"A1": "Code", "A2": "RTR", "B2": "Router", "A3": "NET", "B3": "Network"}
    lines = {"A1": "Class", "B1": "Qty", "C1": "Part", "D1": "Maker", "E1": "Description", "F1": "Price", "G1": "Notes",
             "A2": "Equipment", "A3": "Group 1",
             "A4": "RTR", "B4": 1, "C4": "SW-1", "D4": "Acme", "E4": "Switch", "F4": "1234.50", "G4": "see https://example.invalid/sw1 rack",
             "A5": "net", "B5": 2, "C5": "SW-1", "D5": "ACME", "E5": "Switch spare", "F5": "1234.50",
             "B6": 1, "C6": "CB-9", "D6": "Acme", "E6": "Cable", "F6": ("=", "Side!B900", 0),
             "A7": "ZZZ", "B7": 1, "E7": "Mystery", "F7": 0,
             "B8": 0, "F8": 0,
             "E9": "SUBTOTAL", "F9": ("=", "SUM(F4:F7)", 0)}
    side = {"A1": "excluded", "B2": 5}
    sheets = {"Grid": grid, "Rates": rates, "Trips": trips, "Codes": codes, "Lines": lines, "Side": side}
    sheets.update(over)
    return xlsx(sheets, {"Grid": gstyle})


PROFILE = WorkbookProfile.model_validate({
    "name": "synthetic-estimate", "version": "2", "document_type": "EST",
    "anchors": [{"sheet": "Grid", "cell": "B1", "text": "effort   grid"}, {"sheet": "Codes", "cell": "A1", "text": "Code"}],
    "vocabularies": [{"set_name": "class_code", "sheet": "Codes", "code_col": "A", "label_col": "B", "first_row": 2}],
    "catalogs": [{"kind": "rate_role", "sheet": "Rates", "first_row": 2, "code_col": "A", "label_col": "B", "fields": {"rate": "C"}},
                 {"kind": "trip_line", "sheet": "Trips", "first_row": 2, "code_col": "A", "label_col": "B", "fields": {"cost": "C"}}],
    "role_matrix": {
        "sheet": "Grid", "label_col": "B", "header_row": 3, "rate_row": 2, "first_row": 4, "last_row": 23,
        "first_block_col": "C", "block_count": 4, "row_total_col": "O", "responsibility_col": "P",
        "placeholder_values": ["Drop Down"], "task_kinds": ["task"],
        "rules": [{"row_kind": "subtotal", "pattern": "Totals:"},
                  {"row_kind": "phase", "pattern": r"^Stage\s*(\d+)", "code_group": 1},
                  {"row_kind": "copy_marker", "pattern": r"^\(copy"}],
        "hierarchy": {"section_start_pattern": r"^\*\*\*", "subsystem_min_indent": 3, "leaf_code_pattern": r"^([A-Z0-9]{2,8})\s+-\s+\S",
                      "subsystem_set": "class_code", "placeholder_pattern": r"\(ex: ([A-Z0-9]+)\)"},
        "role_classes": [{"pattern": "^R-", "labor_source": "internal"}, {"pattern": "^OUT-", "labor_source": "contract"},
                         {"pattern": "^VEND", "labor_source": "vendor", "priced_elsewhere": True}],
        "role_code_format": r"^(?P<series>[A-Z]+)-(?P<number>\d{3})-(?P<year>\d{2})$",
        "responsibility_classes": {"Our Team": ["internal"], "Vendor": ["vendor"]},
        "responsibility_precedence": "internal"},
    "line_tables": [{"name": "bill", "sheet": "Lines", "first_row": 2,
                     "columns": {"class": "A", "quantity": "B", "part_number": "C", "manufacturer": "D", "description": "E", "price": "F", "notes": "G"},
                     "money_fields": ["price"], "classification_field": "class", "classification_set": "class_code",
                     "rules": [{"row_kind": "section", "pattern": "^Equipment$", "col": "A", "sets_section": "equipment"},
                               {"row_kind": "group", "pattern": r"^Group \d+", "col": "A"},
                               {"row_kind": "subtotal", "pattern": "^SUBTOTAL$", "col": "E"}]}],
    "reference_checks": [{"name": "rate_reference", "sheet": "Rates", "first_row": 2, "last_row": 3, "code_col": "A", "ref_cols": ["E", "F"]}],
    "crosswalk_checks": [{"name": "trip_code", "source_kind": "trip_line", "target_kind": "rate_role"}],
    "excluded_sheets": ["Side"]})


def run(data, profile=PROFILE, mapping="synthetic-estimate", source_id="estimate-1", binding=BINDING):
    pipe = build_ingest(CFG, profiles=(profile,))
    raw = put_raw(pipe, platform="file", fmt="xlsx", source_id=source_id, received_at=WHEN, data=data, mapping=mapping, binding=binding)
    return pipe, raw, pipe.adapters["xlsx"].parse(raw, CFG, {})


def by(objs, kind):
    return [o for o in objs if o.kind == kind]


def rel(o, t):
    return [r.target_id for r in o.relations if r.type == t]


class XlsxWorkbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipe, cls.raw, cls.res = run(workbook())
        cls.objs = cls.res.objects
        cls.tasks = {t.fields["locator"]: t for t in by(cls.objs, "wbs_task")}
        cls.checks = {(x.fields["check"], x.fields["locator"]) for x in by(cls.objs, "ingest_diagnostic")}

    # intake and quarantine
    def test_raw_item_needs_a_profile(self):
        with self.assertRaises(ValueError):
            RawItem(platform="file", format="xlsx", source_id="x", received_at=WHEN, content=self.raw.content)

    def test_unknown_profile_and_layout_are_quarantined(self):
        self.assertIn("unknown workbook profile", run(workbook(), mapping="nope")[2].rejection.reason)
        self.assertIn("anchor Grid!B1", run(workbook(Grid={"B1": "Something else"}))[2].rejection.reason)
        self.assertIsNotNone(run(b"not a zip")[2].rejection)

    # document tied to the project
    def test_workbook_is_a_document_tied_to_the_project(self):
        doc, = by(self.objs, "project_document")
        ref, = by(self.objs, "project_reference")
        rev, = by(self.objs, "workbook_revision")
        self.assertEqual(rel(doc, "document_of"), [ref.object_id])
        self.assertEqual(rel(doc, "current_revision"), [rev.object_id])
        self.assertEqual(rel(rev, "revision_of"), [doc.object_id])
        self.assertEqual(ref.fields["reference"], "PRJ-SYNTH-1")
        self.assertEqual(ref.fields["resolution_status"], "unresolved")
        self.assertEqual(rev.fields["revision_label"], "Round 1")
        for t in by(self.objs, "wbs_task") + by(self.objs, "task_role_demand"):
            self.assertEqual(rel(t, "extracted_from"), [doc.object_id])

    def test_document_identity_survives_a_new_revision(self):
        _, _, other = run(workbook(Side={"A1": "excluded", "B2": 6}))
        self.assertEqual(by(other.objects, "project_document")[0].object_id, by(self.objs, "project_document")[0].object_id)
        self.assertNotEqual(by(other.objects, "workbook_revision")[0].object_id, by(self.objs, "workbook_revision")[0].object_id)
        self.assertFalse({o.object_id for o in by(other.objects, "wbs_task")} & set(t.object_id for t in self.tasks.values()))

    def test_unbound_document_is_kept_and_flagged(self):
        _, _, res = run(workbook(), binding=None)
        doc, = by(res.objects, "project_document")
        self.assertEqual(doc.fields["binding_state"], "unbound")
        self.assertFalse(rel(doc, "document_of"))
        self.assertIn("unbound_document", {x.fields["check"] for x in by(res.objects, "ingest_diagnostic")})

    def test_binding_survives_the_broker(self):
        pipe, raw, _ = run(workbook())
        env = pipe.receive(raw)
        self.assertEqual(env.payload["binding_subject_ref"], "PRJ-SYNTH-1")
        from app.application.ingest.services import _unflat_binding
        self.assertEqual(_unflat_binding(env.payload), BINDING)       # a raw event from another producer rebuilds it
        pipe.ring.register("probe", ())
        self.assertIn("project_reference", {e.object.kind for e in pipe.ring.poll("probe", 10000)})

    # WBS hierarchy
    def test_phases_stems_subsystems_and_leaves(self):
        out = {r["locator"]: r for r in wbs_outline(self.objs) if r["locator"]}
        self.assertEqual([p.fields["wbs_code"] for p in by(self.objs, "phase_scope")], ["P1", "P2", "P3"])
        self.assertEqual(out["Grid!B5"]["wbs_code"], "P1.01")
        self.assertEqual(out["Grid!B11"]["wbs_code"], "P2.01")
        self.assertEqual((out["Grid!B13"]["row_kind"], out["Grid!B13"]["wbs_code"]), ("subsystem", "P2.02"))
        self.assertEqual((out["Grid!B14"]["wbs_code"], out["Grid!B14"]["parent_wbs_code"], out["Grid!B14"]["wbs_level"]), ("P2.02.01", "P2.02", 3))
        self.assertEqual((out["Grid!B14"]["hierarchy_basis"], out["Grid!B14"]["parent_status"]), ("indent", "proposed"))
        self.assertEqual((out["Grid!B16"]["parent_wbs_code"], out["Grid!B16"]["hierarchy_basis"]), ("P2.03", "name_code"))
        self.assertEqual((out["Grid!B17"]["wbs_level"], out["Grid!B17"]["hierarchy_basis"]), (2, "plain_after_section"))
        self.assertEqual(rel(self.tasks["Grid!B14"], "proposed_child_of"), [self.tasks["Grid!B13"].object_id])

    def test_explicit_outline_parent_edge_agrees_with_asserted_status(self):
        # Change only explicit Excel outline levels on the synthetic fixture.
        from xml.etree import ElementTree as ET
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(workbook())) as src, zipfile.ZipFile(buf, "w") as dst:
            for entry in src.infolist():
                data = src.read(entry.filename)
                if entry.filename == "xl/worksheets/sheet1.xml":
                    sheet = ET.fromstring(data)
                    for row in sheet.find("m:sheetData", ns):
                        if int(row.attrib["r"]) in (13, 14):
                            row.attrib["outlineLevel"] = "1" if row.attrib["r"] == "13" else "2"
                    data = ET.tostring(sheet)
                dst.writestr(entry, data)
        res = run(buf.getvalue())[2]
        self.assertIsNone(res.rejection)
        tasks = {t.fields["locator"]: t for t in by(res.objects, "wbs_task")}
        parent, leaf = tasks["Grid!B13"], tasks["Grid!B14"]
        self.assertEqual(leaf.fields["hierarchy_basis"], "outline")
        self.assertEqual(leaf.fields["parent_status"], "asserted")
        self.assertEqual(leaf.fields["parent_wbs_code"], parent.fields["wbs_code"])
        self.assertEqual(rel(leaf, "child_of"), [parent.object_id])
        self.assertEqual(rel(leaf, "proposed_child_of"), [])
        # Existing indentation-only fixture is still a proposal, never promoted by this fix.
        proposed = self.tasks["Grid!B14"]
        self.assertEqual(proposed.fields["parent_status"], "proposed")
        self.assertEqual(rel(proposed, "child_of"), [])
        self.assertEqual(rel(proposed, "proposed_child_of"), [self.tasks["Grid!B13"].object_id])

    def test_subsystem_codes_resolve_only_from_the_index(self):
        self.assertEqual((self.tasks["Grid!B13"].fields["subsystem_state"], self.tasks["Grid!B13"].fields["subsystem_code"]), ("placeholder", "RTR"))
        self.assertFalse(rel(self.tasks["Grid!B13"], "classified_as"))
        self.assertEqual(self.tasks["Grid!B15"].fields["subsystem_state"], "resolved")
        self.assertTrue(rel(self.tasks["Grid!B15"], "classified_as"))

    def test_markers_are_evidence_not_tasks(self):
        self.assertEqual({r.fields["row_kind"] for r in by(self.objs, "wbs_row")}, {"copy_marker", "subtotal", "section_marker"})
        self.assertNotIn("Grid!B8", self.tasks)

    def test_formatting_disagreement_is_reported(self):
        self.assertIn(("formatting_disagrees", "Grid!B21"), self.checks)
        self.assertEqual(by(self.objs, "phase_scope")[2].fields["hierarchy_basis"], "text")

    def test_repeated_labels_stay_distinct(self):
        self.assertNotEqual(self.tasks["Grid!B5"].object_id, self.tasks["Grid!B11"].object_id)

    # task x role demand
    def test_blank_inputs_are_not_zero_demand(self):
        self.assertEqual((self.tasks["Grid!B11"].fields["roles_with_input"], self.tasks["Grid!B11"].fields["roles_blank"]), (0, 4))
        d = {x.fields["locator"]: x for x in by(self.objs, "task_role_demand")}
        self.assertEqual(d["Grid!C5:E5"].fields["labor_hours"], 16)
        self.assertEqual(d["Grid!C5:E5"].fields["elapsed_hours_estimate"], 8)       # man hours are per person
        self.assertEqual(d["Grid!F6:H6"].fields["input_state"], "explicit_zero")
        self.assertEqual(d["Grid!C7:E7"].fields["input_state"], "partial")
        self.assertNotIn("labor_hours", d["Grid!C7:E7"].fields)

    def test_stale_cache_is_reported_not_recalculated(self):
        d = [x for x in by(self.objs, "task_role_demand") if x.fields["locator"] == "Grid!C5:E5"][0]
        self.assertEqual(d.fields["total_cached_raw"], "0")
        self.assertTrue(d.fields["cache_disagrees"])

    def test_role_codes_and_labor_sources(self):
        roles = {r.fields["role_code"]: r for r in by(self.objs, "role_column")}
        self.assertEqual((roles["R-100-26"].fields["role_number"], roles["R-100-26"].fields["role_year"]), ("100", "26"))
        self.assertEqual(roles["OUT-1"].fields["role_code_format"], "nonconforming")
        self.assertEqual(roles["VEND"].fields["labor_source"], "vendor")
        self.assertTrue(roles["VEND"].fields["priced_elsewhere"])
        for d in by(self.objs, "task_role_demand"):
            self.assertEqual(d.fields["layer"], "commercial_estimate")
            self.assertIn(rel(d, "priced_under")[0], {r.object_id for r in roles.values()})

    def test_internal_wins_a_responsibility_conflict_and_raw_is_kept(self):
        t = self.tasks["Grid!B18"].fields
        self.assertEqual((t["labor_sources"], t["responsibility_raw"]), ("contract", "Our Team"))
        self.assertTrue(t["responsibility_conflict"])
        self.assertEqual((t["responsible_party"], t["resolution_rule"]), ("internal", "internal_precedence"))
        v = self.tasks["Grid!B19"].fields
        self.assertNotIn("responsibility_conflict", v)
        self.assertEqual(v["responsible_party"], "vendor")
        self.assertEqual(self.tasks["Grid!B22"].fields["responsibility_state"], "placeholder")

    # BOM lines
    def test_lines_part_numbers_and_subsystems(self):
        lines = {l.fields["locator"]: l for l in by(self.objs, "estimate_line")}
        self.assertEqual(len(lines), 4)
        self.assertEqual(by(self.objs, "line_table")[0].fields["template_rows_skipped"], 1)
        obs = by(self.objs, "part_number_observation")
        self.assertEqual(len(obs), 3)                                         # one claim per line, never collapsed
        self.assertEqual(len({o.fields["comparison_value"] for o in obs}), 2)
        self.assertTrue(all(o.fields["resolution_status"] == "unmapped" for o in obs))
        self.assertEqual(lines["Lines!A6"].fields["classification_state"], "blank")   # group header not carried down
        self.assertEqual(lines["Lines!A6"].fields["group_label"], "Group 1")
        self.assertEqual(rel(lines["Lines!A5"], "subsystem_candidate"), [self.tasks["Grid!B15"].object_id])
        self.assertEqual(lines["Lines!A4"].fields["price_raw"], "1234.50")
        self.assertNotIn("price", lines["Lines!A4"].fields)
        self.assertEqual(lines["Lines!A4"].fields["notes_url_count"], 1)
        self.assertEqual(lines["Lines!A4"].fields["uom_authority"], "external")

    def test_defects_are_diagnostics_never_repairs(self):
        for c in [("rate_reference", "Rates!F3"), ("reference_outside_used_range", "Lines!F6"), ("trip_code", "Trips!A3"),
                  ("trip_code", "Trips!A2"), ("unresolved_classification", "Lines!A7")]:
            self.assertIn(c, self.checks)

    # identity and determinism
    def test_reingest_is_idempotent(self):
        _, _, again = run(workbook())
        self.assertEqual([o.object_id for o in again.objects], [o.object_id for o in self.objs])
        self.assertEqual([o.digest() for o in again.objects], [o.digest() for o in self.objs])
        pipe, raw, _ = run(workbook())
        pipe.receive(raw)
        n = len(pipe.ring)
        pipe.receive(raw)
        self.assertEqual(len(pipe.ring), n)

    def test_everything_sits_in_one_revision(self):
        rev = by(self.objs, "workbook_revision")[0]
        for o in self.objs:
            if o.kind not in ("workbook_revision", "project_document", "project_reference"):
                self.assertEqual(o.relations[0].target_id, rev.object_id)

    def test_shared_formula_shift(self):
        self.assertEqual(shift_formula("SUM(E6,$H6,K$6)+'Sheet A1'!B2&\"C3\"", 2, 3), "SUM(H8,$H8,N$6)+'Sheet A1'!E4&\"C3\"")


@unittest.skipUnless(os.environ.get("DATAMESH_PRIVATE_WORKBOOK") and os.environ.get("DATAMESH_PRIVATE_PROFILE"),
                     "private workbook check: set DATAMESH_PRIVATE_WORKBOOK and DATAMESH_PRIVATE_PROFILE")
class PrivateWorkbook(unittest.TestCase):
    def test_private_template_parses(self):
        prof = WorkbookProfile.model_validate_json(Path(os.environ["DATAMESH_PRIVATE_PROFILE"]).read_text())
        b = IntakeBinding(subject_kind="opportunity", subject_namespace="private.check", subject_ref="LOCAL-1",
                          document_type=prof.document_type or "unknown")
        _, _, res = run(Path(os.environ["DATAMESH_PRIVATE_WORKBOOK"]).read_bytes(), profile=prof, mapping=prof.name, binding=b)
        self.assertIsNone(res.rejection)
        self.assertTrue(by(res.objects, "phase_scope"))
        self.assertTrue(all(r["wbs_code"] for r in wbs_outline(res.objects)))


if __name__ == "__main__":
    unittest.main()
