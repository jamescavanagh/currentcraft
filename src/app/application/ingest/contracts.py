"""Ingestion contracts: raw topics, domain records, ring entries, tensor plans and batches. Pydantic only.

Design source: docs/architecture/INGESTION.md. Raw bytes never appear here: only BlobRef handles.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, ClassVar, Literal, Optional, Union

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.simulation.contracts import TensorContract
from app.application.common.contracts import _Frozen
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-ingest/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,160}$")]
Level = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,80}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Scalar = Union[str, int, float, bool, None]
SourceFormat = Literal["email", "docx", "pdf", "json", "data_contract", "text", "xlsx"]
MAX_TEXT = 20000


def _aware(dt: Optional[datetime], name: str):
    if dt is not None and dt.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


class BlobRef(_Frozen):
    """Handle to raw content in a blob store. Only adapters read the bytes."""

    key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:/-]{1,200}$")] = Field(description="Blob store key.")
    sha256: Digest = Field(description="SHA-256 of the bytes.")
    size: NonNegativeInt = Field(description="Byte length.")
    media_type: str = Field(min_length=1, max_length=120, description="Declared media type.")


class IntakeBinding(_Frozen):
    """What a raw item is about, supplied at intake by the source system (never parsed from a filename or cell).

    Ties a document (e.g. a project estimation workbook) to the project or opportunity it belongs to. The reference is a
    governed external reference, not a graph key; the canonical Project entity is resolved later by a reviewed mapping.
    """

    subject_kind: Literal["project", "opportunity"] = Field(description="What the document belongs to.")
    subject_namespace: Level = Field(description="Issuing system of the reference, e.g. erp.project, crm.opportunity.")
    subject_ref: Level = Field(description="Reference value as issued by that system.")
    document_type: Level = Field(description="Business document type, e.g. PEW.")
    revision_label: Optional[str] = Field(default=None, max_length=80,
                                          description="Supplied stage label, e.g. 'Round 1'. Never inferred from content.")


class RawItem(_Frozen):
    """One raw intake, published to raw/<platform>/<format>/<source_id>."""

    platform: Level = Field(description="Source platform, e.g. sharepoint, outlook, tracker, erp, file.")
    format: SourceFormat = Field(description="Content format; selects the adapter.")
    source_id: Level = Field(description="Id of the item within its platform.")
    received_at: datetime = Field(description="Real intake time (timezone-aware).")
    content: BlobRef = Field(description="Content handle.")
    mapping: Optional[Level] = Field(default=None, description="JsonMapping name for format json; WorkbookProfile name for format xlsx.")
    contract_name: Optional[Level] = Field(default=None, description="Registered data contract, required for format data_contract.")
    binding: Optional[IntakeBinding] = Field(default=None, description="What the item belongs to, supplied at intake.")

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.received_at, "received_at")
        if self.format == "json" and not self.mapping:
            raise ValueError("json intake needs a mapping")
        if self.format == "xlsx" and not self.mapping:
            raise ValueError("xlsx intake needs a workbook profile name in mapping")
        if self.format == "data_contract" and not self.contract_name:
            raise ValueError("data_contract intake needs a contract_name")
        return self

    @property
    def topic(self) -> str:
        return f"raw/{self.platform}/{self.format}/{self.source_id}"


class Provenance(_Frozen):
    """Where a domain object came from and which transform made it."""

    platform: Level = Field(description="Source platform.")
    format: SourceFormat = Field(description="Source format.")
    source_id: Level = Field(description="Source item id.")
    content_sha256: Digest = Field(description="SHA-256 of the raw bytes.")
    adapter: str = Field(min_length=1, max_length=80, description="Adapter name.")
    adapter_version: str = Field(min_length=1, max_length=40, description="Adapter version.")
    received_at: datetime = Field(description="Intake time.")


class ResourceRef(_Frozen):
    """A person or party as a pseudonymous resource. People are never objects."""

    role: Literal["sender", "recipient", "author", "assignee", "owner", "executor", "other"] = Field(description="Role in the record.")
    token: Annotated[str, StringConstraints(pattern=r"^res-[0-9a-f]{16}$")] = Field(description="Salted pseudonym; never the raw address or name.")
    role_label: Optional[str] = Field(default=None, max_length=80, description="Business role, if known (e.g. coordinator).")


class TypedRelation(_Frozen):
    """A typed, evidenced relation from this object to another."""

    type: Level = Field(description="Relation type, e.g. blocks, reply_to, produces.")
    target_id: Ident = Field(description="Target object id.")
    evidence: str = Field(min_length=1, max_length=200, description="Field or header the relation was read from.")


class DomainObject(_Frozen):
    """A domain record after the anti-corruption layer: an object (thing), never a person."""

    schema_version: Literal["datamesh-ingest/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    object_id: Ident = Field(description="Deterministic id from platform and natural key.")
    kind: Level = Field(description="Object kind, e.g. email_message, document, work_item, process_execution.")
    title: str = Field(default="", max_length=500, description="Title or subject.")
    text: str = Field(default="", max_length=MAX_TEXT, description="Bounded extracted text.")
    fields: dict[str, Scalar] = Field(default_factory=dict, description="Flat scalar fields (at most 64).")
    relations: tuple[TypedRelation, ...] = Field(default=(), max_length=256, description="Typed relations.")
    resources: tuple[ResourceRef, ...] = Field(default=(), max_length=256, description="Pseudonymous resources.")
    occurred_at: Optional[datetime] = Field(default=None, description="Timestamp from the record itself, if any.")
    provenance: Provenance = Field(description="Source and transform.")
    epistemic_status: Literal["computed"] = Field(default="computed", description="Read from a record, not modelled.")

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.occurred_at, "occurred_at")
        if len(self.fields) > 64 or any(len(k) > 60 for k in self.fields):
            raise ValueError("fields: at most 64 flat scalars with short keys")
        return self

    def digest(self) -> str:
        """Content digest of this version. Excludes intake time, so re-ingesting identical bytes later is a no-op."""
        return hashlib.sha256(self.model_dump_json(exclude={"provenance": {"received_at"}}).encode()).hexdigest()


class Rejection(_Frozen):
    """Quarantined input. Never a partial object."""

    topic: str = Field(min_length=1, max_length=300, description="Raw topic.")
    content_sha256: Digest = Field(description="SHA-256 of the raw bytes.")
    adapter: str = Field(min_length=1, max_length=80, description="Adapter that rejected it.")
    reason: str = Field(min_length=1, max_length=500, description="Why.")
    received_at: datetime = Field(description="Intake time.")


class AdapterResult(_Frozen):
    """Objects, or a rejection; never both."""

    objects: tuple[DomainObject, ...] = Field(default=(), description="Parsed objects.")
    rejection: Optional[Rejection] = Field(default=None, description="Why the input was quarantined.")

    @model_validator(mode="after")
    def _xor(self):
        if bool(self.objects) == (self.rejection is not None):
            raise ValueError("an adapter returns objects or a rejection, exactly one")
        return self


class JsonMapping(_Frozen):
    """Declared mapping from platform JSON to a domain object. Dotted paths into the JSON body."""

    name: Level = Field(description="Mapping name.")
    kind: Level = Field(description="Object kind produced.")
    id_field: str = Field(min_length=1, max_length=120, description="Path to the natural key.")
    title_field: Optional[str] = Field(default=None, max_length=120, description="Path to the title.")
    text_fields: tuple[str, ...] = Field(default=(), description="Paths concatenated into text.")
    numeric_fields: dict[str, str] = Field(default_factory=dict, description="Domain field -> path for numeric values.")
    scalar_fields: dict[str, str] = Field(default_factory=dict, description="Domain field -> path for other scalars.")
    relation_fields: dict[str, str] = Field(default_factory=dict, description="Path -> relation type; values are source ids on the same platform.")
    occurred_at_field: Optional[str] = Field(default=None, max_length=120, description="Path to an ISO-8601 timestamp.")
    resource_fields: dict[str, str] = Field(default_factory=dict, description="Path -> resource role; values are pseudonymised.")


class IngestConfig(_Frozen):
    """Pipeline settings. The salt is configuration and is never published."""

    pseudonym_salt: str = Field(min_length=16, max_length=200, description="Salt for resource pseudonyms; keep private.")
    max_text: int = Field(default=MAX_TEXT, ge=100, le=MAX_TEXT, description="Text truncation length.")


class RingEntry(_Frozen):
    """One object version on the IngestRing."""
    offset: NonNegativeInt = Field(description="Monotonic ring offset.")
    object: DomainObject = Field(description="The domain object.")
    digest: Digest = Field(description="Object digest at append time.")


class TensorPlan(_Frozen):
    """What a consumer needs as tensors."""

    name: Level = Field(description="Plan name.")
    text_dim: int = Field(default=512, ge=16, le=65536, description="Hashed text feature width D.")
    numeric_fields: tuple[str, ...] = Field(default=(), max_length=256, description="Numeric fields, in column order.")
    relation_types: tuple[Level, ...] = Field(default=(), max_length=64, description="Relation types kept as edges, in type-index order.")
    projection: Optional["FrozenProjection"] = Field(default=None, description="Apply this frozen projection to produce positions.")

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class ConsumerSpec(_Frozen):
    """A ring consumer (GNN, ensemble, enrichment, ...) and the tensor plan it needs."""
    name: Level = Field(description="Consumer name; owns a ring cursor.")
    kinds: tuple[Level, ...] = Field(default=(), description="Object kinds read; empty reads all.")
    plan: TensorPlan = Field(description="Tensor plan.")
    batch_size: int = Field(default=256, ge=1, le=100000, description="Max entries per batch.")


PROJ_COMPONENTS_SPEC = TensorSpec(name="ingest.projection_components", dims=("component", "feature"), shape=(3, "D"),
                                  dtype="float64", description="PCA components (rows), fit once on the fit set.")
PROJ_MEAN_SPEC = TensorSpec(name="ingest.projection_mean", dims=("feature",), shape=("D",), dtype="float64",
                            description="Fit-set mean of hashed text features.")
TEXT_SPEC = TensorSpec(name="ingest.text", dims=("row", "feature"), shape=("B", "D"), dtype="float32",
                       description="Signed hashed log term frequency of title + text, L2-normalised.")
NUMERIC_SPEC = TensorSpec(name="ingest.numeric", dims=("row", "field"), shape=("B", "F"), dtype="float64",
                          description="Declared numeric fields; 0 where missing (see numeric_mask).")
NUMERIC_MASK_SPEC = TensorSpec(name="ingest.numeric_mask", dims=("row", "field"), shape=("B", "F"), dtype="bool",
                               description="True where the field was present.")
EDGE_INDEX_SPEC = TensorSpec(name="ingest.edge_index", dims=("endpoint", "edge"), shape=(2, "E"), dtype="int64", min_value=0,
                             layout="COO", description="Row 0 source, row 1 target, batch row indices.")
EDGE_TYPE_SPEC = TensorSpec(name="ingest.edge_type", dims=("edge",), shape=("E",), dtype="int64", min_value=0,
                            description="Index into plan.relation_types.")
POSITIONS_SPEC = TensorSpec(name="ingest.positions", dims=("row", "axis"), shape=("B", 3), dtype="float64",
                            description="Frozen projection of text features.")


class FrozenProjection(TensorContract):
    """PCA to 3D fit once on an explicit fit set. Applied, never refit."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {"components": PROJ_COMPONENTS_SPEC, "mean": PROJ_MEAN_SPEC}
    PRODUCED_BY: ClassVar[str] = "TensorizerPort.fit_projection"
    name: Level = Field(description="Projection name.")
    text_dim: int = Field(ge=16, description="Feature width it applies to.")
    tokenizer: str = Field(min_length=1, max_length=80, description="Tokenizer and hashing version.")
    fit_ids: tuple[Ident, ...] = Field(min_length=3, description="Object ids of the fit set.")
    explained_share: float = Field(ge=0, le=1, description="Variance share kept by the 3 components.")
    discarded_share: float = Field(ge=0, le=1, description="Variance share in the projection-null space (reported, not hidden).")
    digest: Digest = Field(description="SHA-256 of components, mean, fit ids, width and tokenizer.")
    components: TensorRef = Field(description="Ref to 3 x D components.")
    mean: TensorRef = Field(description="Ref to D mean.")

    def size_seed(self):
        return {"D": self.text_dim}


class TensorBatch(TensorContract):
    """Tensors for one consumer batch, with lineage back to raw content."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {"text": TEXT_SPEC, "numeric": NUMERIC_SPEC, "numeric_mask": NUMERIC_MASK_SPEC,
                                                "edge_index": EDGE_INDEX_SPEC, "edge_type": EDGE_TYPE_SPEC, "positions": POSITIONS_SPEC}
    PRODUCED_BY: ClassVar[str] = "TensorizerPort.build"
    consumer: Level = Field(description="Consumer name.")
    plan_digest: Digest = Field(description="Digest of the plan used.")
    projection_digest: Optional[Digest] = Field(default=None, description="Digest of the projection applied, if any.")
    offsets: tuple[NonNegativeInt, ...] = Field(description="Ring offsets, row order.")
    object_ids: tuple[Ident, ...] = Field(description="Object ids, row order.")
    content_sha256: tuple[Digest, ...] = Field(description="Raw content digest per row (lineage).")
    numeric_fields: tuple[str, ...] = Field(description="Column order of numeric.")
    relation_types: tuple[str, ...] = Field(description="Type index order of edge_type.")
    text: TensorRef = Field(description="Ref to B x D text features.")
    numeric: Optional[TensorRef] = Field(default=None, description="Ref to B x F numeric; None without numeric fields.")
    numeric_mask: Optional[TensorRef] = Field(default=None, description="Ref to B x F presence mask.")
    edge_index: Optional[TensorRef] = Field(default=None, description="Ref to 2 x E edges; None when no edge falls inside the batch.")
    edge_type: Optional[TensorRef] = Field(default=None, description="Ref to E edge types.")
    positions: Optional[TensorRef] = Field(default=None, description="Ref to B x 3 positions; None without a projection.")

    def size_seed(self):
        return {"B": len(self.object_ids)}


TensorPlan.model_rebuild()
CONTRACTS = (BlobRef, IntakeBinding, RawItem, Provenance, ResourceRef, TypedRelation, DomainObject, Rejection, AdapterResult, JsonMapping,
             IngestConfig, RingEntry, TensorPlan, ConsumerSpec, FrozenProjection, TensorBatch)
TENSOR_CONTRACTS = (FrozenProjection, TensorBatch)
