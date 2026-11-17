"""Graph-geodesic lattice transport, not a claimed reproduction of Phillips-Stone interpolation."""
from __future__ import annotations
import hashlib
from typing import ClassVar, Literal, Protocol, runtime_checkable
from pydantic import Field, model_validator
from app.application.simulation.contracts import TensorContract
from app.application.simulation.tensors import TensorRef, TensorSpec, TensorContractError
from app.application.simulation.ports import TensorStorePort
from .contracts import _Frozen, Finite, NodeId, GaugeRequest, Digest

FEATURES = ("transport_alignment", "transport_coherence", "transport_phase_abs", "mean_path_length",
            "curvature_load", "defect_load")

class GeodesicProbeRequest(_Frozen):
    """Read node interactions over shortest graph paths; perturb a focal node's own embedding locally."""
    schema_version: Literal["datamesh-geodesic/v1"] = Field(default="datamesh-geodesic/v1", description="Version of this additive probe contract.")
    source: GaugeRequest = Field(description="Existing gauge request, including embedding refs and provenance.")
    focal_ids: tuple[NodeId, ...] = Field(min_length=1, max_length=32, description="Focal operands to probe, explicit rather than auto-selected on labels.")
    radii: tuple[Finite, ...] = Field(default=(1.5, 3.0, 5.0), min_length=1, max_length=12, description="Geodesic ball radii in units of median nearest-neighbour distance; cumulative balls, excluding focal node.")
    epsilon: tuple[Finite, ...] = Field(default=(0.01, 0.05), min_length=1, max_length=8, description="Embedding displacement as fraction of focal mean kNN distance. Each local tangent axis is tested with both signs.")
    minimum_neighbors: int = Field(default=3, ge=1, description="Minimum reachable neighbours for a valid ball descriptor.")
    check_invariance: bool = Field(default=True, description="Refuse base reduction when the existing gauge battery fails; never a predictive validation.")

    @model_validator(mode="after")
    def rules(self):
        ids = {n.id for n in self.source.nodes}
        if len(set(self.focal_ids)) != len(self.focal_ids) or not set(self.focal_ids) <= ids:
            raise ValueError("focal ids must be unique and belong to source.nodes")
        for name in ("radii", "epsilon"):
            v = getattr(self, name)
            if any(x <= 0 for x in v) or any(b <= a for a,b in zip(v,v[1:])):
                raise ValueError(f"{name} must be positive and strictly increasing")
        return self

    def digest(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def spec(name, dims, shape, dtype, description):
    return TensorSpec(name="geodesic."+name, dims=dims, shape=shape, dtype=dtype, description=description)

class GeodesicProbeResult(TensorContract):
    """Multiscale transported readings and local perturbation response, with missingness and graph changes explicit."""
    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "descriptor": spec("descriptor", ("focal","radius","feature"), ("P","S",6), "float64", "FEATURES: mean cos transported director; modulus of mean phase; absolute mean phase (placeholder 0 if coherence <= 1e-10, then undefined); mean distance/spacing; incident |holonomy|; incident |charge|. First four summarize geodesic ball, last two its triangles."),
        "valid": spec("valid", ("focal","radius"), ("P","S"), "bool", "Ball has a valid focal node and enough reachable neighbours; otherwise descriptor zero is a placeholder, not measured zero."),
        "neighbor_count": spec("neighbor_count", ("focal","radius"), ("P","S"), "int64", "Reachable neighbors within each radius, excluding focal node."),
        "response_rms": spec("response_rms", ("focal","epsilon","radius","feature"), ("P","H","S",6), "float64", "RMS of descriptor changes divided by epsilon over + and - displacements along both tangent axes, only where base and every perturbed reading are valid."),
        "response_valid": spec("response_valid", ("focal","epsilon","radius"), ("P","H","S"), "bool", "Every symmetric tangent perturbation and base have a valid reading. False means unmeasurable, not no response."),
        "edge_jaccard": spec("edge_jaccard", ("focal","epsilon"), ("P","H"), "float64", "Mean kept-edge intersection/union versus base after perturbations; graph instability diagnostic."),
        "valid_fraction": spec("valid_fraction", ("focal","epsilon","radius"), ("P","H","S"), "float64", "Fraction of four perturbations with valid ball descriptors."),
    }
    PRODUCED_BY: ClassVar[str] = "GeodesicProbePort"
    schema_version: Literal["datamesh-geodesic/v1"] = Field(default="datamesh-geodesic/v1", description="Probe contract version.")
    result_kind: Literal["embedding_geometry"] = Field(default="embedding_geometry", description="Research readout, never an operational forecast or recovered semantic truth.")
    request_digest: Digest = Field(description="Digest of complete probe request.")
    embeddings_sha256: Digest = Field(description="Input embedding digest.")
    focal_ids: tuple[NodeId, ...] = Field(description="P: focal row order.")
    radii: tuple[Finite, ...] = Field(description="S: radii used.")
    epsilon: tuple[Finite, ...] = Field(description="H: local perturbation amplitudes.")
    feature_names: tuple[str, ...] = Field(default=FEATURES, description="Last axis of descriptor and response_rms.")
    invariant_battery_passed: bool | None = Field(description="True if base gauge battery passed, None if explicitly disabled.")
    descriptor: TensorRef = Field(description="Ref to P x S x 6 readings.")
    valid: TensorRef = Field(description="Ref to P x S mask.")
    neighbor_count: TensorRef = Field(description="Ref to P x S neighbor counts.")
    response_rms: TensorRef = Field(description="Ref to P x H x S x 6 sensitivity readings.")
    response_valid: TensorRef = Field(description="Ref to P x H x S joint-validity mask.")
    edge_jaccard: TensorRef = Field(description="Ref to P x H graph stability diagnostic.")
    valid_fraction: TensorRef = Field(description="Ref to P x H x S valid-perturbation fraction.")

    def size_seed(self):
        return {"P":len(self.focal_ids),"S":len(self.radii),"H":len(self.epsilon)}

@runtime_checkable
class GeodesicProbePort(Protocol):
    def probe(self, request: GeodesicProbeRequest) -> GeodesicProbeResult: ...

class GeodesicProbeService:
    def __init__(self, store: TensorStorePort, adapter: GeodesicProbePort):
        self.store, self.adapter = store, adapter
    def probe(self, request: GeodesicProbeRequest) -> GeodesicProbeResult:
        if not self.store.contains(request.source.embeddings):
            raise TensorContractError("probe embeddings not in shared store")
        r = self.adapter.probe(request)
        if r.request_digest != request.digest() or r.embeddings_sha256 != request.source.embeddings.sha256:
            raise TensorContractError("probe provenance mismatch")
        if any(not self.store.contains(ref) for ref in r.tensor_refs().values()):
            raise TensorContractError("probe output refs not in shared store")
        return r

CONTRACTS = (GeodesicProbeRequest, GeodesicProbeResult)
TENSOR_CONTRACTS = (GeodesicProbeResult,)
