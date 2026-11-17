"""Sparse phase splice contracts: workbook source occurrences -> phase-blocked sparse embeddings. Pydantic only.

Design source: docs/pipelines/SPARSE_PHASE_SPLICE.md.

A splice couples two things that must never be confused:

* the **lifecycle phase** a source occurrence belongs to (a phase code read from the workbook, e.g. "2"), and
* a **chart angle**: a declared, versioned research coordinate that places each phase code on a circle so that the
  sparse embedding can weight cross-phase similarity.

The chart angle is not the plate/probe phase theta of the simulator and is never fed to it implicitly. Phase codes are
read from declared evidence only (a field, one typed relation hop, or positive per-phase hours); row order, titles and
blank or zero cells never assign a phase.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.ingest.contracts import DomainObject, Ident, Level
from app.application.persistence.contracts import EmbeddingRecord, EmbeddingSpace
from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "datamesh-splice/v1"
TOKENIZER = "words-v1+blake2b-signed-hash-v1"
MAX_DIM = 65536
PhaseCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,40}$")]
FieldName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,60}$")]
Degrees = Annotated[float, Field(ge=0.0, lt=360.0, allow_inf_nan=False)]


def _sha(model: _Frozen) -> str:
    return hashlib.sha256(model.model_dump_json().encode()).hexdigest()


class PhaseAnchor(_Frozen):
    """Where one lifecycle phase code sits on the chart."""

    phase_code: PhaseCode = Field(description="Phase code exactly as the adapter emits it (e.g. '2').")
    angle_deg: Degrees = Field(description="Chart angle in degrees, before origin and direction are applied.")
    label: Optional[str] = Field(default=None, max_length=80, description="Display label; never used for matching.")


class PhaseChart(_Frozen):
    """Declared phase parameters. A research coordinate for similarity weighting, never the simulator plate phase.

    Bin weights for a phase at chart angle a: w_b proportional to exp(kappa * cos(phi_b - a)), phi_b = 2 pi b / bins,
    then bins below floor * max(w) are dropped and the rest renormalised to sum 1.
    """

    name: Level = Field(description="Chart name.")
    version: Level = Field(description="Chart version; bump on any parameter change.")
    anchors: tuple[PhaseAnchor, ...] = Field(min_length=1, max_length=64, description="One anchor per phase code.")
    origin_deg: Degrees = Field(default=0.0, description="Rotation applied to every anchor.")
    direction: Literal["ccw", "cw"] = Field(default="ccw", description="ccw adds angles, cw subtracts them.")
    bins: int = Field(default=12, ge=2, le=72, description="Phase bins around the circle (B).")
    concentration: float = Field(default=4.0, ge=0.0, le=64.0, allow_inf_nan=False,
                                 description="von Mises kappa. 0 ignores phase entirely; large values separate phases.")
    floor: float = Field(default=0.05, ge=0.0, lt=1.0, allow_inf_nan=False,
                         description="Drop bins whose weight is below floor x the largest bin (sparsity).")
    shared_weight: float = Field(default=0.25, ge=0.0, le=1.0, allow_inf_nan=False,
                                 description="Share s of a phased object's mass kept in the phase-free block.")
    provenance: str = Field(min_length=3, max_length=300, description="Who set these parameters and why.")

    @model_validator(mode="after")
    def _rules(self):
        codes = [a.phase_code for a in self.anchors]
        if len(set(codes)) != len(codes):
            raise ValueError("phase codes must be unique in a chart")
        return self

    @classmethod
    def uniform(cls, codes, *, name="uniform", version="1", provenance="uniform spacing in template order", **kw) -> "PhaseChart":
        """Evenly spaced anchors in the given order (template order is an ordering, not a dependency)."""
        n = len(codes)
        return cls(name=name, version=version, provenance=provenance,
                   anchors=tuple(PhaseAnchor(phase_code=c, angle_deg=360.0 * k / n) for k, c in enumerate(codes)), **kw)

    def angle_rad(self, code: str) -> Optional[float]:
        """Effective chart angle of a phase code (origin and direction applied), or None when unanchored."""
        for a in self.anchors:
            if a.phase_code == code:
                sign = 1.0 if self.direction == "ccw" else -1.0
                return math.radians((self.origin_deg + sign * a.angle_deg) % 360.0)
        return None

    def bin_weights(self, code: str) -> Optional[tuple[float, ...]]:
        """Normalised bin distribution of one phase code (pure Python; B <= 72)."""
        a = self.angle_rad(code)
        if a is None:
            return None
        raw = [math.exp(self.concentration * (math.cos(2 * math.pi * b / self.bins - a) - 1.0)) for b in range(self.bins)]
        top = max(raw)
        kept = [w if w >= self.floor * top else 0.0 for w in raw]
        tot = sum(kept)
        return tuple(w / tot for w in kept)

    def coupling(self, code_a: str, code_b: str) -> Optional[float]:
        """Analytic phase factor between two single-phase objects: s + (1 - s) * Bhattacharyya(w_a, w_b)."""
        wa, wb = self.bin_weights(code_a), self.bin_weights(code_b)
        if wa is None or wb is None:
            return None
        bc = sum(math.sqrt(x * y) for x, y in zip(wa, wb))
        return self.shared_weight + (1.0 - self.shared_weight) * bc

    def digest(self) -> str:
        return _sha(self)


class PhaseEvidenceRule(_Frozen):
    """How one object kind gets its phase. Declared evidence only; first matching rule wins."""

    kind: Level = Field(description="Object kind the rule applies to.")
    source: Literal["field", "relation", "per_phase_hours"] = Field(description="Evidence type.")
    field: Optional[FieldName] = Field(default=None, description="field: the field holding the phase code.")
    relation_types: tuple[Level, ...] = Field(default=(), max_length=16,
                                              description="relation: follow one hop to a target that has field evidence.")
    hours_field_template: Optional[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]*\{code\}[A-Za-z0-9_]*$")]] = Field(
        default=None, description="per_phase_hours: field name with {code}, e.g. ph{code}_raw. Only values > 0 count.")

    @model_validator(mode="after")
    def _rules(self):
        if self.source == "field" and not self.field:
            raise ValueError("field rule needs field")
        if self.source == "relation" and not self.relation_types:
            raise ValueError("relation rule needs relation_types")
        if self.source == "per_phase_hours" and not self.hours_field_template:
            raise ValueError("per_phase_hours rule needs hours_field_template")
        return self


class SpliceProfile(_Frozen):
    """Everything that defines one sparse splice space. Changing any value changes the space identity."""

    name: Level = Field(description="Profile name; becomes the embedding model name.")
    version: Level = Field(description="Profile version.")
    text_dim: int = Field(default=4096, ge=16, le=16384, description="Hashed feature width per block (D).")
    slot_fields: tuple[FieldName, ...] = Field(default=("kind", "row_kind", "subsystem_code", "subsystem_state", "labor_source",
                                                        "role_series", "line_kind", "set_name", "section"),
                                               max_length=32, description="Fields hashed as namespaced tokens f:<field>=<value>. 'kind' is the object kind.")
    relation_slots: bool = Field(default=True, description="Hash relation types (never targets) as r:<type> tokens.")
    relation_slot_exclude: tuple[Level, ...] = Field(default=("in_revision", "extracted_from", "revision_of"), max_length=32,
                                                     description="Provenance relations every occurrence carries; not hashed as slots.")
    slot_weight: float = Field(default=0.5, gt=0.0, le=4.0, allow_inf_nan=False, description="Weight of slot tokens relative to words.")
    excluded_kinds: tuple[Level, ...] = Field(default=("ingest_diagnostic", "project_reference", "opportunity_reference",
                                                       "project_document", "workbook_revision"),
                                              description="Kinds kept out of the space (containers, bindings and template defects).")
    phase_rules: tuple[PhaseEvidenceRule, ...] = Field(default=(), max_length=64, description="Phase evidence per kind.")
    chart: PhaseChart = Field(description="Phase parameters.")

    @model_validator(mode="after")
    def _rules(self):
        if self.dim > MAX_DIM:
            raise ValueError(f"(bins + 1) x text_dim = {self.dim} exceeds {MAX_DIM}")
        return self

    @property
    def dim(self) -> int:
        """Shared block plus one block per phase bin."""
        return (self.chart.bins + 1) * self.text_dim

    def digest(self) -> str:
        return _sha(self)

    def space(self) -> EmbeddingSpace:
        """Model identity: profile name, and a version pinned to the full profile digest (chart included)."""
        return EmbeddingSpace(model_name=self.name, model_version=f"{self.version}.{self.digest()[:12]}", dim=self.dim,
                              precision="float32")


class PhaseAssignment(_Frozen):
    """The phase evidence of one object. Weights are shares over phase codes, summing to 1 when phased."""

    object_id: Ident = Field(description="Object.")
    state: Literal["phased", "mixed", "unphased"] = Field(description="One phase, several phases, or none.")
    weights: tuple[tuple[PhaseCode, float], ...] = Field(default=(), description="(phase_code, share) pairs, codes sorted.")
    basis: str = Field(min_length=1, max_length=200, description="Rule and evidence that produced the assignment, or why none.")

    @model_validator(mode="after")
    def _rules(self):
        if self.state == "unphased" and self.weights:
            raise ValueError("unphased has no weights")
        if self.state != "unphased":
            if not self.weights or abs(sum(w for _, w in self.weights) - 1.0) > 1e-9 or any(w <= 0 for _, w in self.weights):
                raise ValueError("phased weights must be positive and sum to 1")
            if (self.state == "phased") != (len(self.weights) == 1):
                raise ValueError("phased means exactly one code; mixed means several")
        return self

    @property
    def dominant(self) -> Optional[str]:
        return max(self.weights, key=lambda cw: (cw[1], cw[0]))[0] if self.weights else None


class SpliceRecord(_Frozen):
    """One object in the splice space."""

    object_id: Ident = Field(description="Object.")
    kind: Level = Field(description="Object kind.")
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="Raw content lineage.")
    assignment: PhaseAssignment = Field(description="Phase evidence.")
    tokens: NonNegativeInt = Field(description="Distinct content tokens hashed (words + slots).")
    bins_used: tuple[NonNegativeInt, ...] = Field(default=(), description="Phase bins carrying mass (0-based bin index).")
    embedding: EmbeddingRecord = Field(description="Sparse vector, zero-based indices. Block 0 is phase-free; block 1+b is bin b.")


class SpliceJunction(_Frozen):
    """A cross-phase coupling candidate: two objects in different phases whose content overlaps. Never a relation."""

    a: Ident = Field(description="First object (lower id).")
    b: Ident = Field(description="Second object.")
    phase_a: PhaseCode = Field(description="Dominant phase of a.")
    phase_b: PhaseCode = Field(description="Dominant phase of b.")
    content_similarity: float = Field(ge=-1.0, le=1.0, description="Cosine of the phase-free content vectors.")
    phase_coupling: float = Field(ge=0.0, le=1.0, description="Phase factor between the two objects under the chart.")
    spliced_similarity: float = Field(ge=-1.0, le=1.0, description="Cosine in the splice space = content x coupling.")
    angular_distance_deg: float = Field(ge=0.0, le=180.0, description="Chart distance between dominant phases.")
    shared_terms: tuple[str, ...] = Field(default=(), max_length=8, description="Words both objects carry (display only).")
    status: Literal["candidate"] = Field(default="candidate", description="Always a candidate; a person labels it.")


class SpliceRequest(_Frozen):
    """Splice a set of source occurrences under one profile."""

    profile: SpliceProfile = Field(description="Space definition and phase parameters.")
    objects: tuple[DomainObject, ...] = Field(min_length=1, max_length=100000, description="Adapter output (any kinds).")
    recorded_at: datetime = Field(description="Timestamp written on each EmbeddingRecord (timezone-aware).")
    junction_min_content: float = Field(default=0.35, ge=0.0, le=1.0, description="Content cosine a junction must reach.")
    max_junctions: int = Field(default=200, ge=0, le=5000, description="Top junctions kept, by spliced similarity.")
    junction_min_shared_terms: int = Field(default=1, ge=0, le=8,
                                           description="Words both objects must share, so slot tokens alone never make a junction.")
    junction_kinds: tuple[Level, ...] = Field(default=(), max_length=64,
                                              description="Kinds that may form junctions; empty allows every embedded kind.")

    @model_validator(mode="after")
    def _rules(self):
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        ids = [o.object_id for o in self.objects]
        if len(set(ids)) != len(ids):
            raise ValueError("object ids must be unique in one splice")
        return self


class SpliceResult(_Frozen):
    """Sparse records, cross-phase junction candidates and the diagnostics of one splice."""

    schema_version: Literal["datamesh-splice/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    profile_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="Profile digest.")
    chart_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="Chart digest.")
    space: EmbeddingSpace = Field(description="Embedding space of every record.")
    records: tuple[SpliceRecord, ...] = Field(description="One per object not excluded, input order.")
    excluded: tuple[Ident, ...] = Field(default=(), description="Objects kept out by kind.")
    junctions: tuple[SpliceJunction, ...] = Field(default=(), description="Cross-phase candidates, best first.")
    junctions_considered: NonNegativeInt = Field(default=0, description="Cross-phase pairs above the content threshold before the cap.")
    diagnostics: tuple[str, ...] = Field(default=(), max_length=1000, description="Evidence that was present but not usable.")

    def counts(self) -> dict[str, int]:
        out = {"phased": 0, "mixed": 0, "unphased": 0}
        for r in self.records:
            out[r.assignment.state] += 1
        out["excluded"] = len(self.excluded)
        return out


CONTRACTS = (PhaseAnchor, PhaseChart, PhaseEvidenceRule, SpliceProfile, PhaseAssignment, SpliceRecord, SpliceJunction,
             SpliceRequest, SpliceResult)
