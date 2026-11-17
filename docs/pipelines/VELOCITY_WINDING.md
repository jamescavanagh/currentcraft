# Velocity winding: sampled polygon versus continuous contour

This is an additive refactor of the proposed circular velocity-index calculation. It deliberately does NOT replace lattice director defect/winding in lattice_kernels.py: that is a different observable, potentially half-integer and connection-dependent. Velocity winding uses the Cartesian velocity direction along a specified circle. No radial leakage or eta mask gates its result.

## Output states

- invalid: a sampled point, velocity-space chord, phase-margin or integer-sum guard fails. sampled_index=None, certified_index=None.
- sampled_only: sampled polygon is safe; sampled_index is its integer degree. Continuous-field winding is unresolved; winding_valid=False.
- certified: supplied whole-segment bounds exclude zeros in a homotopy from the continuous velocity curve to its polygon. winding_valid=True, certified_index available, CONDITIONAL on those bounds and continuity being correct.

The library records bound provenance but cannot verify that a caller's bound is truthful or rigorous. Endpoint Jacobians alone are not sufficient bounds. No automatic smooth-field certification or adaptive resampling is claimed.

## Guard construction

Angles must be strictly increasing through one circle, without a duplicated closing endpoint; unequal angular spacing is supported.

For each velocity-space segment a -> b, t=clip(-a dot (b-a) / ||b-a||^2,0,1), with t=0 for equal endpoints. Require ||a+t(b-a)|| > point_floor. Also require minimum sampled speed > point_floor, |wrapped phase step| < pi-phase_margin, and an integer phase-sum residual <1e-8. Thresholds are in their declared units; absolute noise floors affect small-amplitude validity.

To certify the continuous field, supply B_e >= sup_arc ||du/ds||, with arc length l_e = r delta_phi_e. For fraction t along an arc, Lipschitz continuity implies deviation from the linear interpolant <=2 B_e l_e t(1-t)<= B_e l_e/2. Require every polygon chord's distance from zero minus B_e l_e/2 > point_floor. Then the straight homotopy avoids zero, preserving winding. This sufficient test may reject valid contours conservatively.

Safe endpoints and small wrapped phase steps alone do not certify winding. In the 64-turn control, 64 samples look constant; 4096 samples plus the analytic derivative bound certify +64.

Clockwise and counterclockwise solid rotation both have velocity index +1 on a counterclockwise spatial contour. Index is not circulation sign. Dilation also has index +1. A saddle has index -1. Use the separate kinematic/circulation/leakage readings for interpretation; winding is not an orbit-attraction test and is observer-dependent under changes to the velocity reference frame.

## Array usage (infrastructure)

```python
from app.infrastructure.gauge import measure_velocity_winding
result = measure_velocity_winding(velocity, phi, radius)
# result.status == 'sampled_only' if polygon safe but no whole-segment bound supplied
# result.sampled_index is never advertised as a continuous-field certificate
```

## Shared TensorRef usage

```python
from app.application.gauge import VelocityWindingRequest
from app.infrastructure.gauge import NumpyVelocityWindingAdapter, put_velocity_winding_inputs
refs = put_velocity_winding_inputs(store, velocity, phi, derivative_bound)
request = VelocityWindingRequest(**refs, radius=radius,
    bound_provenance='analytic whole-arc bound, with derivation recorded in source manifest')
result = NumpyVelocityWindingAdapter(store).measure(request)
```

Application contracts are array-free. Numerical calculations live in infrastructure. Existing TensorSpec, TensorRef and shared numpy store are reused. Generated contracts include both new models.

## Integration boundary

The old geodesic GaugeLoop winding continues to mean connection-corrected director winding. This new API handles the proposed ring-velocity winding. Call it with velocities sampled from numpy_kernels.field on the same declared circle. A BufferRingResult radius alone does not supply a continuous-field derivative bound or establish an actual periodic orbit. No automatic bridge into BufferRingResult was added; existing contracts and callers remain compatible.

## Tests

12 new tests cover rotation both signs, source/saddle indices, uniform translation, shear with on-grid and between-grid stagnation, sampled-only status, 64-turn aliasing and refinement, zero field, non-equivalence of chord and phase guards, uneven angles and duplicate-endpoint rejection, shared-store adapter, and field documentation.
