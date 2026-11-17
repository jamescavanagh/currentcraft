# Geodesic link integration and local perturbation readout

Research extension to the DataMesh gauge package, November 11, 2026.

## Goal

Use each operand's embedding to probe its local vortex/director environment, transport comparisons along the embedding manifold, and measure response to local changes. Gauges remain read-only measurements, not GNN input tensors or operational authority.

**Implemented:** shortest paths on the reliable weighted connection graph, lattice link products, multiscale transported readings, symmetric perturbations of focal node embeddings, explicit missingness and graph-stability diagnostics. Arrays remain in infrastructure, and contracts reuse the existing TensorSpec/TensorRef and TensorContract classes.

**Not implemented:** Phillips-Stone bundle reconstruction and interpolation, an analytic continuous geodesic solver, fitting a differentiable metric to arbitrary embeddings, or evaluation of the unspecified Inequality (17). The graph lengths are Euclidean chords in normalized embedding space. They approximate intrinsic geodesics only where sampling, locality and graph connectivity support that approximation. Geodesics on the base manifold and shortest interpolation paths on a gauge group are different constructions.

## Two connections, not one

The Levi-Civita connection Gamma transports tangent vectors on a metric manifold. A lattice connection transports the node director's orientation between local frames. They can be related when the field is a tangent director and the local frames consistently approximate its tangent bundle, but one is not automatically a measurement of the other.

For a continuous gauge field, one would use U_gamma = P exp(i integral_gamma A). This implementation instead estimates edge rotations from local embedding frames, then composes them along a graph path. It does not claim those discrete links are already proven samples of a specified continuous vector potential.

With the existing convention A_uv maps frame v to frame u. For path i -> ... -> j:

    U_path = product exp(i m A_uv)
    psi_i = exp(i m phi_i)
    C_ij = conjugate(psi_i) * U_path * psi_j

m=2 for an unoriented principal-axis director, m=1 for a supply-demand vector director. C_ij is invariant under independently rotating every local frame. Its magnitude is 1 per pair; the modulus of its weighted mean over neighbours measures coherence. Alternative paths can disagree when curvature is enclosed. The shortest-path tree selects one route, breaking equal-length ties by stable node-id rank. It does NOT erase path dependence or average alternate paths.

## Cylinder correction

The excerpt did not specify a metric. For an ordinary fixed-radius cylinder surface with coordinates (theta,z):

    ds^2 = R^2 dtheta^2 + dz^2

All intrinsic Christoffel symbols vanish in this chart. The cylinder is curved extrinsically but flat intrinsically. A nonzero vortex winding can still surround its noncontractible angular cycle; this does not require local Gaussian curvature.

For an explicit warped surface X(theta,z)=(R(z)cos(theta), R(z)sin(theta), z):

    g = diag(R^2, 1+R'^2)
    Gamma^theta_(theta z) = Gamma^theta_(z theta) = R'/R
    Gamma^z_(theta theta) = -R R'/(1+R'^2)
    Gamma^z_(zz) = R' R''/(1+R'^2)

All other coefficients vanish. These formulas are supplied as a metric-compatibility-tested reference helper, not secretly imposed on every embedding cloud. The full 3-D cylindrical-coordinate metric is another case again, with Gamma^r_(theta theta)=-r and Gamma^theta_(r theta)=1/r. Without the actual metric and Inequality (17), no specific two-family bound is claimed.

## Per-node information extracted

For each requested focal node and each cumulative geodesic ball:

1. Transport alignment: weighted mean Re(C_ij).
2. Transport coherence: |weighted mean C_ij|.
3. Absolute mean transported phase. Undefined when coherence <= 1e-10: stored as a documented zero placeholder; do not interpret that phase then.
4. Mean shortest-path length in median nearest-neighbour spacing units.
5. Sum of |triangle holonomy| inside the ball.
6. Sum of |triangle charge| inside the ball.

Only reliable links and valid directors participate. A ball with too few reachable neighbours is masked, not assigned a scientific zero. These are graph-dependent descriptors, not normalized curvature integrals: dense or overlapping triangles can increase the last two loads. Compare matched graph density and sampling before claiming differences.

## Local embedding perturbations

For each explicit focal node and epsilon:

- Move its embedding by +/- epsilon times its mean kNN distance, along each of its two local principal tangent axes.
- Rebuild neighbours, tangent frames, directors, connection and graph for all four perturbations.
- Recompute the focal multiscale descriptors.
- Report RMS descriptor change divided by epsilon, joint-validity mask, valid-perturbation fraction and kept-edge Jaccard.

This is a directional finite-perturbation sensitivity, not a certified derivative, intervention effect, stability theorem or recovered semantic meaning. Threshold crossings, director degeneracy and graph changes can cause jumps. Edge Jaccard is cloud-wide and may dilute small local changes. The normalized base-cloud length unit stays fixed across perturbations; no baseline normalization is fit to labels.

## Example (runs as a doctest)

>>> import sys; sys.path.insert(0, 'src')
>>> import numpy as np
>>> from app.application.gauge import GaugeRequest, GaugeNode, GaugeParams, EmbeddingSpaceRef, GeodesicProbeRequest
>>> from app.infrastructure.gauge import build_numpy_geodesic_probe, put_embeddings
>>> rng = np.random.default_rng(10)
>>> P = rng.uniform(-1, 1, (80, 2))
>>> X = np.c_[P, .15 * P[:, 0] ** 2, rng.normal(scale=.001, size=(80, 2))]
>>> probe, store = build_numpy_geodesic_probe()
>>> source = GaugeRequest(frame_id='geodesic-demo', space=EmbeddingSpaceRef(model='synthetic'),
...                       nodes=tuple(GaugeNode(id=f'n{i:03}') for i in range(80)),
...                       embeddings=put_embeddings(store, X), params=GaugeParams(k=8, director_ratio_min=1.01))
>>> result = probe.probe(GeodesicProbeRequest(source=source, focal_ids=('n020',), radii=(3., 6.), epsilon=(.01, .05)))
>>> result.descriptor.shape, result.response_rms.shape
((1, 2, 6), (1, 2, 2, 6))
>>> result.invariant_battery_passed
True
>>> store.get(result.response_valid).shape
(1, 2, 2)

## Evidence and limits

Synthetic fixture generators and controls live in tests/test_geodesic_probe.py and tests/test_gauge_numpy_adapters.py. Original run artifacts and experiment directories are excluded from this public slice.

- End-to-end descriptor and perturbation-response changes under global rotation, translation, scale x1000 and node permutation are below 1e-9 on the committed synthetic fixture.
- Supplied oracle director fields on identical flat geometry give coherence 1 for uniform alignment and approximately 0 for a symmetric swirl. This tests the readout only: it does NOT demonstrate recovering that director field from embeddings.
- A random director field ALSO has low coherence. Therefore coherence alone is not a vortex detector. Check charge/winding, scale persistence and matched random-director controls together.
- Existing principal-axis director recovery limitations remain. New probes expose the field to measurement; they do not fix the embedding-to-director bottleneck.
- No empirical node/process information gain, improved supply-demand prediction, or novelty claim has been established.

Before a process claim: use independent labels, demand-only patches, forward-time/case splits, the existing stage-preserving null and paired locality comparison. Compare global cosine, graph distance alone, direct-edge transport, geodesic transport and perturbation features with identical splits. Add shuffled-director, random-placement, flat-field, and sampling-density controls. Freeze gain criteria before held-out evaluation.

## Sources and attribution boundary

Phillips & Stone, *Lattice gauge fields, principal bundles and the calculation of topological charge* (1986): https://doi.org/10.1007/bf01211167

Akyar & Dupont, *Lattice gauge field theory and prismatic sets* (2011), discusses lattice gauge theory in the Phillips-Stone sense using parallel transport functions: https://doi.org/10.7146/math.scand.a-15159

These motivate connection/link and topological readouts. The implementation is explicitly a graph-geodesic lattice-transport prototype, not a claim to reproduce either paper or the missing Equation (17).
