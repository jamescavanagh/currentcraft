"""Workbook profile contracts: how a known spreadsheet template is read. Pydantic only; no bytes, no parsers.

Design source: docs/pipelines/XLSX_WORKBOOK.md. A profile is declared configuration, versioned and reviewed. It names
cells and columns; it never guesses positions. Enterprise profiles live outside the public tree (references/private/).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.application.common.contracts import _Frozen

Level = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,80}$")]
Col = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}$")]
A1 = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")]
SheetName = Annotated[str, StringConstraints(min_length=1, max_length=31)]
Row = Annotated[int, Field(ge=1, le=1048576)]


def _compiles(p: Optional[str]) -> Optional[str]:
    if p is not None:
        try:
            re.compile(p)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from None
    return p


class CellAnchor(_Frozen):
    """A cell whose text must match for the profile to apply (case- and whitespace-insensitive)."""

    sheet: SheetName = Field(description="Sheet name.")
    cell: A1 = Field(description="Cell reference.")
    text: str = Field(min_length=1, max_length=200, description="Expected text after whitespace collapse and casefold.")


class RowRule(_Frozen):
    """Classifies a row by a regex on one column. First matching rule wins; unmatched non-empty rows use the table default."""

    row_kind: Level = Field(description="Row kind, e.g. phase, task, subtotal, copy_marker, section.")
    pattern: str = Field(min_length=1, max_length=200, description="Python regex, matched with re.search on the cell text.")
    col: Optional[Col] = Field(default=None, description="Column tested; defaults to the table's label column.")
    sets_section: Optional[Level] = Field(default=None, description="For section rows: the line kind for following rows.")
    code_group: Optional[int] = Field(default=None, ge=1, le=9, description="Regex group holding a code (e.g. phase number).")

    @field_validator("pattern")
    @classmethod
    def _regex(cls, v):
        return _compiles(v)


class VocabularySpec(_Frozen):
    """A code list, read as reference values. A vocabulary is classification, not a list of installed things."""

    set_name: Level = Field(description="Reference set name.")
    sheet: SheetName = Field(description="Sheet name.")
    code_col: Col = Field(description="Code column.")
    label_col: Optional[Col] = Field(default=None, description="Label column; None when the code is its own label.")
    first_row: Row = Field(description="First data row.")
    last_row: Optional[Row] = Field(default=None, description="Last data row; None reads to the sheet end.")


class CatalogSpec(_Frozen):
    """A keyed table (rate card, plan list, link list). One object per row with a code; section rows are kept as context."""

    kind: Level = Field(description="Object kind emitted, e.g. labor_role, support_plan_option, travel_line, reference_link.")
    sheet: SheetName = Field(description="Sheet name.")
    first_row: Row = Field(description="First data row.")
    last_row: Optional[Row] = Field(default=None, description="Last data row.")
    code_col: Col = Field(description="Code column; rows without a code are skipped or treated as sections.")
    label_col: Optional[Col] = Field(default=None, description="Label column.")
    fields: dict[Level, Col] = Field(default_factory=dict, description="Extra field -> column, kept as raw text.")
    section_pattern: Optional[str] = Field(default=None, max_length=200,
                                           description="Regex on the label column marking a section row (code column holds the section name).")
    skip_codes: tuple[str, ...] = Field(default=(), description="Codes treated as non-entries, e.g. 'Total:'.")
    capture_hyperlinks: bool = Field(default=False, description="Keep the code cell's hyperlink target as a field. Never fetched.")

    @field_validator("section_pattern")
    @classmethod
    def _regex(cls, v):
        return _compiles(v)


class HierarchySpec(_Frozen):
    """How a task-list column carries its WBS levels when the sheet has no outline grouping or WBS code column.

    Levels: 1 phase (root), 2 stem (boilerplate task or sub-system heading), 3 leaf (task under a sub-system).
    Text rules classify; formatting confirms. Disagreement is a diagnostic, never a silent override. Leaf parents are
    proposals: the template does not state them.
    """

    section_start_pattern: str = Field(min_length=1, max_length=200, description="Regex for the row opening a sub-system section.")
    subsystem_min_indent: int = Field(default=3, ge=1, le=15, description="Alignment indent marking a sub-system row inside a section.")
    leaf_min_indent: Optional[int] = Field(default=None, ge=1, le=15, description="Indent marking a leaf; default subsystem_min_indent + 1.")
    leaf_code_pattern: Optional[str] = Field(default=None, max_length=200,
                                             description="Regex, group 1 a sub-system code, naming a leaf, e.g. '^([A-Z0-9]{2,8})\\s+-\\s+'.")
    subsystem_set: Optional[Level] = Field(default=None, description="Vocabulary resolving sub-system codes from row names.")
    placeholder_pattern: Optional[str] = Field(default=None, max_length=200,
                                               description="Regex, group 1 an example code, for template placeholder rows. Examples never resolve.")
    bold_kinds: tuple[Level, ...] = Field(default=("phase", "subtotal", "total"), description="Row kinds expected to be bold.")
    use_outline_levels: bool = Field(default=True, description="Prefer Excel outline levels when the sheet has them.")

    @field_validator("section_start_pattern", "leaf_code_pattern", "placeholder_pattern")
    @classmethod
    def _regex(cls, v):
        return _compiles(v)


class RoleClassRule(_Frozen):
    """Classifies a role block by its code: who supplies the labor."""

    pattern: str = Field(min_length=1, max_length=200, description="Regex on the role code.")
    labor_source: Literal["internal", "contract", "vendor"] = Field(description="Internal staff, contract/freelance, or vendor-provided service.")
    priced_elsewhere: bool = Field(default=False, description="Hours recorded here but priced as another line (e.g. sold with equipment).")

    @field_validator("pattern")
    @classmethod
    def _regex(cls, v):
        return _compiles(v)


class RoleMatrixSpec(_Frozen):
    """A task x role effort grid: one label column, repeated role blocks of (count, hours each, total)."""

    sheet: SheetName = Field(description="Sheet name.")
    label_col: Col = Field(description="Task label column.")
    header_row: Row = Field(description="Row holding role headers (code on the first line).")
    rate_row: Optional[Row] = Field(default=None, description="Row holding the hourly rate per block.")
    first_row: Row = Field(description="First row of the grid body.")
    last_row: Row = Field(description="Last row of the grid body.")
    first_block_col: Col = Field(description="First column of the first role block.")
    block_width: int = Field(default=3, ge=1, le=8, description="Columns per role block.")
    block_count: int = Field(ge=1, le=200, description="Number of role blocks.")
    count_offset: int = Field(default=0, ge=0, description="Offset of the crew count column within a block.")
    hours_offset: int = Field(default=1, ge=0, description="Offset of the hours-each column.")
    total_offset: int = Field(default=2, ge=0, description="Offset of the block total column.")
    row_total_col: Optional[Col] = Field(default=None, description="Row total column.")
    responsibility_col: Optional[Col] = Field(default=None, description="Responsibility column (raw text).")
    notes_col: Optional[Col] = Field(default=None, description="Scope-notes column.")
    role_code_pattern: str = Field(default=r"^\s*(\S+)", description="Regex; group 1 is the role code in the header cell.")
    placeholder_values: tuple[str, ...] = Field(default=(), description="Cell texts meaning 'not filled in', e.g. 'Drop Down List'.")
    rules: tuple[RowRule, ...] = Field(min_length=1, description="Row classification. Rows of kind 'phase' open a phase block.")
    task_kinds: tuple[Level, ...] = Field(default=("task",), description="Row kinds that become task occurrences.")
    default_kind: Level = Field(default="task", description="Kind for non-empty rows that match no rule.")
    hierarchy: Optional[HierarchySpec] = Field(default=None, description="WBS level detection for the label column.")
    role_classes: tuple[RoleClassRule, ...] = Field(default=(), description="First matching rule classifies a role block.")
    role_code_format: Optional[str] = Field(default=None, max_length=200,
                                            description="Regex with named groups series, number, year splitting a role code.")
    responsibility_classes: dict[str, tuple[Literal["internal", "contract", "vendor", "client"], ...]] = Field(
        default_factory=dict, description="Responsibility value (case-insensitive) -> party classes it names, e.g. 'Team / Client' -> internal, client.")
    responsibility_precedence: Literal["internal", "none"] = Field(
        default="none", description="'internal': when hours and responsibility disagree and internal staff is on either side, internal wins.")

    @field_validator("role_code_pattern", "role_code_format")
    @classmethod
    def _regex(cls, v):
        return _compiles(v)

    @model_validator(mode="after")
    def _rows(self):
        if self.last_row < self.first_row:
            raise ValueError("last_row before first_row")
        if len({self.count_offset, self.hours_offset, self.total_offset}) != 3 or max(
                self.count_offset, self.hours_offset, self.total_offset) >= self.block_width:
            raise ValueError("block offsets must be distinct and inside the block")
        return self


class LineTableSpec(_Frozen):
    """A sectioned line table (bill of equipment, allowances). Quantity-bearing rows become estimate lines."""

    name: Level = Field(description="Table name, e.g. bill_of_equipment.")
    sheet: SheetName = Field(description="Sheet name.")
    first_row: Row = Field(description="First data row.")
    last_row: Optional[Row] = Field(default=None, description="Last data row.")
    columns: dict[Level, Col] = Field(description="Field -> column. Needs description, quantity, part_number, manufacturer.")
    money_fields: tuple[Level, ...] = Field(default=(), description="Fields kept as raw text only (Decimal downstream).")
    classification_field: Optional[Level] = Field(default=None, description="Field resolved against a vocabulary.")
    classification_set: Optional[Level] = Field(default=None, description="Vocabulary set_name for classification_field.")
    rules: tuple[RowRule, ...] = Field(default=(), description="Section, group, subtotal and total rows.")
    default_section: Level = Field(default="line", description="Line kind before the first section row.")
    content_fields: tuple[Level, ...] = Field(default=("part_number", "description"),
                                              description="A row is a line only if one of these is non-empty.")

    @model_validator(mode="after")
    def _cols(self):
        missing = {"description", "quantity", "part_number", "manufacturer"} - set(self.columns)
        if missing:
            raise ValueError(f"columns missing {sorted(missing)}")
        if (self.classification_field is None) != (self.classification_set is None):
            raise ValueError("classification_field and classification_set go together")
        return self


class RowReferenceCheck(_Frozen):
    """On each row, formulas in ref_cols must reference one target column, and that column's role block must carry the
    row's code. Findings are diagnostics; formulas are never repaired."""

    name: Level = Field(description="Check name.")
    sheet: SheetName = Field(description="Sheet name.")
    first_row: Row = Field(description="First row.")
    last_row: Row = Field(description="Last row.")
    code_col: Col = Field(description="Column holding the row's role code.")
    ref_cols: tuple[Col, ...] = Field(min_length=2, description="Columns whose formulas reference the role matrix.")


class CrosswalkCheck(_Frozen):
    """Codes in one catalog compared to another by prefix; differing labels are reported, never resolved."""

    name: Level = Field(description="Check name.")
    source_kind: Level = Field(description="Catalog kind holding the short codes.")
    target_kind: Level = Field(description="Catalog kind holding canonical codes.")


class WorkbookProfile(_Frozen):
    """Declared reading of one workbook template version. Unknown layouts are rejected, not guessed."""

    name: Level = Field(description="Profile name; RawItem.mapping selects it.")
    version: Level = Field(description="Profile version; part of every object's provenance fields.")
    anchors: tuple[CellAnchor, ...] = Field(min_length=1, description="All must match, else the workbook is quarantined.")
    vocabularies: tuple[VocabularySpec, ...] = Field(default=(), description="Code lists.")
    catalogs: tuple[CatalogSpec, ...] = Field(default=(), description="Keyed tables.")
    role_matrix: Optional[RoleMatrixSpec] = Field(default=None, description="Task x role effort grid.")
    line_tables: tuple[LineTableSpec, ...] = Field(default=(), description="Sectioned line tables.")
    reference_checks: tuple[RowReferenceCheck, ...] = Field(default=(), description="Formula reference consistency checks.")
    crosswalk_checks: tuple[CrosswalkCheck, ...] = Field(default=(), description="Code crosswalk checks.")
    excluded_sheets: tuple[SheetName, ...] = Field(default=(), description="Sheets deliberately not interpreted; references into them are reported.")
    document_type: Optional[Level] = Field(default=None, description="When set, the workbook is emitted as a project document of this type.")


WORKBOOK_CONTRACTS = (CellAnchor, RowRule, VocabularySpec, CatalogSpec, HierarchySpec, RoleClassRule, RoleMatrixSpec, LineTableSpec, RowReferenceCheck,
                      CrosswalkCheck, WorkbookProfile)
