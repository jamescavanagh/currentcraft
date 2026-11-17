"""Planar velocity-index contracts, separate from lattice director winding and radial leakage."""
from __future__ import annotations
from typing import Literal, Protocol, runtime_checkable
from pydantic import Field, model_validator
from app.application.simulation.tensors import TensorRef, TensorSpec
from .contracts import _Frozen, Finite

VELOCITY_SPEC=TensorSpec(name='winding.velocity',dims=('sample','component'),shape=('K',2),dtype='float64',description='Cartesian velocity on one ordered circular contour, no repeated closing endpoint.')
ANGLES_SPEC=TensorSpec(name='winding.angles',dims=('sample',),shape=('K',),dtype='float64',unit='rad',description='Strictly increasing angles spanning less than 2 pi; closing segment wraps to phi[0]+2 pi.')
BOUND_SPEC=TensorSpec(name='winding.derivative_bound',dims=('sample',),shape=('K',),dtype='float64',min_value=0,description='Caller-supplied upper bound on ||du/ds|| on EACH ENTIRE contour segment, including closing segment. Not endpoint Jacobian estimates.')

class VelocityWindingRequest(_Frozen):
    velocity: TensorRef=Field(description='K x 2 Cartesian sampled velocity, VELOCITY_SPEC.')
    angles: TensorRef=Field(description='K ordered circle angles, ANGLES_SPEC.')
    radius: Finite=Field(gt=0,description='Fixed circle radius; used to convert angular gaps into arc lengths.')
    point_floor: Finite=Field(default=1e-10,ge=0,description='Absolute velocity-space zero exclusion threshold; choose in velocity units.')
    phase_margin: Finite=Field(default=0.05,gt=0,lt=3.141592653589793,description='Require every wrapped endpoint phase increment < pi - margin.')
    derivative_bound: TensorRef | None=Field(default=None,description='Optional BOUND_SPEC: rigorous segment-wide ||du/ds|| bounds from the caller.')
    bound_provenance: str | None=Field(default=None,min_length=1,max_length=500,description='How whole-segment derivative bounds were established; required when supplied.')

    @model_validator(mode='after')
    def rules(self):
        if self.velocity.spec!=VELOCITY_SPEC or self.angles.spec!=ANGLES_SPEC:
            raise ValueError('velocity/angles must use winding specs')
        k=self.velocity.shape[0]
        if k<3 or self.angles.shape!=(k,): raise ValueError('need >=3 matching samples')
        if self.derivative_bound is not None:
            if self.derivative_bound.spec!=BOUND_SPEC or self.derivative_bound.shape!=(k,):
                raise ValueError('bounds must match K and BOUND_SPEC')
            if self.bound_provenance is None: raise ValueError('bound provenance required')
        elif self.bound_provenance is not None: raise ValueError('provenance without bounds')
        return self

class VelocityWindingResult(_Frozen):
    """Index of a sampled velocity polygon and optional conditional certificate for the continuous contour."""
    status: Literal['invalid','sampled_only','certified']=Field(description='certified is conditional on supplied whole-segment bounds being correct, not inferred from finite samples.')
    sampled_index: int | None=Field(description='Integer degree of safe velocity polygon; None if a polygon guard failed. Not by itself a continuous-field index.')
    certified_index: int | None=Field(description='Continuous-field index only when homotopy guard passes under supplied bounds.')
    sampled_valid: bool=Field(description='Sampled points, chords, phase margin and integer residual pass.')
    winding_valid: bool=Field(description='True ONLY for certified continuous-field winding; sampled-only is not certified.')
    refinement_recommended: bool=Field(description='True for unresolved bounds or undersampling; resampling alone does not create a certificate.')
    reasons: tuple[str,...]=Field(description='Diagnostics, including unresolved aliasing or failing bound.')
    minimum_speed: Finite=Field(description='Minimum sampled speed.')
    minimum_chord_distance: Finite=Field(description='Minimum distance to origin across velocity-space polygon segments.')
    maximum_phase_step: Finite=Field(description='Largest absolute wrapped phase increment.')
    integer_residual: Finite=Field(description='Absolute difference between sampled phase sum / 2 pi and nearest integer.')
    minimum_certified_clearance: Finite | None=Field(description='Minimum chord distance minus B_e * arc_length_e / 2; must exceed point_floor.')
    bound_provenance: str | None=Field(description='Caller-supplied bound provenance, copied without independent verification.')

@runtime_checkable
class VelocityWindingPort(Protocol):
    def measure(self,request: VelocityWindingRequest)->VelocityWindingResult: ...

CONTRACTS=(VelocityWindingRequest,VelocityWindingResult)
