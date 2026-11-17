# Gauge pipeline: operand gauges from reduced embeddings

Status: research instrument (`embedding_geometry`). Not an operational forecast. The `supply_demand` director is **proposed and untested on bench data**.

## What it measures

Operands get properties (gauges) that compare local and global conditions. The embedding cloud is treated as a field (the supersaturated-fluid picture, used here as a field, not a flow):

| DataMesh reading | Gauge-slice object | Gauge status |
| --- | --- | --- |
| Local frame of an operand | tangent plane `O_i` of its kNN patch | gauge choice |
| Spin / orientation of an operand | `director` angle in that frame | gauge-dependent |
| Vector potential between operands | `edge_connection` A_ij (rotation frame j to frame i) | gauge-dependent |
| Relationship reading | `edge_link` = phi_j + A_ij - phi_i | invariant |
| Field strength / curvature | `triangle_holonomy` | invariant |
| Vortex | `triangle_charge` (half-integer for axis directors) | invariant |
| Handedness break | `triangle_z2` = -1 (frames cannot be oriented around the loop) | invariant |
| Winding around a hole or subsystem | `GaugeResult.loops` | invariant |
| Local vs global condition | `node_gauges` (density ratio, supersaturated, coherence vs global, ...) | invariant |

Only invariants are measurements. A reading that changes when one node's frame is rotated is bookkeeping, not signal. Gauges are read-only: they are not GNN inputs (the GNN takes embeddings + typed relations).

## Layering

```
application/gauge        Pydantic contracts, ports, GaugeService          (no numpy)
   reuses  application/simulation: TensorContract, TensorSpec, TensorRef, NodeRole, TensorStorePort
infrastructure/gauge     lattice kernels, adapters, build_numpy_gauge     (numpy only, no scipy)
   reuses  infrastructure/tensors: InMemoryNumpyTensorStore (one store for both slices)
```

## Run it

```python
>>> import sys; sys.path.insert(0, "src")
>>> import numpy as np
>>> from app.application.gauge import (EmbeddingSpaceRef, GaugeCheckRequest, GaugeNode, GaugeRequest,
...                                    ParticipationEdge, ScoredPair, StageNullRequest)
>>> from app.infrastructure.tensors import build_numpy_simulation
>>> from app.infrastructure.gauge import build_numpy_gauge, put_embeddings
>>> _, store, _ = build_numpy_simulation()          # one store shared by both slices
>>> gauge, _ = build_numpy_gauge(store)
>>> rng = np.random.default_rng(0)                   # streak texture on a gently curved sheet in 8-D
>>> P = np.vstack([np.c_[np.arange(-1, 1, 0.025), np.full(80, y)] for y in np.linspace(-1, 1, 10)])
>>> Q, _ = np.linalg.qr(rng.normal(size=(8, 8)))
>>> Z = np.c_[P, 0.3 * (P[:, 0] ** 2 - 0.5 * P[:, 1] ** 2), rng.normal(scale=0.003, size=(len(P), 5))]
>>> ref = put_embeddings(store, Z @ Q)
>>> req = GaugeRequest(frame_id="demo-streaks", space=EmbeddingSpaceRef(model="synthetic", reduction="none"),
...                    nodes=tuple(GaugeNode(id=f"n{i:04d}") for i in range(len(P))), embeddings=ref)
>>> result, check = gauge.reduce_checked(req, seed=1)   # refuses to return readings that fail invariance
>>> check.passed, [c.transform for c in check.checks]
(True, ['frame_rotation', 'frame_flip', 'global_rotation', 'translation', 'scale', 'permutation'])
>>> result.node_feature_names[:4]
('planarity', 'anisotropy', 'log_density_ratio', 'supersaturated')
>>> store.get(result.node_gauges).shape == (len(P), len(result.node_feature_names))
True
>>> GaugeRequest.model_validate(req.model_dump()).digest() == result.request_digest
True

```

Participation null (stage-preserving curveball rewiring plus a paired bootstrap of local vs global AUC):

```python
>>> edges = tuple(ParticipationEdge(resource_id=f"r{r}", process_id=f"{s}-p{r // 4}", stage=s)
...               for s in ("design", "ordering") for r in range(24))
>>> pairs = tuple(ScoredPair(a=f"r{a}", b=f"r{b}", stage=s, local_score=-abs(a // 4 - b // 4) + 0.1 * rng.normal(),
...                          global_score=rng.normal()) for s in ("design", "ordering")
...               for a in range(24) for b in range(a + 1, 24))
>>> null = gauge.participation_null(StageNullRequest(frame_id="demo-null", participation=edges, pairs=pairs,
...                                                  n_rewires=50, n_bootstrap=100, seed=0))
>>> null.verdict, null.auc_local > 0.9, null.p_local < 0.05
('local_beats_global', True, True)

```

## Protocol rules baked in

- `GaugeService.reduce_checked` runs the invariance battery (per-node frame rotation and reflection, global rotation, translation, scale x1000, node permutation) before returning any reading.
- Edges and triangles are oriented by node id, frames by BFS plus `net_holonomy_positive` per component, so signs do not depend on row order or SVD sign choices.
- Rewiring never crosses stages and preserves every resource and process degree per stage. It tests the local score against stage-matched chance only. Locality (local beats global) is tested by the paired, stage-stratified bootstrap, never by the rewiring null.
- Score pairs on demand-only patches (keep the pair's own training participants out of the local patch); otherwise the local score leaks the label.
- The default `gain_bar` 0.05 reached about 37% power in v0.2 simulations: recalibrate before using it as a pass bar.

## Known limits

- Director recovery on streamline textures was weak in the v0.2 prototype (uniform 5/8, radial 6/8, swirl 1/8, annulus 3/8). Uniform textures still show spurious defects (nonzero net charge) in this build. Treat charges as candidates.
- `supply_demand` gives integer windings around a supply/demand boundary in synthetic annuli; it has not been run on bench records.
- Exact kNN is O(N^2) in chunks (fine to a few thousand nodes). Distance ties can break differently under permutation.
- Holonomy is wrapped to (-pi, pi]; loops enclosing more than pi of curvature are ambiguous by construction.
