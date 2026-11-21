"""Generate (or --check) the agency contract docs: process, plate, messaging, enrichment, probe, ingestion, persistence, splice, hfgt. Mirrors gen_gauge_contract_docs.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import evidence as EC  # noqa: E402
from app.application import enrichment as EN  # noqa: E402
from app.application import messaging as MS  # noqa: E402
from app.application import plate as PL  # noqa: E402
from app.application import probe as PB  # noqa: E402
from app.application import ingest as IG  # noqa: E402
from app.application import enterprise as ENT
from app.application.enterprise.contracts import ENTITY_TYPES
from app.domain.shared.identity import ExternalReference
from app.domain.shared.facts import TimeWindow, DateBounds
from app.domain.shared.contexts import ProjectContext, SubsystemContext
from app.domain.quality.quality_evidence import Derivation
from app.domain.shared.quantities import UnitRef, Quantity, SourceMoney
from app.domain.versioning import VersionedEntity
from app.domain.workforce.resource import Resource
from app.application import process as PR  # noqa: E402
from app.application import persistence as PS  # noqa: E402
from app.application import splice as SP  # noqa: E402
from app.application import hfgt as HF  # noqa: E402
from app.application.messaging.durable import DURABLE_CONTRACTS  # noqa: E402
from app.application.persistence.deletion_review import REVIEW_CONTRACTS  # noqa: E402

_spec = importlib.util.spec_from_file_location("_gauge_docs", ROOT / "scripts" / "gen_gauge_contract_docs.py")
_g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_g)
_g.JUNK = _g.JUNK + ("app.application.ingest.contracts.", "app.application.probe.contracts.", "app.application.enrichment.contracts.", "app.application.process.contracts.", "app.application.plate.contracts.",
                     "app.application.messaging.contracts.", "app.application.messaging.durable.", "app.application.persistence.contracts.", "app.application.splice.contracts.", "app.application.hfgt.contracts.", "app.application.common.contracts.", "datetime.", "decimal.", "uuid.")

_base_type = _g._type


def _strip_annotated(s: str) -> str:
    """Replace Annotated[X, constraints...] with X, matching brackets (constraints can contain brackets)."""
    while "Annotated[" in s:
        i = s.index("Annotated[")
        j, depth, comma = i + len("Annotated["), 1, None
        while depth:
            ch = s[j]
            depth += ch == "["
            depth -= ch == "]"
            if ch == "," and depth == 1 and comma is None:
                comma = j
            j += 1
        s = s[:i] + s[i + len("Annotated["):comma] + s[j:]
    return s


def _type(ann) -> str:
    import enum
    if isinstance(ann, type):
        return _base_type(ann)
    s = _strip_annotated(str(ann))
    for junk in _g.JUNK + ("pydantic.types.",):
        s = s.replace(junk, "")
    s = s.replace("NoneType", "None")
    import re
    s = re.sub(r"<class '([\w.]+)'>", lambda m: m.group(1).split(".")[-1], s)
    return s if len(s) < 90 else s[:87] + "..."


_g._type = _type
OUT = ROOT / "docs" / "contracts"
SLICES = (("Enterprise capture proposals", "domain/V1_DOMAIN.md", ENT.SCHEMA_VERSION,
           ENT.CONTRACTS + ENTITY_TYPES + (ExternalReference, TimeWindow, DateBounds, ProjectContext, SubsystemContext, Derivation, UnitRef, Quantity, SourceMoney, VersionedEntity, Resource), ()),
          ("Process-first domain", "domain/PROCESS_FIRST.md", PR.SCHEMA_VERSION, PR.CONTRACTS, ()),
          ("Plate and spatial isosceles", "pipelines/PLATE_ISOSCELES.md", PL.SCHEMA_VERSION, PL.CONTRACTS, PL.TENSOR_CONTRACTS),
          ("Messaging", "architecture/MESSAGE_BROKER.md", MS.SCHEMA_VERSION, MS.CONTRACTS, ()),
          ("Embedding enrichment", "pipelines/EMBEDDING_ENRICHMENT.md", EN.SCHEMA_VERSION, EN.CONTRACTS, EN.TENSOR_CONTRACTS),
          ("Probe", "pipelines/PROBE.md", PB.SCHEMA_VERSION, PB.CONTRACTS, ()),
          ("Ingestion", "architecture/INGESTION.md", IG.SCHEMA_VERSION, IG.CONTRACTS, IG.TENSOR_CONTRACTS),
          ("Persistence", "architecture/PERSISTENCE.md", PS.SCHEMA_VERSION, PS.CONTRACTS, ()),
          ("Durable broker", "architecture/JETSTREAM.md", "datamesh-durable-messaging/v1", DURABLE_CONTRACTS, ()),
          ("Storage deletion review", "architecture/DELETION_REVIEW.md", "datamesh-deletion-review/v1", REVIEW_CONTRACTS, ()),
          ("Sparse phase splice", "pipelines/SPARSE_PHASE_SPLICE.md", SP.SCHEMA_VERSION, SP.CONTRACTS, ()),
          ("HFGT capability graph", "pipelines/HFGT_CAPABILITY_GRAPH.md", HF.SCHEMA_VERSION, HF.CONTRACTS, HF.TENSOR_CONTRACTS))


def render() -> dict[str, str]:
    md = ["---", "title: Agency contracts (generated)", "tags: [datamesh, generated]", "---", "",
          "# Agency contracts (generated)", "",
          "Generated by `scripts/gen_agency_contract_docs.py`. Do not edit by hand: change the contract, then regenerate.",
          "CI fails when this file is stale. Design sources are linked per slice.", "",
          "JSON Schema encodes local structural conditions, not cross-record validation or authorization.",
          "See [validation matrix](../domain/V1_REVIEW_CORRECTIONS.md#schema--validation-matrix) for Python/JSON input and application/policy limits.", ""]
    files: dict[str, str] = {}
    for title, page, version, contracts, tensor_contracts in SLICES:
        md += [f"## {title}", "", f"Design source: [{page}](../{page}). Schema version: `{version}`.", ""]
        for m in contracts:
            md += [f"### `{m.__name__}`", "", (m.__doc__ or "").strip(), ""]
            if m in tensor_contracts:
                md += [f"Produced by `{m.PRODUCED_BY}`.", "",
                       *_g._tensor_rows(m.TENSORS, lambda n, m=m: m.model_fields[n].is_required()), ""]
            md += ["| Field | Type | Required | Description |", "| --- | --- | --- | --- |", *_g._rows(m), ""]
            files[f"schemas/agency/{m.__name__}.schema.json"] = json.dumps(m.model_json_schema(), indent=2, sort_keys=True) + "\n"
    md += ["## Plate readout features", "", "Column order of `PlateRunResult.plate` (axis `feature`):", "",
           "| # | Feature | Meaning |", "| --- | --- | --- |",
           *[f"| {i} | `{f}` | {PL.PLATE_FEATURE_MEANINGS[f]} |" for i, f in enumerate(PL.PLATE_FEATURES)], "",
           "## Allowed effects by function class", "", "| Class | Effects |", "| --- | --- |",
           *[f"| `{c}` | {', '.join(f'`{e}`' for e in sorted(v))} |" for c, v in PR.ALLOWED_EFFECTS.items()], "",
           "## JSON Schemas", "", *[f"- [`{n.split('/')[-1][:-12]}`]({n})" for n in sorted(files)], ""]
    files["AGENCY_CONTRACTS.md"] = "\n".join(md)
    # Keep the existing agency reference byte-identical for parallel lanes.
    evidence_md = ["---", "title: Evidence contracts (generated)", "tags: [currentcraft, generated]", "---", "",
                   "# Evidence contracts (generated)", "",
                   "Generated by `scripts/gen_agency_contract_docs.py`. Do not edit by hand.", "",
                   f"Schema version: `{EC.SCHEMA_VERSION}`.",
                   "Design source: [Hierarchical evidence chunks](../architecture/EVIDENCE_CHUNKS.md).", "",
                   "JSON Schema covers structural constraints, not cross-record validation or authorization.", ""]
    for model in EC.CONTRACTS:
        evidence_md += [f"## `{model.__name__}`", "", (model.__doc__ or "").strip(), "",
                        "| Field | Type | Required | Description |", "| --- | --- | --- | --- |",
                        *_g._rows(model), "",
                        f"[JSON Schema](schemas/agency/{model.__name__}.schema.json)", ""]
        files[f"schemas/agency/{model.__name__}.schema.json"] = json.dumps(
            model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    files["EVIDENCE_CONTRACTS.md"] = "\n".join(evidence_md)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    files, stale = render(), []
    for rel, text in files.items():
        path = OUT / rel
        if a.check:
            if not path.exists() or path.read_text() != text:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if a.check:
        extra = sorted(str(p.relative_to(OUT)) for p in (OUT / "schemas" / "agency").glob("*.json") if str(p.relative_to(OUT)) not in files)
        for rel in stale:
            print(f"STALE {rel}")
        for rel in extra:
            print(f"ORPHAN {rel}")
        print(f"{'OK' if not stale and not extra else 'FAIL'}: {len(files)} generated agency docs, {len(stale)} stale, {len(extra)} orphan")
        if stale or extra:
            print("Run: python3 scripts/gen_agency_contract_docs.py")
        return 1 if stale or extra else 0
    print(f"wrote {len(files)} files to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
