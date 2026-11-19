# Approved domain validation boundary

James confirmed Pydantic v2 in the domain on November 17, 2026. This supersedes
the earlier implementation work order's prohibition on Pydantic/domain framework
imports. Do not convert the existing domain models to dataclasses to satisfy
that obsolete restriction. No speed benchmark is claimed by this decision.

Domain construction, validators and JSON Schema hooks are deterministic and
perform no filesystem/network access, database writes, broker dispatch or
automatic permission grants. HTTP frameworks and interface adapters stay in
interfaces; file loading, drivers and runtime composition stay in infrastructure.
NumPy/PyTorch runtime code stays in infrastructure; enterprise entities contain
no arrays. Existing TensorSpec/TensorRef contracts are retained at application
boundaries. Existing ProcessExecution, ObjectIncidence, CapabilityBinding and
AuthorityRef remain canonical. Resources execute; people are never operands.

Pydantic is a model validation mechanism, not an authority source. JSON Schema
conditions express local wire constraints; temporal ordering, reference support,
typed context consistency and trusted reference selection require further
validation. The [validation matrix](../domain/V1_REVIEW_CORRECTIONS.md#schema--validation-matrix)
specifies these separate guarantees. Undefined operational policy denies release.

Application trust is explicit: capture receives a loader-verified selection from
trusted composition independently of the payload. Structural hydration alone is
not trusted ingestion. Historical restore reports the recorded verification
receipt and does not assert fresh verification of unavailable source bytes.
