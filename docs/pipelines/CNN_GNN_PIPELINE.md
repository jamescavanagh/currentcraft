# CNN → GNN pipeline: documentation-driven design

This page is the design source for the simulation pipeline. Code follows it, in this order:
**doc section → contract (with field descriptions) → generated reference → port → adapter → tests.**
The generated reference is [docs/contracts/SIMULATION_CONTRACTS.md](../contracts/SIMULATION_CONTRACTS.md); CI fails if it is stale,
if any contract field lacks a description, or if numpy leaks out of infrastructure. The examples on this page run as doctests.

Status: stages 1 to 4 are implemented with numpy adapters. Stages 5 and 6 are **ports only** (no model, nothing trained).
All results are `embedding_geometry`: a procedural vortex field over embedded records, not CFD and not an operational forecast.

## Layering

```text
domain/                         untouched (stdlib prototype; Body = Resource/Process/Operand)
application/simulation/         Pydantic contracts, TensorSpec/TensorRef, ports (Protocols), use cases   <- no numpy
infrastructure/tensors/         numpy store, ValidatedArray, kernels, adapters implementing the ports     <- numpy lives here
```

- Contracts never hold arrays. They hold `TensorRef`: spec (name, axis names, symbolic shape, dtype, unit, bounds), store key,
  concrete shape and SHA-256. Symbols (`N`, `S`, `G`, `E`) must bind to one size per contract instance.
- Arrays are validated once, at the store (`ValidatedArray`): dtype must match exactly (no silent casts), shape must bind,
  floats must be finite, bounds are enforced.
- Transforms happen through ports: `TensorTransformPort` for tensor ops, `reflect_nodes()` for geometry
  (a reflection must also negate strengths, or the field is impossible).

## Stages

| # | Stage | Port | In → out | Key tensors | Status |
| --- | --- | --- | --- | --- | --- |
| 0 | Records → nodes | (embedding pipeline) | records → `InteractionNode` | n/a | outside this package |
| 1 | Node interactions | `NodeInteractionPort` | `NodeInteractionRequest` → `NodeInteractionResult` | coupling (N, N), node_velocity (S, N, 2), field (S, 5, G, G) | numpy adapter |
| 2 | Buffer rings | `BufferRingPort` | `BufferRingRequest` → `BufferRingResult` | basins (G, G), occupancy_history (R, T), tracers_final (P, 2) | numpy adapter |
| 3 | CNN sample | `CnnSamplePort` | `CnnSampleRequest` → `CnnSample` | x (S, 5, G, G), heat (S, 2, G, G), saddle_count (S) | numpy adapter |
| 4 | GNN sample | `GraphTensorPort` | `GraphSampleRequest` → `GraphSample` | x (N, F), edge_index (2, E) int64, edge_attr (E, D) | numpy adapter |
| 5 | CNN-1 → CNN-2 encoder | `CnnEncoderPort` | `CnnSample` → motif maps + frame embedding | to be specified here first | planned |
| 6 | GNN encoder | `GnnEncoderPort` | `GraphSample` (+ frame embedding) → node / graph outputs | to be specified here first | planned |
| 7 | Evaluation | n/a | experiment matrix arms A0 to A7 | see `models/experiments/cnn_cnn_matrix/` | design |

Conventions: CNN tensors are slice-major `SCHW` (CNN-2 convolves along `S`; a batch becomes `[B, C, S, H, W]` for Conv3d-style
models). GNN tensors follow PyTorch Geometric: `x [N, F]`, `edge_index [2, E]` int64 COO, `edge_attr [E, D]`. Edge `j → i`
carries `k_ij`, the rotation node j induces at node i.

**Buffer rings** have two meanings, both kept explicit: the *ring* is the closed orbit tracers settle onto around a core
(`radius`); the *buffer* is how many tracers it holds (`occupancy`), with a circular history of the last T records
(`occupancy_history`, oldest first). Mapping a ring to the domain `Buffer` (capacity / occupied / reserved) is **not approved**;
see the domain-semantics design work (tracked privately).

## Worked example (runs as a doctest)

>>> import sys; sys.path.insert(0, "src")
>>> from app.application.simulation import FramePipelineRequest, InflowSweep, InteractionNode, FieldGrid, TransformSpec
>>> from app.infrastructure.tensors import build_numpy_simulation
>>> service, store, transforms = build_numpy_simulation()
>>> nodes = (InteractionNode(id="gate", role="process", x=-0.5, y=0.0, strength=-0.3),
...          InteractionNode(id="ktc", role="operand", x=-0.1, y=0.25, strength=-0.25),
...          InteractionNode(id="service", role="operand", x=-0.15, y=-0.3, strength=-0.25),
...          InteractionNode(id="intake", role="resource", x=0.6, y=0.0, strength=0.3))
>>> req = FramePipelineRequest(frame_id="doc-demo", nodes=nodes, inflow=InflowSweep.grid(0, 0.3, 0.05),
...                            ring_inflow=0.07, grid=FieldGrid(size=16), ring_steps=300)
>>> result = service.run_frame(req)
>>> result.interactions.saddle_curve
(1, 1, 1, 1, 1, 1, 1)
>>> result.cnn.x.shape, result.cnn.x.spec.layout
((7, 5, 16, 16), 'SCHW')
>>> result.graph.x.shape, result.graph.edge_index.shape, result.graph.edge_index.spec.dtype
((4, 13), (2, 12), 'int64')
>>> "numpy" in type(result.graph.x).__module__   # contracts hold refs, not arrays
False
>>> transforms.apply(TransformSpec(op="select_slices", indices=(1, 2)), result.cnn.x).shape
(2, 5, 16, 16)
>>> service.run_reflected(req).interactions.saddle_curve == result.interactions.saddle_curve
True

## Adding stage 5 or 6 (the documentation-driven loop)

1. Write the stage section here: purpose, inputs, outputs, every tensor (axes, shape symbols, dtype, unit, meaning), acceptance tests.
2. Add the output contract to `contracts.py` as a `TensorContract` with a `TENSORS` registry and a description on every field.
3. Run `python3 scripts/gen_contract_docs.py`; review the generated diff like code.
4. Keep the port (`CnnEncoderPort` / `GnnEncoderPort`) signature array-free; implement the adapter under `infrastructure/`.
5. Add tests: contract validation, adapter parity against an oracle or fixture, and the layering test stays green.
6. Gate on the experiment matrix: if the encoder can't beat the exact-topology baseline on held-out salts, stop.

## Open decisions (not settled by this code)

- Pydantic in the domain vs the stdlib prototype: these contracts sit in **application** to avoid forcing that choice (domain-semantics design work, tracked privately).
- `NodeRole` mirrors the prototype's `Body`; unify once imports are standardised.
- API transport: refs travel as JSON; array payloads need a separate download route and a size policy (Validate the FastAPI simulation contract (internal reference omitted)).
- Persisted tensor store (npz / object storage) and retention; the in-memory store is for tests and notebooks.

## Related work

Primary: Validate the FastAPI simulation contract (internal reference omitted). Related: Integrate and harden the no-ports DataMesh domain prototype (internal reference omitted), Implement model baselines and evaluate the experimental fluid pipeline (internal reference omitted), Validate the interactive three-body and flow visualization (internal reference omitted).
