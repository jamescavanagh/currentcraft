"""Profile-driven XLSX adapter: a known workbook template -> typed source-occurrence DomainObjects. Stdlib only.

Design source: docs/pipelines/XLSX_WORKBOOK.md. Every object is a source occurrence keyed by revision + locator, not a
business entity. Blank inputs stay blank (never asserted zero), money stays raw text, formulas and cached values stay
apart, defects become diagnostics and nothing is repaired. Unknown layouts are quarantined.

0.9.1: a workbook with a profile document_type is a project document (e.g. the PEW) tied to the project or opportunity
named by RawItem.binding; WBS levels come from text rules confirmed by formatting; leaf parents are proposals.
"""

from __future__ import annotations

import math
import re
from typing import Mapping, Optional

from app.application.ingest.contracts import DomainObject, TypedRelation
from app.application.ingest.identity import document_id, subject_reference_id
from app.application.ingest.workbook import CatalogSpec, LineTableSpec, RoleMatrixSpec, RowRule, VocabularySpec, WorkbookProfile

from .adapters import _Base, _clip, _key, _Reject
from .ooxml import Sheet, Workbook, col_index, col_letters, cross_refs, read_workbook

MAX_DIAGNOSTICS = 200
_URL = re.compile(r"https?://\S+", re.I)


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().casefold()


def _num(raw: Optional[str]) -> Optional[float]:
    if raw is None or raw.strip() == "":
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _cols(first: str, n: int):
    base = col_index(first)
    return [col_letters(base + i) for i in range(n)]


class XlsxWorkbookAdapter(_Base):
    name, version = "xlsx_workbook", "3"

    def __init__(self, blobs, profiles: Mapping[str, WorkbookProfile] | None = None):
        super().__init__(blobs)
        self.profiles = dict(profiles or {})

    def _parse(self, raw, data, config, mappings):
        profile = self.profiles.get(raw.mapping)
        if profile is None:
            raise _Reject(f"unknown workbook profile {raw.mapping!r}")
        wb = read_workbook(data)
        for a in profile.anchors:
            sh = wb.sheets.get(a.sheet)
            if sh is None:
                raise _Reject(f"profile {profile.name}: sheet {a.sheet!r} missing")
            col, row = re.match(r"([A-Z]+)(\d+)", a.cell).groups()
            if _norm(sh.text(col, int(row))) != _norm(a.text):
                raise _Reject(f"profile {profile.name}: anchor {a.sheet}!{a.cell} does not match")
        return _Run(self, raw, config, profile, wb).objects()


class _Run:
    """One parse. Holds ids so children point at parents; objects are emitted in a stable order."""

    def __init__(self, adapter, raw, config, profile: WorkbookProfile, wb: Workbook):
        self.a, self.raw, self.config, self.p, self.wb = adapter, raw, config, profile, wb
        self.prov = adapter.prov(raw)
        self.out: list[DomainObject] = []
        self.diag: list[DomainObject] = []
        self.rev_id = self.oid("workbook_revision")
        # Source document identity: platform + source id, stable across revisions (hash + locator is per revision).
        self.doc_id = document_id(raw.platform, raw.source_id) if profile.document_type else None
        b = raw.binding
        self.subject_id = subject_reference_id(b.subject_kind, b.subject_namespace, b.subject_ref) if b else None
        self.vocab: dict[tuple[str, str], str] = {}
        self.catalog: dict[str, list[DomainObject]] = {}
        self.role_codes: dict[str, str] = {}             # block total column -> role code
        self.subsystems: dict[str, list[str]] = {}       # resolved sub-system code -> wbs_task ids

    # ids, objects ----------------------------------------------------------------------------------------------
    def oid(self, kind: str, *parts) -> str:
        return f"{self.raw.platform}:xlsx:{kind[:32]}:{_key(self.raw.source_id, self.raw.content.sha256, kind, *map(str, parts))}"

    def _base_rels(self):
        return (TypedRelation(type="in_revision", target_id=self.rev_id, evidence="workbook"),)

    def emit(self, kind, oid, title="", text="", fields=None, rels=()):
        f = {"profile": f"{self.p.name}@{self.p.version}", "assertion": "source_occurrence"}
        f.update({k: v for k, v in (fields or {}).items() if v is not None})
        obj = DomainObject(object_id=oid, kind=kind, title=str(title or "")[:500], text=_clip(text or "", self.config.max_text),
                           fields=f, relations=self._base_rels() + tuple(rels), provenance=self.prov)
        self.out.append(obj)
        return obj

    def diagnostic(self, check, severity, locator, detail, about=None):
        if len(self.diag) >= MAX_DIAGNOSTICS:
            return
        rels = (TypedRelation(type="about", target_id=about, evidence=locator[:200]),) if about else ()
        self.diag.append(DomainObject(
            object_id=self.oid("diagnostic", check, locator, detail), kind="ingest_diagnostic", title=f"{check}: {locator}"[:500],
            text=detail[:2000], fields={"profile": f"{self.p.name}@{self.p.version}", "check": check, "severity": severity,
                                        "locator": locator[:200]},
            relations=self._base_rels() + rels, provenance=self.prov))

    def sheet(self, name) -> Sheet:
        sh = self.wb.sheets.get(name)
        if sh is None:
            raise _Reject(f"profile {self.p.name}: sheet {name!r} missing")
        return sh

    def doc_rel(self, evidence):
        return (TypedRelation(type="extracted_from", target_id=self.doc_id, evidence=evidence[:200]),) if self.doc_id else ()

    # run ------------------------------------------------------------------------------------------------------
    def objects(self):
        head = []
        if self.doc_id:
            head = self.document()
        for v in self.p.vocabularies:
            self.vocabulary(v)
        for c in self.p.catalogs:
            self.catalog_table(c)
        if self.p.role_matrix is not None:
            self.role_matrix(self.p.role_matrix)
        for t in self.p.line_tables:
            self.line_table(t)
        for chk in self.p.reference_checks:
            self.reference_check(chk)
        for chk in self.p.crosswalk_checks:
            self.crosswalk(chk)
        self.formula_scan()
        rev_rels = (TypedRelation(type="revision_of", target_id=self.doc_id, evidence="source_id"),) if self.doc_id else ()
        rev = DomainObject(
            object_id=self.rev_id, kind="workbook_revision", title=(self.wb.title or self.raw.source_id)[:500],
            fields={"profile": f"{self.p.name}@{self.p.version}", "assertion": "source_occurrence",
                    "content_sha256": self.raw.content.sha256,
                    "revision_label": self.raw.binding.revision_label if self.raw.binding else None,
                    "sheets": len(self.wb.sheets), "hidden_sheets": sum(s.state != "visible" for s in self.wb.sheets.values()),
                    "excluded_sheets": ",".join(self.p.excluded_sheets)[:500], "has_macros": self.wb.has_macros,
                    "external_links": self.wb.external_links, "objects": len(self.out), "diagnostics": len(self.diag),
                    "diagnostics_capped": len(self.diag) >= MAX_DIAGNOSTICS},
            relations=rev_rels, provenance=self.prov)
        rev = rev.model_copy(update={"fields": {k: v for k, v in rev.fields.items() if v is not None}})
        return head + [rev] + self.out + self.diag

    # document tied to the project -----------------------------------------------------------------------------
    def document(self):
        b = self.raw.binding
        objs = []
        rels = []
        if b is not None:
            objs.append(DomainObject(
                object_id=self.subject_id, kind=f"{b.subject_kind}_reference", title=b.subject_ref,
                fields={"assertion": "intake_binding", "namespace": b.subject_namespace, "reference": b.subject_ref,
                        "resolution_status": "unresolved"},
                provenance=self.prov))
            rels.append(TypedRelation(type="document_of", target_id=self.subject_id, evidence="RawItem.binding"))
        else:
            self.diagnostic("unbound_document", "review", self.raw.source_id,
                            f"{self.p.document_type} arrived without a project or opportunity binding; records stay "
                            "retrievable, project-scoped claims are withheld")
        if b is not None and _norm(b.document_type) != _norm(self.p.document_type):
            self.diagnostic("document_type_mismatch", "review", self.raw.source_id,
                            f"binding says {b.document_type!r}, profile reads {self.p.document_type!r}")
        objs.append(DomainObject(
            object_id=self.doc_id, kind="project_document", title=(self.wb.title or self.raw.source_id)[:500],
            fields={"assertion": "source_document", "document_type": self.p.document_type,
                    "binding_state": "bound" if b else "unbound", "subject_kind": b.subject_kind if b else None,
                    "current_revision_sha256": self.raw.content.sha256, "profile": f"{self.p.name}@{self.p.version}",
                    "revision_label": b.revision_label if b else None},
            relations=tuple(rels) + (TypedRelation(type="current_revision", target_id=self.rev_id, evidence="content_sha256"),),
            provenance=self.prov))
        objs = [o.model_copy(update={"fields": {k: v for k, v in o.fields.items() if v is not None}}) for o in objs]
        return objs

    # vocabularies ---------------------------------------------------------------------------------------------
    def vocabulary(self, v: VocabularySpec):
        sh = self.sheet(v.sheet)
        set_id = self.oid("reference_set", v.set_name)
        self.emit("reference_set", set_id, title=v.set_name, fields={"set_name": v.set_name, "locator": f"{v.sheet}!{v.code_col}{v.first_row}"})
        for r in range(v.first_row, (v.last_row or sh.max_row) + 1):
            code = sh.text(v.code_col, r)
            if not code:
                continue
            label = sh.text(v.label_col, r) if v.label_col else code
            oid = self.oid("reference_value", v.set_name, r)
            key = (v.set_name, _norm(code))
            if key in self.vocab:
                self.diagnostic("duplicate_code", "review", f"{v.sheet}!{v.code_col}{r}", f"code {code!r} repeats in {v.set_name}", oid)
            else:
                self.vocab[key] = oid
            self.emit("reference_value", oid, title=code, text=label or "",
                      fields={"set_name": v.set_name, "code": code, "label": label, "locator": f"{v.sheet}!{v.code_col}{r}"},
                      rels=(TypedRelation(type="member_of", target_id=set_id, evidence=f"{v.sheet}!{v.code_col}{r}"),))

    # catalogs -------------------------------------------------------------------------------------------------
    def catalog_table(self, c: CatalogSpec):
        sh = self.sheet(c.sheet)
        section = None
        skip = {_norm(s) for s in c.skip_codes}
        for r in range(c.first_row, (c.last_row or sh.max_row) + 1):
            code = sh.text(c.code_col, r)
            label = sh.text(c.label_col, r) if c.label_col else None
            if c.section_pattern and label and re.search(c.section_pattern, label):
                section = code
                continue
            if not code or _norm(code) in skip:
                continue
            f = {"code": code, "label": label, "section": section, "locator": f"{c.sheet}!{c.code_col}{r}"}
            for name, col in c.fields.items():
                cell = sh.get(col, r)
                if cell is not None:
                    f[f"{name}_raw"] = cell.raw
                    if cell.formula:
                        f[f"{name}_formula"] = cell.formula[:400]
            if c.capture_hyperlinks:
                f["link_target"] = sh.hyperlinks.get(f"{c.code_col}{r}")
            obj = self.emit(c.kind, self.oid(c.kind, c.sheet, r), title=code, text=label or "", fields=f)
            self.catalog.setdefault(c.kind, []).append(obj)

    # role matrix: WBS levels, tasks, task x role demand ---------------------------------------------------------
    def _rule(self, rules: tuple[RowRule, ...], sh: Sheet, r: int, default_col: str):
        for rule in rules:
            txt = sh.text(rule.col or default_col, r)
            if txt:
                m = re.search(rule.pattern, txt)
                if m:
                    return rule, m
        return None, None

    def _role_class(self, m: RoleMatrixSpec, code: str):
        for rc in m.role_classes:
            if re.search(rc.pattern, code):
                return rc
        return None

    def _subsystem_code(self, h, name: str):
        """(code, state, basis) from a row name. Placeholders give an example code that never resolves."""
        if h.placeholder_pattern:
            pm = re.search(h.placeholder_pattern, name)
            if pm:
                return pm.group(1), "placeholder", "placeholder_pattern"
        if h.subsystem_set:
            token = re.split(r"[\s\-–:/,(]+", name.strip(), maxsplit=1)[0]
            if token and (h.subsystem_set, _norm(token)) in self.vocab:
                return token, "resolved", "leading_code"
        return None, "unresolved", None

    def role_matrix(self, m: RoleMatrixSpec):
        sh = self.sheet(m.sheet)
        h = m.hierarchy
        blocks = []
        catalog = {_norm(o.fields["code"]): o.object_id for objs in self.catalog.values() for o in objs}
        for i in range(m.block_count):
            cols = _cols(col_letters(col_index(m.first_block_col) + i * m.block_width), m.block_width)
            header = sh.text(cols[0], m.header_row) or ""
            mm = re.search(m.role_code_pattern, header)
            code = mm.group(1) if mm else f"block{i + 1}"
            label = " ".join(header.split("\n")[1:]).strip() or None
            rc = self._role_class(m, code)
            rid = self.oid("role_column", m.sheet, cols[0])
            f = {"role_code": code, "label": label, "block": i + 1, "locator": f"{m.sheet}!{cols[0]}{m.header_row}",
                 "layer": "commercial_estimate", "labor_source": rc.labor_source if rc else None,
                 "priced_elsewhere": rc.priced_elsewhere if rc else None}
            if m.role_code_format:
                fm = re.match(m.role_code_format, code)
                if fm:
                    gd = fm.groupdict()
                    f.update({"role_series": gd.get("series"), "role_number": gd.get("number"), "role_year": gd.get("year")})
                else:
                    f["role_code_format"] = "nonconforming"
            if m.rate_row:
                rcell = sh.get(cols[0], m.rate_row)
                if rcell is not None:
                    f["rate_raw"], f["rate_formula"] = rcell.raw, rcell.formula
            rels = (TypedRelation(type="catalog_entry", target_id=catalog[_norm(code)], evidence=f["locator"]),) if _norm(code) in catalog else ()
            if not rels and rc is not None and not rc.priced_elsewhere:
                self.diagnostic("role_without_rate", "review", f["locator"], f"role block {code!r} has no rate-card entry", rid)
            self.emit("role_column", rid, title=code, text=header, fields=f, rels=rels)
            blocks.append((code, cols, rid, rc))
            self.role_codes[cols[m.total_offset]] = code

        holders = {_norm(x) for x in m.placeholder_values}
        resp_classes = {_norm(k): v for k, v in m.responsibility_classes.items()}
        outline_rows = sh.outline if (h and h.use_outline_levels) else {}
        phase = phase_id = phase_n = None
        in_section = False
        stem_n = 0
        leaf_counts: dict[str, int] = {}
        parent_sub = None        # (wbs_code, task id, code) of the last sub-system row in the open section
        for r in range(m.first_row, m.last_row + 1):
            label = sh.text(m.label_col, r)
            if not label:
                continue
            cell = sh.get(m.label_col, r)
            style = cell.style
            rule, mm = self._rule(m.rules, sh, r, m.label_col)
            kind = rule.row_kind if rule else m.default_kind
            loc = f"{m.sheet}!{m.label_col}{r}"
            if h and h.section_start_pattern and re.search(h.section_start_pattern, label):
                kind = "section_marker"
            if h and kind in h.bold_kinds and not style.bold:
                self.diagnostic("formatting_disagrees", "review", loc, f"text reads as {kind} but the cell is not bold; text rule kept")
            if kind == "phase":
                phase = mm.group(rule.code_group) if rule and rule.code_group else label
                phase_n = phase
                phase_id = self.oid("phase_scope", m.sheet, r)
                stem_n, in_section, parent_sub = 0, False, None
                self.emit("phase_scope", phase_id, title=label,
                          fields={"phase_code": phase, "locator": loc, "row": r, "wbs_code": f"P{phase}", "wbs_level": 1,
                                  "hierarchy_basis": "text+bold" if style.bold else "text"},
                          rels=self.doc_rel(loc))
                continue
            if kind == "section_marker":
                in_section, parent_sub = True, None
                if h and not (style.bold and style.italic):
                    self.diagnostic("formatting_disagrees", "review", loc, "section marker is not bold italic; text rule kept")
            if kind not in m.task_kinds:
                if phase_id is None:
                    continue
                self.emit("wbs_row", self.oid("wbs_row", m.sheet, r), title=label,
                          fields={"row_kind": kind, "phase_code": phase, "locator": loc, "row": r,
                                  "row_total_formula": self._f(sh, m.row_total_col, r), "row_total_cached_raw": self._v(sh, m.row_total_col, r)},
                          rels=(TypedRelation(type="in_phase", target_id=phase_id, evidence=loc),))
                continue
            if phase_id is None:
                self.diagnostic("task_outside_phase", "review", loc, f"task row {label!r} precedes any phase row")

            # ---- WBS level: outline level first, else text rules confirmed by formatting
            level, basis, parent_status, parent_rel = 2, "position", "asserted", None
            sub_code = sub_state = sub_basis = None
            leaf_indent = (h.leaf_min_indent or h.subsystem_min_indent + 1) if h else None
            row_kind = kind
            if r in outline_rows:
                level, basis = min(3, 1 + outline_rows[r]), "outline"
                if level == 3 and parent_sub is not None:
                    parent_rel, row_kind = parent_sub, "leaf"     # explicit Excel grouping: parent asserted, not proposed
                elif level == 2:
                    parent_sub = (None, None, None)
                if level == 2 and phase:
                    parent_sub = (f"P{phase}.{stem_n + 1:02d}", self.oid("wbs_task", m.sheet, r), None)
                if level == 3 and parent_rel is None:
                    level = 2
            elif h and in_section:
                named = re.search(h.leaf_code_pattern, label) if h.leaf_code_pattern else None
                named_parent = None
                if named and parent_sub is not None:
                    named_parent = next((p for p in self.subsystems.get(_norm(named.group(1)), []) if p[0] == phase), None)
                if parent_sub is not None and style.indent >= leaf_indent:
                    level, basis, parent_status, row_kind = 3, "indent", "proposed", "leaf"
                    parent_rel = parent_sub
                elif named_parent is not None:
                    level, basis, parent_status, row_kind = 3, "name_code", "proposed", "leaf"
                    parent_rel = named_parent[1:]
                elif style.indent >= h.subsystem_min_indent:
                    level, basis, row_kind = 2, "indent", "subsystem"
                    sub_code, sub_state, sub_basis = self._subsystem_code(h, label)
                else:
                    in_section, parent_sub = False, None       # plain row after the block: back to stem
                    basis = "plain_after_section"
            if level == 2 or parent_rel is None:
                stem_n += 1
                wbs = f"P{phase}.{stem_n:02d}" if phase else None
                parent_wbs = f"P{phase}" if phase else None
            else:
                leaf_counts[parent_rel[0]] = leaf_counts.get(parent_rel[0], 0) + 1
                wbs = f"{parent_rel[0]}.{leaf_counts[parent_rel[0]]:02d}"
                parent_wbs = parent_rel[0]
            tid = self.oid("wbs_task", m.sheet, r)
            if row_kind == "subsystem":
                parent_sub = (wbs, tid, sub_code)
                if sub_state == "resolved":
                    self.subsystems.setdefault(_norm(sub_code), []).append((phase, wbs, tid))

            # ---- task x role inputs
            resp = self._v(sh, m.responsibility_col, r)
            resp_state = "blank" if not resp or not resp.strip() else ("placeholder" if _norm(resp) in holders else "value")
            resp_class = resp_classes.get(_norm(resp)) if resp_state == "value" else None
            if resp_state == "value" and resp_class is None and resp_classes:
                self.diagnostic("unknown_responsibility", "review", f"{m.sheet}!{m.responsibility_col}{r}", f"{resp!r} is not a known responsibility value")
            demands, blank, sources = [], 0, set()
            for code, cols, rid, rc in blocks:
                cnt, hrs, tot = (sh.get(cols[m.count_offset], r), sh.get(cols[m.hours_offset], r), sh.get(cols[m.total_offset], r))
                c_raw = None if cnt is None or cnt.is_blank else cnt.raw
                h_raw = None if hrs is None or hrs.is_blank else hrs.raw
                if c_raw is None and h_raw is None:
                    blank += 1
                    continue
                cn, hn = _num(c_raw), _num(h_raw)
                state = ("partial" if (c_raw is None) != (h_raw is None) else
                         "explicit_zero" if cn == 0 or hn == 0 else "explicit")
                if rc is not None and state != "explicit_zero":
                    sources.add(rc.labor_source)
                demands.append((code, cols, rid, rc, c_raw, h_raw, cn, hn, tot, state))
            party = self._party(m, sources, resp_class, loc)
            known = [cn * hn for *_, cn, hn, _t, st in demands if cn is not None and hn is not None]
            rels = []
            if phase_id:
                rels.append(TypedRelation(type="child_of" if level == 2 else "in_phase", target_id=phase_id, evidence=loc))
            if parent_rel is not None:
                rels.append(TypedRelation(type="child_of" if parent_status == "asserted" else "proposed_child_of",
                                          target_id=parent_rel[1], evidence=f"{loc} ({basis})"))
            if sub_state == "resolved":
                rels.append(TypedRelation(type="classified_as", target_id=self.vocab[(h.subsystem_set, _norm(sub_code))], evidence=loc))
            notes = self._v(sh, m.notes_col, r)
            self.emit("wbs_task", tid, title=label, text=notes or "",
                      fields={"row_kind": row_kind, "phase_code": phase, "locator": loc, "row": r,
                              "wbs_code": wbs, "parent_wbs_code": parent_wbs, "wbs_level": level, "wbs_code_basis": "derived_row_order",
                              "hierarchy_basis": basis, "parent_status": parent_status, "indent": style.indent or None,
                              "subsystem_code": sub_code, "subsystem_state": sub_state, "subsystem_basis": sub_basis,
                              "roles_with_input": len(demands), "roles_blank": blank,
                              "labor_hours_known": sum(known) if known else None,
                              "row_total_formula": self._f(sh, m.row_total_col, r), "row_total_cached_raw": self._v(sh, m.row_total_col, r),
                              "responsibility_raw": resp, "responsibility_state": resp_state, "responsibility_class": ",".join(resp_class) if resp_class else None,
                              **party, "scope_notes": notes or None},
                      rels=tuple(rels) + self.doc_rel(loc))
            for code, cols, rid, rc, c_raw, h_raw, cn, hn, tot, state in demands:
                dloc = f"{m.sheet}!{cols[0]}{r}:{cols[-1]}{r}"
                f = {"role_code": code, "phase_code": phase, "wbs_code": wbs, "locator": dloc, "input_state": state,
                     "layer": "commercial_estimate", "labor_source": rc.labor_source if rc else None,
                     "priced_elsewhere": rc.priced_elsewhere if rc else None,
                     "count_raw": c_raw, "hours_each_raw": h_raw, "count": cn, "hours_each": hn,
                     "labor_hours": cn * hn if cn is not None and hn is not None else None,
                     "elapsed_hours_estimate": hn if cn is not None and hn is not None and cn > 0 else None,
                     "elapsed_basis": "hours_each_parallel_crew" if cn is not None and hn is not None and cn > 0 else None,
                     "total_formula": tot.formula if tot else None, "total_cached_raw": tot.raw if tot else None}
                if f["labor_hours"] is not None and tot is not None and _num(tot.raw) is not None and abs(_num(tot.raw) - f["labor_hours"]) > 1e-9:
                    f["cache_disagrees"] = True
                    self.diagnostic("stale_cached_total", "review", dloc,
                                    f"cached total {tot.raw} differs from count x hours {f['labor_hours']}; workbook not recalculated")
                self.emit("task_role_demand", self.oid("task_role_demand", m.sheet, r, cols[0]), title=f"{label} / {code}", fields=f,
                          rels=(TypedRelation(type="budget_for", target_id=tid, evidence=dloc),
                                TypedRelation(type="priced_under", target_id=rid, evidence=f"{m.sheet}!{cols[0]}{m.header_row}")) + self.doc_rel(dloc))

    def _party(self, m: RoleMatrixSpec, sources: set, resp: Optional[tuple], loc: str) -> dict:
        """Who carries the work: hours by labor source vs the responsibility column. Raw values are always kept."""
        out = {"labor_sources": ",".join(sorted(sources)) or None}
        named = set(resp or ())
        if not named or not sources:
            pool = named or sources
            out["responsible_party"] = (next(iter(pool)) if len(pool) == 1 else "mixed") if pool else None
            return out
        if sources <= named:
            out["responsible_party"] = next(iter(sources)) if len(sources) == 1 else "mixed"
            return out
        out["responsibility_conflict"] = True
        if m.responsibility_precedence == "internal" and "internal" in sources | named:
            out["responsible_party"], out["resolution_rule"] = "internal", "internal_precedence"
        else:
            out["responsible_party"], out["resolution_rule"] = "unresolved", "none"
        self.diagnostic("responsibility_conflict", "review", loc,
                        f"hours from {out['labor_sources']} but responsibility names {','.join(sorted(named))}; resolved "
                        f"{out['responsible_party']} by {out['resolution_rule']}. Raw values kept.")
        return out

    @staticmethod
    def _v(sh, col, r):
        c = sh.get(col, r) if col else None
        return c.raw if c is not None else None

    @staticmethod
    def _f(sh, col, r):
        c = sh.get(col, r) if col else None
        return c.formula[:400] if c is not None and c.formula else None

    # line tables ----------------------------------------------------------------------------------------------
    def line_table(self, t: LineTableSpec):
        sh = self.sheet(t.sheet)
        tid = self.oid("line_table", t.name)
        default_col = t.columns.get(t.classification_field or "description")
        section, group_id, group_label, lines, template_rows, observations = t.default_section, None, None, 0, 0, 0
        pending = []
        for r in range(t.first_row, (t.last_row or sh.max_row) + 1):
            rule, mm = self._rule(t.rules, sh, r, default_col)
            loc = f"{t.sheet}!A{r}"
            if rule is not None:
                if rule.sets_section:
                    section, group_id, group_label = rule.sets_section, None, None
                    continue
                if rule.row_kind == "group":
                    group_id = self.oid("line_group", t.name, r)
                    group_label = sh.text(rule.col or default_col, r)
                    pending.append(("line_group", group_id, group_label, {"section": section, "locator": loc, "row": r},
                                    (TypedRelation(type="group_of", target_id=tid, evidence=loc),)))
                    continue
                f = {"row_kind": rule.row_kind, "section": section, "locator": loc, "row": r}
                for name, col in t.columns.items():
                    c = sh.get(col, r)
                    if c is not None and c.formula:
                        f[f"{name}_formula"] = c.formula[:400]
                    if c is not None and c.raw not in (None, ""):
                        f[f"{name}_raw"] = c.raw
                pending.append(("line_table_row", self.oid("line_table_row", t.name, r), mm.group(0), f,
                                (TypedRelation(type="row_of", target_id=tid, evidence=loc),)))
                continue
            vals = {name: sh.get(col, r) for name, col in t.columns.items()}
            if not any(vals.get(k) is not None and not vals[k].is_blank and (vals[k].raw or "").strip() for k in t.content_fields):
                if any(c is not None and not c.is_blank for c in vals.values()):
                    template_rows += 1
                continue
            lid = self.oid("estimate_line", t.name, r)
            # the line's own sub-system cell only; a group header above is context, never carried down
            f = {"line_kind": section, "locator": loc, "row": r, "group_label": group_label}
            for name, c in vals.items():
                if c is None:
                    continue
                if c.raw not in (None, ""):
                    f[f"{name}_raw"] = c.raw
                if c.formula:
                    f[f"{name}_formula"] = c.formula[:400]
            f["quantity"] = _num(vals["quantity"].raw) if vals.get("quantity") is not None else None
            f["uom_authority"] = "external"          # unit of measure is owned by the ERP item, not this sheet
            notes = vals.get("notes")
            note_txt = (notes.raw or "") if notes is not None else ""
            if note_txt:
                f["notes_url_count"] = len(_URL.findall(note_txt))
            rels = [TypedRelation(type="line_of", target_id=tid, evidence=loc)]
            if group_id:
                rels.append(TypedRelation(type="in_group", target_id=group_id, evidence=loc))
            if t.classification_field:
                code = vals.get(t.classification_field)
                code_txt = (code.raw or "").strip() if code is not None and code.raw else ""
                hit = self.vocab.get((t.classification_set, _norm(code_txt))) if code_txt else None
                f["classification_state"] = "resolved" if hit else ("unresolved" if code_txt else "blank")
                if hit:
                    rels.append(TypedRelation(type="classified_as", target_id=hit, evidence=f"{t.sheet}!{t.columns[t.classification_field]}{r}"))
                    for ph, wbs, sub_tid in self.subsystems.get(_norm(code_txt), []):
                        rels.append(TypedRelation(type="subsystem_candidate", target_id=sub_tid, evidence=f"code {code_txt} = {wbs}"))
                elif code_txt:
                    self.diagnostic("unresolved_classification", "review", f"{t.sheet}!{t.columns[t.classification_field]}{r}",
                                    f"{code_txt!r} is not in {t.classification_set}", lid)
            pn = vals.get("part_number")
            pn_txt = (pn.raw or "").strip() if pn is not None and pn.raw else ""
            if pn_txt:
                mfr = vals.get("manufacturer")
                mfr_txt = (mfr.raw or "").strip() if mfr is not None and mfr.raw else ""
                obs = self.oid("part_number_observation", t.name, r)
                pending.append(("part_number_observation", obs, pn_txt,
                                {"raw_value": pn_txt, "issuer_claim": "manufacturer", "manufacturer_raw": mfr_txt or None,
                                 "comparison_value": f"{_norm(mfr_txt)}|{_norm(pn_txt)}", "resolution_status": "unmapped",
                                 "assertion": "claim", "locator": f"{t.sheet}!{t.columns['part_number']}{r}"},
                                (TypedRelation(type="observed_on", target_id=lid, evidence=f"{t.sheet}!{t.columns['part_number']}{r}"),)))
                observations += 1
            desc = vals.get("description")
            pending.append(("estimate_line", lid, (desc.raw if desc is not None else None) or pn_txt, f, tuple(rels) + self.doc_rel(loc)))
            lines += 1
        self.emit("line_table", tid, title=t.name, fields={"table": t.name, "locator": f"{t.sheet}!A{t.first_row}", "lines": lines,
                                                          "template_rows_skipped": template_rows, "part_number_observations": observations},
                  rels=self.doc_rel(f"{t.sheet}!A{t.first_row}"))
        for kind, oid, title, f, rels in pending:
            self.emit(kind, oid, title=title or "", text=(f.get("notes_raw") or "") if kind == "estimate_line" else "", fields=f, rels=rels)

    # checks ---------------------------------------------------------------------------------------------------
    def reference_check(self, chk):
        sh = self.sheet(chk.sheet)
        m = self.p.role_matrix
        by_code = {_norm(v): k for k, v in self.role_codes.items()}
        for r in range(chk.first_row, chk.last_row + 1):
            code = sh.text(chk.code_col, r)
            if not code:
                continue
            targets = {}
            for col in chk.ref_cols:
                c = sh.get(col, r)
                refs = cross_refs(c.formula) if c is not None and c.formula else []
                if refs:
                    targets[col] = refs[0]
            if len(targets) < 2:
                continue
            cols = [t[1] for t in targets.values()]
            on_matrix = m is not None and next(iter(targets.values()))[0] == m.sheet
            # expected column: the row code's role block when the matrix is the target, else the most common (first wins ties)
            major = by_code.get(_norm(code)) if on_matrix and _norm(code) in by_code else max(cols, key=lambda c: (cols.count(c), -cols.index(c)))
            for col, (tsheet, tcol, trow) in targets.items():
                if tcol != major:
                    self.diagnostic(chk.name, "defect", f"{chk.sheet}!{col}{r}",
                                    f"references {tsheet}!{tcol}{trow}; row {r} ({code}) should read column {major}. Not repaired; "
                                    "hours come from the task grid, not this sheet.")
            if on_matrix and _norm(code) not in by_code:
                block_code = self.role_codes.get(major)
                if block_code:
                    self.diagnostic(chk.name + "_code", "defect", f"{chk.sheet}!{chk.code_col}{r}",
                                    f"row code {code!r} reads role block {block_code!r} (column {major})")

    def crosswalk(self, chk):
        targets = self.catalog.get(chk.target_kind, [])
        for o in self.catalog.get(chk.source_kind, []):
            code = _norm(o.fields.get("code"))
            match = [t for t in targets if _norm(t.fields.get("code")) == code or _norm(t.fields.get("code")).startswith(code + "-")]
            if not match:
                self.diagnostic(chk.name, "review", o.fields["locator"], f"code {o.fields.get('code')!r} has no {chk.target_kind} entry", o.object_id)
            elif _norm(match[0].fields.get("label")) != _norm(o.fields.get("label")):
                self.diagnostic(chk.name, "review", o.fields["locator"],
                                f"{o.fields.get('code')} is labelled {o.fields.get('label')!r} here and "
                                f"{match[0].fields.get('label')!r} in {chk.target_kind} ({match[0].fields['locator']}). "
                                f"The {chk.target_kind} sheet is the reference; raw values kept, not resolved.", o.object_id)

    def formula_scan(self):
        excluded = set(self.p.excluded_sheets)
        into_excluded: dict[tuple[str, str], list[str]] = {}
        for sh in self.wb.sheets.values():
            if sh.name in excluded:
                continue
            for c in sh.cells.values():
                if not c.formula:
                    continue
                for tsheet, tcol, trow in cross_refs(c.formula):
                    target = self.wb.sheets.get(tsheet)
                    loc = f"{sh.name}!{c.ref}"
                    if target is None:
                        self.diagnostic("missing_sheet_reference", "defect", loc, f"references missing sheet {tsheet!r}")
                    elif trow > target.max_row:
                        self.diagnostic("reference_outside_used_range", "defect", loc,
                                        f"references {tsheet}!{tcol}{trow}; {tsheet} ends at row {target.max_row}")
                    elif tsheet in excluded:
                        into_excluded.setdefault((sh.name, tsheet), []).append(c.ref)
        for (src, dst), refs in sorted(into_excluded.items()):
            self.diagnostic("depends_on_excluded_sheet", "info", f"{src}!{refs[0]}",
                            f"{len(refs)} formula reference(s) from {src} into excluded sheet {dst}; totals using them are partial.")
