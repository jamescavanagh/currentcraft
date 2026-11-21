"""Synthetic boundary checks for the contracts-only evidence slice."""
import ast
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
from jsonschema import Draft202012Validator

from app.application.evidence import (
    CONTRACTS, EvidenceCellRange, EvidenceChunk, EvidenceChunkSet,
    EvidenceProvenance, EvidenceTextOffsets,
)
from app.application.evaluation import RankedRun, RelevanceJudgment

ROOT = Path(__file__).resolve().parents[1]


def cells(**changes):
    return dict(sheet_id="sheet_01", first_row=1, last_row=10,
                first_column=1, last_column=6, **changes)


def chunk(kind="page", **changes):
    provenance = dict(source_locator="loc_01", extractor_name="synthetic",
                      extractor_version="1.0", config_sha256="a" * 64)
    if kind == "page":
        provenance["page_number"] = 1
    elif kind in ("sheet", "bom_row"):
        provenance["cells"] = cells()
        if kind == "bom_row":
            provenance["cells"].update(first_row=2, last_row=2)
    else:
        provenance["offsets"] = dict(start=0, end=10, unit="unicode_codepoints")
    data = dict(chunk_id="chunk_" + kind, kind=kind, file_id="file_01",
                revision_id="rev_01", project_id="project_01", provenance=provenance)
    if kind == "bom_row":
        data["parent_chunk_id"] = "chunk_sheet"
    data.update(changes)
    return data


class EvidenceContractsTests(unittest.TestCase):
    def test_generated_schemas_are_valid_and_accept_synthetic_json(self):
        for model in CONTRACTS:
            Draft202012Validator.check_schema(model.model_json_schema())
        payload = EvidenceChunkSet(chunks=[chunk(k) for k in
                                   ("page", "sheet", "bom_row", "email", "chat_thread")])
        validator = Draft202012Validator(EvidenceChunkSet.model_json_schema())
        validator.validate(json.loads(payload.model_dump_json()))
        wrong_type = json.loads(payload.model_dump_json())
        wrong_type["chunks"][0]["provenance"]["page_number"] = "1"
        self.assertTrue(list(validator.iter_errors(wrong_type)))

    def test_all_five_kinds_roundtrip_preserve_supplied_identity(self):
        payload = dict(chunks=[chunk(k) for k in
                              ("page", "sheet", "bom_row", "email", "chat_thread")])
        snapshot = EvidenceChunkSet.model_validate(payload)
        self.assertEqual(snapshot, EvidenceChunkSet.model_validate_json(snapshot.model_dump_json()))
        self.assertEqual([c.chunk_id for c in snapshot.chunks], [c["chunk_id"] for c in payload["chunks"]])
        for before, after in zip(payload["chunks"], snapshot.chunks):
            for name in ("file_id", "revision_id", "project_id"):
                self.assertEqual(before[name], getattr(after, name))
        reversed_set = EvidenceChunkSet(chunks=tuple(reversed(snapshot.chunks)))
        self.assertEqual({c.chunk_id for c in snapshot.chunks}, {c.chunk_id for c in reversed_set.chunks})

    def test_handles_work_unchanged_in_evaluation(self):
        item = EvidenceChunk(**chunk())
        judgment = RelevanceJudgment(query_id="query_01", item_id=item.chunk_id, grade=3)
        run = RankedRun(system_id="system_01", query_id="query_01", items=(item.chunk_id,))
        self.assertEqual(judgment.item_id, run.items[0])
        self.assertNotIn("source_locator", run.model_dump_json())

    def test_all_fields_described_closed_frozen_and_schemas_generated(self):
        for model in CONTRACTS:
            with self.subTest(model=model.__name__):
                self.assertTrue(all(f.description and f.description.strip() for f in model.model_fields.values()))
                self.assertTrue(model.model_config["frozen"])
                self.assertEqual(model.model_config["extra"], "forbid")
                path = ROOT / "docs/contracts/schemas/agency" / (model.__name__ + ".schema.json")
                self.assertEqual(json.loads(path.read_text()), model.model_json_schema())
        item = EvidenceChunk(**chunk())
        with self.assertRaises(ValidationError):
            item.chunk_id = "replacement"
        for extra in ("text", "filename", "source_url", "approved"):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                EvidenceChunk(**dict(chunk(), **{extra: "forbidden"}))

    def test_offset_bounds_units_and_strict_integers(self):
        for unit in ("bytes", "unicode_codepoints"):
            self.assertEqual(EvidenceTextOffsets(start=0, end=1, unit=unit).end, 1)
        for start, end in ((-1, 2), (1, 1), (2, 1), (False, 1), (0, True), ("0", 1), (0, 1.0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                EvidenceTextOffsets(start=start, end=end, unit="bytes")
        with self.assertRaises(ValidationError):
            EvidenceTextOffsets(start=0, end=1, unit="characters")

    def test_cell_bounds_and_strict_integers(self):
        for changes in (dict(first_row=0), dict(last_row=0), dict(first_column=0),
                        dict(last_column=0), dict(last_row=False), dict(first_column="1"),
                        dict(first_row=11), dict(first_column=7)):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EvidenceCellRange(**(cells() | changes))

    def test_provenance_required_and_coordinate_exclusion(self):
        base = chunk()["provenance"]
        for name in ("source_locator", "extractor_name", "extractor_version", "config_sha256"):
            data = dict(base)
            del data[name]
            with self.subTest(missing=name), self.assertRaises(ValidationError):
                EvidenceProvenance(**data)
        for changes in (dict(source_locator="https://example.invalid/source"),
                        dict(extractor_version=" "), dict(config_sha256="not-a-hash"),
                        dict(page_number=0), dict(page_number=True),
                        dict(cells=cells(), offsets=dict(start=0, end=1, unit="bytes"))):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EvidenceProvenance(**(base | changes))

    def test_kind_locator_shapes_rejected_python_and_json(self):
        for kind in ("page", "sheet", "bom_row", "email", "chat_thread"):
            data = chunk(kind)
            field = "page_number" if kind == "page" else "cells" if kind in ("sheet", "bom_row") else "offsets"
            del data["provenance"][field]
            for value in (data, json.dumps(data)):
                with self.subTest(kind=kind), self.assertRaises(ValidationError):
                    (EvidenceChunk.model_validate_json(value) if isinstance(value, str)
                     else EvidenceChunk.model_validate(value))
        data = chunk("bom_row")
        data["provenance"]["cells"]["last_row"] = 3
        with self.assertRaises(ValidationError):
            EvidenceChunk(**data)
        for kind in ("sheet", "email", "chat_thread"):
            data = chunk(kind)
            data["provenance"]["page_number"] = 1
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                EvidenceChunk(**data)

    def test_opaque_binding_fields_and_schema_version(self):
        for field in ("chunk_id", "file_id", "revision_id", "project_id"):
            for value in ("", "a/b", "a b", "x" * 201):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    EvidenceChunk(**(chunk() | {field: value}))
        with self.assertRaises(ValidationError):
            EvidenceChunk(**(chunk() | dict(schema_version="future/v2")))

    def test_parent_rules_self_parent_and_cycles_fail_closed(self):
        for data in (chunk("bom_row", parent_chunk_id=None),
                     chunk("bom_row", parent_chunk_id="chunk_bom_row"),
                     chunk(parent_chunk_id="chunk_sheet"),
                     chunk("sheet", parent_chunk_id="chunk_bom_row")):
            with self.subTest(data=data["kind"]), self.assertRaises(ValidationError):
                EvidenceChunk(**data)

    def test_closed_snapshot_duplicates_missing_and_wrong_parent(self):
        for chunks in ([chunk(), chunk()], [chunk("bom_row")],
                       [chunk("bom_row", parent_chunk_id="chunk_page"), chunk()]):
            with self.subTest(chunks=len(chunks)), self.assertRaises(ValidationError):
                EvidenceChunkSet(chunks=chunks)
        self.assertEqual(EvidenceChunkSet(chunks=()).chunks, ())

    def test_parent_binding_matches_all_three_ids(self):
        for field in ("file_id", "revision_id", "project_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                EvidenceChunkSet(chunks=[chunk("sheet"), chunk("bom_row", **{field: "different"})])

    def test_bom_range_must_be_contained_in_same_sheet(self):
        for changes in (dict(sheet_id="other"), dict(first_row=11, last_row=11),
                        dict(first_column=7, last_column=7)):
            data = chunk("bom_row")
            data["provenance"]["cells"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EvidenceChunkSet(chunks=[chunk("sheet"), data])

    def test_different_root_files_allowed_without_implying_relationship(self):
        snapshot = EvidenceChunkSet(chunks=[chunk(), chunk("email", file_id="file_02", revision_id="rev_02")])
        self.assertTrue(all(c.parent_chunk_id is None for c in snapshot.chunks))

    def test_slice_imports_only_pydantic_typing_and_shared_contract_base(self):
        tree = ast.parse((ROOT / "src/app/application/evidence/contracts.py").read_text())
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {"__future__", "typing", "pydantic", "app.application.common.contracts"})
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
