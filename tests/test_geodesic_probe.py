import sys
import unittest
from pathlib import Path
import doctest
import os
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from app.application.gauge import GaugeRequest,GaugeNode,GaugeParams,EmbeddingSpaceRef
from app.application.gauge.geodesic import GeodesicProbeRequest,CONTRACTS
from app.infrastructure.gauge import put_embeddings,build_numpy_gauge
from app.infrastructure.gauge.geodesic import readout,integrate_paths,build_numpy_geodesic_probe,warped_cylinder_christoffel
from app.infrastructure.gauge.lattice_kernels import reduce_arrays,normalise
from tests.test_gauge_numpy_adapters import sheet


def oracle_field(kind='swirl'):
    # Same flat geometry and same zero connection. Only the director field changes.
    xy=np.array([(x,y) for x in np.arange(-4,5) for y in np.arange(-4,5)],dtype=float)
    X=np.c_[xy,np.zeros(len(xy))]
    edges=np.array([(i,j) for i in range(len(xy)) for j in range(i+1,len(xy)) if np.linalg.norm(xy[i]-xy[j])<1.01],dtype=np.int64).T
    phi=np.arctan2(xy[:,1],xy[:,0])+np.pi/2 if kind=='swirl' else np.zeros(len(xy))
    center=int(np.argmin(np.linalg.norm(xy,axis=1)))
    mask=np.ones(len(xy),dtype=bool)
    # Center director is a probe orientation, not a claimed vortex-core orientation.
    phi[center]=0
    out=dict(node_mask=mask,director=phi,edge_index=edges,edge_connection=np.zeros(edges.shape[1]),
             triangles=np.zeros((3,0),dtype=np.int64),triangle_holonomy=np.zeros(0),triangle_charge=np.zeros(0))
    return X,out,center

class Transport(unittest.TestCase):
    def test_gauge_cancels_along_paths(self):
        X,out,i=oracle_field()
        rank=np.arange(len(X)); radii=(2.,3.,4.)
        a,mask,_=readout(X,out,[i],rank,radii,1.,mode='supply_demand')
        alpha=np.random.default_rng(3).uniform(-np.pi,np.pi,len(X))
        other=dict(out); other['director']=out['director']-alpha
        e=out['edge_index']; other['edge_connection']=out['edge_connection']-alpha[e[0]]+alpha[e[1]]
        b,mask2,_=readout(X,other,[i],rank,radii,1.,mode='supply_demand')
        np.testing.assert_array_equal(mask,mask2)
        np.testing.assert_allclose(a,b,atol=1e-12)

    def test_vortex_and_uniform_on_same_geometry_differ(self):
        values=[]
        for kind in ('uniform','swirl'):
            X,out,i=oracle_field(kind)
            d,ok,_=readout(X,out,[i],np.arange(len(X)),(2.,3.,4.),1.,mode='supply_demand')
            self.assertTrue(ok.all()); values.append(d[0,:,1])
        np.testing.assert_allclose(values[0],1.,atol=1e-12)
        np.testing.assert_allclose(values[1],0.,atol=1e-12)
        # This proves transport READOUT, not embedding-to-director recovery or a physical vortex inference.

    def test_shortest_path_length_and_phase(self):
        adj=[[(1,1.,.2),(2,3.,.9)],[(0,1.,-.2),(2,1.,.3)],[(0,3.,-.9),(1,1.,-.3)]]
        d,A,p=integrate_paths(adj,0,np.arange(3))
        np.testing.assert_allclose(d,[0,1,2]); self.assertAlmostEqual(A[2],.5)
        self.assertEqual(p[2],1)

    def test_missing_is_masked(self):
        X,out,i=oracle_field(); d,ok,_=readout(X,out,[i],np.arange(len(X)),(.01,),1.)
        self.assertFalse(ok.any()); self.assertTrue((d==0).all())

    def test_fixed_cylinder_intrinsic_connection_zero(self):
        np.testing.assert_array_equal(warped_cylinder_christoffel(2.,0.,0.),0.)

    def test_warped_cylinder_metric_compatibility(self):
        R,Rp,Rpp=2.,.3,-.2
        G=warped_cylinder_christoffel(R,Rp,Rpp)
        g=np.diag([R*R,1+Rp*Rp]); dg=np.zeros((2,2,2)); dg[1]=np.diag([2*R*Rp,2*Rp*Rpp])
        # nabla_k g_ij = partial_k g_ij - Gamma^l_ki g_lj - Gamma^l_kj g_il = 0
        for k in range(2):
            for i in range(2):
                for j in range(2):
                    value=dg[k,i,j]-sum(G[l,k,i]*g[l,j]+G[l,k,j]*g[i,l] for l in range(2))
                    self.assertAlmostEqual(value,0.)

class Probe(unittest.TestCase):
    def test_shared_store_perturbation_shapes_and_finite_values(self):
        rng=np.random.default_rng(1); P=rng.uniform(-1,1,(100,2)); X=sheet(P,curve=.15,noise=.001)
        gauge,store=build_numpy_gauge(); svc,shared=build_numpy_geodesic_probe(store)
        self.assertIs(shared,store)
        req=GaugeRequest(frame_id='test-perturb',space=EmbeddingSpaceRef(model='synthetic'),
                         nodes=tuple(GaugeNode(id=f'n{i:03}') for i in range(len(X))),embeddings=put_embeddings(store,X),
                         params=GaugeParams(k=8,director_ratio_min=1.01))
        q=GeodesicProbeRequest(source=req,focal_ids=('n020','n050'),radii=(3.,6.),epsilon=(.01,.05))
        result=svc.probe(q)
        self.assertEqual(result.request_digest,q.digest())
        self.assertEqual(result.response_rms.shape,(2,2,2,6))
        self.assertTrue(result.invariant_battery_passed)
        self.assertTrue(store.get(result.response_valid).any())
        for ref in result.tensor_refs().values():
            self.assertTrue(store.contains(ref)); self.assertTrue(np.isfinite(store.get(ref)).all())
        j=store.get(result.edge_jaccard); self.assertTrue(((j>=0)&(j<=1)).all())
        self.assertTrue((store.get(result.response_rms)>=0).all())

    def test_contracts_documented(self):
        self.assertFalse([(m.__name__,n) for m in CONTRACTS for n,f in m.model_fields.items() if not f.description])

    def test_full_probe_symmetries_include_response(self):
        rng=np.random.default_rng(1)
        P=rng.uniform(-1,1,(100,2)); X=sheet(P,curve=.15,noise=.001)
        svc,store=build_numpy_geodesic_probe()
        nodes=tuple(GaugeNode(id=f'n{i:03}') for i in range(len(X)))
        def run(Y,ns):
            req=GaugeRequest(frame_id='symmetry',space=EmbeddingSpaceRef(model='synthetic'),
                             nodes=ns,embeddings=put_embeddings(store,Y),
                             params=GaugeParams(k=8,director_ratio_min=1.01))
            r=svc.probe(GeodesicProbeRequest(source=req,focal_ids=('n020','n050'),radii=(3.,6.),epsilon=(.01,.05)))
            return {n:store.get(ref) for n,ref in r.tensor_refs().items()}
        base=run(X,nodes)
        Q,_=np.linalg.qr(rng.normal(size=(X.shape[1],X.shape[1])))
        perm=rng.permutation(len(X))
        transforms=(('rotation',X@Q,nodes),('scale',X*1000,nodes),
                    ('translation',X+10,nodes),('permutation',X[perm],tuple(nodes[i] for i in perm)))
        for name,Y,ns in transforms:
            with self.subTest(name):
                other=run(Y,ns)
                for key in base:
                    np.testing.assert_allclose(base[key],other[key],atol=1e-9,err_msg=key)

    def test_documentation_example(self):
        old=os.getcwd()
        os.chdir(ROOT)
        try:
            result=doctest.testfile(str(ROOT/'docs/pipelines/GEODESIC_PROBE.md'),module_relative=False)
        finally:
            os.chdir(old)
        self.assertEqual(result.failed,0)

if __name__=='__main__': unittest.main()
