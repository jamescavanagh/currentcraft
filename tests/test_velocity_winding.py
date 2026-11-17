import unittest,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from app.application.gauge.winding import VelocityWindingRequest,CONTRACTS
from app.infrastructure.gauge.winding import measure_velocity_winding as measure,NumpyVelocityWindingAdapter,put_velocity_winding_inputs
from app.infrastructure.gauge import build_numpy_gauge

class Winding(unittest.TestCase):
    def grid(self,n=128,offset=0): return 2*np.pi*(np.arange(n)+offset)/n
    def test_rotation_both_signs_index_positive(self):
        p=self.grid()
        for spin in (-1,1):
            u=spin*np.c_[-np.sin(p),np.cos(p)]
            r=measure(u,p,1,derivative_bound=np.ones(len(p)),bound_provenance='analytic ||du/ds||=1')
            self.assertEqual((r.status,r.certified_index),('certified',1))
    def test_saddle_and_dilation(self):
        p=self.grid()
        for sign,index in [(-1,-1),(1,1)]:
            r=measure(np.c_[np.cos(p),sign*np.sin(p)],p,1,derivative_bound=np.ones(len(p)),bound_provenance='analytic bound 1')
            self.assertEqual(r.certified_index,index)
    def test_translation(self):
        p=self.grid();r=measure(np.tile([1.,0.],(len(p),1)),p,1,derivative_bound=np.zeros(len(p)),bound_provenance='constant field')
        self.assertEqual(r.certified_index,0)
    def test_shear_sampled_and_unsampled_stagnation(self):
        for off in (0,.5):
            p=self.grid(offset=off);r=measure(np.c_[np.sin(p),np.zeros(len(p))],p,1)
            self.assertEqual(r.status,'invalid');self.assertIsNone(r.sampled_index);self.assertFalse(r.winding_valid)
    def test_safe_samples_not_certificate(self):
        p=self.grid();r=measure(np.c_[np.cos(p),np.sin(p)],p,1)
        self.assertEqual((r.status,r.sampled_index,r.certified_index),('sampled_only',1,None))
    def test_aliased_64_turn_field(self):
        p=self.grid(64);u=np.c_[np.cos(64*p),np.sin(64*p)]
        r=measure(u,p,1)
        self.assertEqual((r.status,r.sampled_index),('sampled_only',0))
        r=measure(u,p,1,derivative_bound=np.full(len(p),64.),bound_provenance='true analytic 64-turn derivative bound')
        self.assertFalse(r.winding_valid);self.assertLess(r.minimum_certified_clearance,0)
    def test_refinement_resolves_known_turn_field_with_bound(self):
        p=self.grid(4096);u=np.c_[np.cos(64*p),np.sin(64*p)]
        r=measure(u,p,1,derivative_bound=np.full(len(p),64.),bound_provenance='analytic bound 64')
        self.assertEqual(r.certified_index,64)
    def test_zero_field_invalid(self):
        p=self.grid();r=measure(np.zeros((len(p),2)),p,1)
        self.assertIsNone(r.sampled_index)
    def test_chord_floor_not_equivalent_to_phase_margin(self):
        # All endpoint speeds exceed floor, angle margin passes, but a small near-zero chord fails.
        p=np.array([0.,2.,4.]);a=np.deg2rad(170)
        u=.0011*np.array([[1.,0.],[np.cos(a),np.sin(a)],[1.,0.]])
        r=measure(u,p,1,point_floor=.001)
        self.assertGreater(r.minimum_speed,.001);self.assertLess(r.maximum_phase_step,np.pi-.05)
        self.assertIn('velocity_chord_near_zero',r.reasons)
    def test_unequal_angles_and_endpoint_validation(self):
        p=self.grid();p[1:-1]+=.001*np.sin(p[1:-1])
        r=measure(np.c_[np.cos(p),np.sin(p)],p,1,derivative_bound=np.ones(len(p)),bound_provenance='analytic')
        self.assertEqual(r.certified_index,1)
        with self.assertRaises(ValueError):measure(np.ones((3,2)),np.array([0.,np.pi,2*np.pi]),1)
    def test_shared_store_adapter(self):
        _,s=build_numpy_gauge();p=self.grid();u=np.c_[np.cos(p),np.sin(p)]
        req=VelocityWindingRequest(**put_velocity_winding_inputs(s,u,p,np.ones(len(p))),radius=1,bound_provenance='analytic')
        r=NumpyVelocityWindingAdapter(s).measure(req)
        self.assertEqual(r.certified_index,1)
    def test_documented_fields(self):
        self.assertFalse([(m.__name__,n) for m in CONTRACTS for n,f in m.model_fields.items() if not f.description])

if __name__=='__main__':unittest.main()
