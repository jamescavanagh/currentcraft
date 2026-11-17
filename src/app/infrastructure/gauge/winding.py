"""Velocity polygon winding with explicit sampling limits and optional bound-backed certification.

If ||du/ds|| <= B_e on an entire arc of length l_e, the velocity curve and its linear
endpoint interpolant differ by at most B_e*l_e/2. If that tube excludes zero, their
straight homotopy excludes zero: the polygon degree equals the continuous-field index.
This is conservative and conditional on the bound, continuity and the declared contour.
Never substitute max(endpoint Jacobian norms) for a proved whole-arc bound.
"""
from __future__ import annotations
import numpy as np
from app.application.gauge.winding import (VELOCITY_SPEC,ANGLES_SPEC,BOUND_SPEC,VelocityWindingResult)
from app.application.simulation.tensors import TensorContractError


def measure_velocity_winding(velocity,angles,radius,*,point_floor=1e-10,phase_margin=.05,
                             derivative_bound=None,bound_provenance=None):
    """Array API (infrastructure only). Uneven angles allowed, one positive complete circle traversal."""
    u=np.asarray(velocity,dtype=np.float64);phi=np.asarray(angles,dtype=np.float64)
    if u.ndim!=2 or u.shape[1]!=2 or len(u)<3 or phi.shape!=(len(u),):
        raise ValueError('need K>=3 samples, velocity[K,2], angles[K]')
    if not np.isfinite(u).all() or not np.isfinite(phi).all(): raise ValueError('finite inputs required')
    if not np.isfinite([radius,point_floor,phase_margin]).all() or radius<=0 or point_floor<0 or not 0<phase_margin<np.pi:
        raise ValueError('invalid radius or thresholds')
    gaps=np.diff(np.r_[phi,phi[0]+2*np.pi])
    if not (gaps>0).all(): raise ValueError('angles strictly increasing, span <2pi, no repeated endpoint')
    speed=np.linalg.norm(u,axis=1);v=np.roll(u,-1,axis=0);d=v-u;dd=np.sum(d*d,axis=1)
    t=np.clip(np.divide(-np.sum(u*d,axis=1),dd,out=np.zeros(len(u)),where=dd>0),0,1)
    chord=np.linalg.norm(u+t[:,None]*d,axis=1)
    theta=np.arctan2(u[:,1],u[:,0]);delta=np.angle(np.exp(1j*(np.roll(theta,-1)-theta)))
    raw=float(delta.sum()/(2*np.pi));nearest=int(round(raw));residual=abs(raw-nearest)
    reasons=[]
    if np.min(speed)<=point_floor: reasons.append('sampled_stagnation_or_below_noise')
    if np.min(chord)<=point_floor: reasons.append('velocity_chord_near_zero')
    if np.max(abs(delta))>=np.pi-phase_margin: reasons.append('phase_jump_margin_failed')
    if residual>1e-8: reasons.append('noninteger_polygon_sum')
    polygon_ok=not reasons
    clear=None;certified=False
    if derivative_bound is not None:
        B=np.asarray(derivative_bound,dtype=np.float64)
        if B.shape!=(len(u),) or not np.isfinite(B).all() or (B<0).any(): raise ValueError('finite nonnegative K whole-segment bounds required')
        if not bound_provenance: raise ValueError('bound provenance required')
        clear=float(np.min(chord-B*radius*gaps/2))
        certified=polygon_ok and clear>point_floor
        if not certified: reasons.append('whole_segment_clearance_not_established')
    else:
        if bound_provenance is not None: raise ValueError('provenance requires bounds')
        reasons.append('continuous_aliasing_unresolved_no_bound')
    status='certified' if certified else 'sampled_only' if polygon_ok else 'invalid'
    return VelocityWindingResult(status=status,sampled_index=nearest if polygon_ok else None,
        certified_index=nearest if certified else None,sampled_valid=polygon_ok,winding_valid=certified,
        refinement_recommended=not certified,reasons=tuple(reasons),minimum_speed=float(min(speed)),
        minimum_chord_distance=float(min(chord)),maximum_phase_step=float(max(abs(delta))),integer_residual=residual,
        minimum_certified_clearance=clear,bound_provenance=bound_provenance)

class NumpyVelocityWindingAdapter:
    """TensorRef port adapter; does not couple validity to radial leakage or gradient energy."""
    def __init__(self,store): self.store=store
    def measure(self,request):
        refs=[request.velocity,request.angles]+([request.derivative_bound] if request.derivative_bound is not None else [])
        if any(not self.store.contains(r) for r in refs): raise TensorContractError('winding refs not in shared store')
        return measure_velocity_winding(self.store.get(request.velocity),self.store.get(request.angles),request.radius,
            point_floor=request.point_floor,phase_margin=request.phase_margin,
            derivative_bound=self.store.get(request.derivative_bound) if request.derivative_bound is not None else None,
            bound_provenance=request.bound_provenance)


def put_velocity_winding_inputs(store,velocity,angles,derivative_bound=None):
    """Explicit infrastructure conversion to float64 and shared TensorRef storage."""
    refs=dict(velocity=store.put(VELOCITY_SPEC,np.array(velocity,dtype=np.float64,copy=True),producer='winding-input'),
              angles=store.put(ANGLES_SPEC,np.array(angles,dtype=np.float64,copy=True),producer='winding-input'))
    if derivative_bound is not None:
        refs['derivative_bound']=store.put(BOUND_SPEC,np.array(derivative_bound,dtype=np.float64,copy=True),producer='winding-input')
    return refs
