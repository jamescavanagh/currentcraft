"""Minimal, read-only SpreadsheetML reader. Stdlib only. Keeps raw cell text, formulas and cached values apart.

Never executes macros, never resolves external links, never fetches hyperlinks. Shared formulas are expanded by
reference shifting and flagged as expanded; array formulas keep their anchor text.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CORE = {"dc": "http://purl.org/dc/elements/1.1/", "dcterms": "http://purl.org/dc/terms/"}
MAX_UNZIPPED = 80 * 1024 * 1024
MAX_PARTS = 2000

_REF = re.compile(r"^([A-Z]{1,3})([0-9]{1,7})$")
_TOKEN = re.compile(r"(\"(?:[^\"]|\"\")*\")|('(?:[^']|'')*')|(?<![A-Za-z0-9_.$])(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})(?![0-9A-Za-z_(])")
_XREF = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!\$?([A-Z]{1,3})\$?([0-9]{1,7})")


def col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref: str) -> tuple[str, int]:
    m = _REF.match(ref)
    if not m:
        raise ValueError(f"bad cell reference {ref!r}")
    return m.group(1), int(m.group(2))


def shift_formula(formula: str, d_row: int, d_col: int) -> str:
    """Shift relative A1 references, leaving $-anchored parts, string literals and quoted sheet names alone."""
    def sub(m):
        if m.group(1) or m.group(2):
            return m.group(0)
        c_abs, col, r_abs, row = m.group(3), m.group(4), m.group(5), int(m.group(6))
        new_col = col if c_abs else col_letters(max(1, col_index(col) + d_col))
        new_row = row if r_abs else max(1, row + d_row)
        return f"{c_abs}{new_col}{r_abs}{new_row}"
    return _TOKEN.sub(sub, formula)


def cross_refs(formula: str) -> list[tuple[str, str, int]]:
    """(sheet, column, row) for every sheet-qualified reference."""
    out = []
    for m in _XREF.finditer(formula):
        sheet = (m.group(1) or m.group(2) or "").replace("''", "'")
        out.append((sheet, m.group(3), int(m.group(4))))
    return out


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    indent: int = 0


PLAIN = Style()


@dataclass(frozen=True)
class Cell:
    ref: str
    row: int
    col: str
    type: Optional[str]          # s, str, inlineStr, b, e, n or None
    raw: Optional[str]           # cached value / literal as text; None when the cell holds no value
    formula: Optional[str] = None
    formula_kind: Optional[str] = None   # normal, shared_anchor, shared_expanded, array
    style: Style = PLAIN

    @property
    def is_blank(self) -> bool:
        return self.formula is None and (self.raw is None or self.raw == "")


@dataclass
class Sheet:
    name: str
    state: str
    cells: dict = field(default_factory=dict)     # (row, col) -> Cell
    hyperlinks: dict = field(default_factory=dict)  # ref -> target
    outline: dict = field(default_factory=dict)     # row -> Excel outline (grouping) level, when set
    max_row: int = 0

    def get(self, col: str, row: int) -> Optional[Cell]:
        return self.cells.get((row, col))

    def text(self, col: str, row: int) -> Optional[str]:
        c = self.get(col, row)
        if c is None or c.raw is None:
            return None
        t = c.raw.strip()
        return t or None


@dataclass
class Workbook:
    sheets: dict
    title: Optional[str]
    has_macros: bool
    external_links: int


def _strings(z) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out = []
    for si in root.iter(M + "si"):
        out.append("".join(t.text or "" for t in si.iter(M + "t") if not _in_phonetic(si, t)))
    return out


def _in_phonetic(si, t) -> bool:
    for rph in si.iter(M + "rPh"):
        if any(x is t for x in rph.iter(M + "t")):
            return True
    return False


def _styles(z, names) -> list[Style]:
    """cellXfs index -> Style (font bold/italic, alignment indent). Empty when the package has no styles part."""
    if "xl/styles.xml" not in names:
        return []
    root = ET.fromstring(z.read("xl/styles.xml"))
    fonts = []
    fonts_el = root.find(M + "fonts")
    for f in (fonts_el if fonts_el is not None else []):
        b, i = f.find(M + "b"), f.find(M + "i")
        on = lambda e: e is not None and e.get("val", "1") not in ("0", "false")
        fonts.append((on(b), on(i)))
    out = []
    xfs = root.find(M + "cellXfs")
    for xf in (xfs if xfs is not None else []):
        fid = int(xf.get("fontId", "0"))
        b, i = fonts[fid] if fid < len(fonts) else (False, False)
        al = xf.find(M + "alignment")
        indent = int(al.get("indent", "0")) if al is not None else 0
        out.append(Style(b, i, indent))
    return out


def read_workbook(data: bytes) -> Workbook:
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > MAX_PARTS or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise ValueError("workbook expands beyond the size limit")
    names = set(z.namelist())
    if "xl/workbook.xml" not in names:
        raise ValueError("not a SpreadsheetML workbook: xl/workbook.xml missing")
    strings = _strings(z)
    styles = _styles(z, names)
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PR + "Relationship"):
            rels[r.get("Id")] = r.get("Target")
    wb_root = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = {}
    for s in wb_root.iter(M + "sheet"):
        target = rels.get(s.get(R + "id"))
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        if path not in names:
            continue
        sheets[s.get("name")] = _read_sheet(z, path, s.get("name"), s.get("state") or "visible", strings, names, styles)
    title = None
    if "docProps/core.xml" in names:
        t = ET.fromstring(z.read("docProps/core.xml")).find("dc:title", CORE)
        title = t.text.strip() if t is not None and t.text and t.text.strip() else None
    return Workbook(sheets=sheets, title=title, has_macros="xl/vbaProject.bin" in names,
                    external_links=sum(1 for n in names if n.startswith("xl/externalLinks/") and n.endswith(".xml")))


def _read_sheet(z, path, name, state, strings, names, styles) -> Sheet:
    root = ET.fromstring(z.read(path))
    sheet = Sheet(name=name, state=state)
    for row_el in root.iter(M + "row"):
        lvl = row_el.get("outlineLevel")
        if lvl and row_el.get("r") and int(lvl) > 0:
            sheet.outline[int(row_el.get("r"))] = int(lvl)
    shared: dict[str, tuple[str, int, int]] = {}
    pending = []
    for c in root.iter(M + "c"):
        ref = c.get("r")
        if not ref:
            continue
        col, row = split_ref(ref)
        t = c.get("t")
        sidx = int(c.get("s", "0"))
        style = styles[sidx] if sidx < len(styles) else PLAIN
        v = c.find(M + "v")
        raw = v.text if v is not None else None
        if t == "s" and raw is not None:
            raw = strings[int(raw)]
        elif t == "inlineStr":
            is_ = c.find(M + "is")
            raw = "".join(x.text or "" for x in is_.iter(M + "t")) if is_ is not None else None
        elif t == "b" and raw is not None:
            raw = "TRUE" if raw == "1" else "FALSE"
        f = c.find(M + "f")
        formula = kind = None
        if f is not None:
            ft = f.get("t")
            if ft == "shared":
                si = f.get("si")
                if f.text:
                    formula, kind = f.text, "shared_anchor"
                    shared[si] = (f.text, row, col_index(col))
                else:
                    pending.append((ref, row, col, t, raw, si, style))
                    continue
            elif ft == "array":
                formula, kind = f.text or "", "array"
            elif f.text:
                formula, kind = f.text, "normal"
        sheet.cells[(row, col)] = Cell(ref, row, col, t, raw, formula, kind, style)
        sheet.max_row = max(sheet.max_row, row)
    for ref, row, col, t, raw, si, style in pending:
        base = shared.get(si)
        formula = shift_formula(base[0], row - base[1], col_index(col) - base[2]) if base else None
        sheet.cells[(row, col)] = Cell(ref, row, col, t, raw, formula, "shared_expanded" if base else None, style)
        sheet.max_row = max(sheet.max_row, row)
    rel_path = posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels")
    targets = {}
    if rel_path in names:
        for r in ET.fromstring(z.read(rel_path)).iter(PR + "Relationship"):
            targets[r.get("Id")] = r.get("Target")
    for h in root.iter(M + "hyperlink"):
        tgt = targets.get(h.get(R + "id")) if h.get(R + "id") else None
        loc = h.get("location")
        if tgt or loc:
            for one in (h.get("ref") or "").split(":")[:1]:
                if one:
                    sheet.hyperlinks[one] = tgt or ("#" + loc)
    return sheet
