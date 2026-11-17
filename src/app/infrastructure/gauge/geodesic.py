"""Numpy implementation of a graph-geodesic approximation; not a smooth-geodesic solver.

A_uv maps coordinates at v to u. Along root->...->j, U = product exp(i*m*A_uv).
The invariant interaction is conjugate(psi_root)*U*psi_j, psi_j=exp(i*m*phi_j).
These edge links are Procrustes estimates from embeddings, NOT integrals of a separately
specified continuous A. Shortest weighted graph paths approximate manifold geodesics.
"""
from __future__ import annotations
import heapq
import numpy as np
from app.application.gauge.contracts import GaugeCheckRequest
from app.application.gauge.geodesic import GeodesicProbeResult, GeodesicProbeService
from app.application.simulation.tensors import TensorContractError
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore
from .numpy_adapters import _inputs, NumpyGaugeInvarianceAdapter
from .lattice_kernels import reduce_arrays, knn, normalise, patches


def adjacency(X, out):
    """Chord-length weighted connection graph in normalized embeddings (undirected, reverse A=-A)."""
    adj = [[] for _ in X]
    for t,(a,b) in enumerate(out["edge_index"].T):
        length = float(np.linalg.norm(X[a]-X[b]))
        A = float(out["edge_connection"][t])
        adj[a].append((int(b),length,A))
        adj[b].append((int(a),length,-A))
    return adj


def integrate_paths(adj, root, ranks, cutoff=np.inf):
    """Dijkstra with deterministic id-rank ties; summed link phases give parallel transport to root.

    Degenerate equal-length alternate paths are NOT averaged. Their Wilson-loop disagreement
    is real path dependence; a shortest-path tree selects one route and must not hide this choice.
    """
    n=len(adj); dist=np.full(n,np.inf); angle=np.zeros(n); parent=-np.ones(n,dtype=np.int64)
    dist[root]=0.; queue=[(0.,int(ranks[root]),root)]; done=set()
    while queue:
        d,_,u=heapq.heappop(queue)
        if u in done or d>cutoff: continue
        done.add(u)
        for v,length,A in sorted(adj[u], key=lambda x:ranks[x[0]]):
            nd=d+length
            if v not in done and nd<dist[v] and nd<=cutoff:
                dist[v]=nd; angle[v]=angle[u]+A; parent[v]=u
                heapq.heappush(queue,(nd,int(ranks[v]),v))
    return dist,angle,parent


def readout(X, out, focal, ranks, radii, spacing, minimum=3, mode="principal_axis"):
    """Invariant multiscale balls using the director and connection from a lattice reduction."""
    adj=adjacency(X,out); m=2 if mode=="principal_axis" else 1
    vals=np.zeros((len(focal),len(radii),6)); mask=np.zeros(vals.shape[:2],dtype=bool)
    counts=np.zeros(vals.shape[:2],dtype=np.int64)
    for p,i in enumerate(focal):
        if not out["node_mask"][i]: continue
        d,A,_=integrate_paths(adj,i,ranks,max(radii)*spacing)
        C=np.exp(1j*m*(out["director"]+A-out["director"][i]))
        for s,r in enumerate(radii):
            ids=np.flatnonzero((d>0)&(d<=r*spacing))
            counts[p,s]=len(ids)
            if len(ids)<minimum: continue
            mask[p,s]=True
            w=np.exp(-0.5*(d[ids]/(r*spacing))**2); z=np.sum(w*C[ids])/w.sum()
            ball=np.zeros(len(X),dtype=bool); ball[ids]=True; ball[i]=True
            tri=out["triangles"]
            inside=ball[tri].all(axis=0) if tri.shape[1] else np.zeros(0,dtype=bool)
            # Absolute curvature/charge avoids arbitrary component handedness comparisons across perturbations.
            h=out["triangle_holonomy"][inside]; q=out["triangle_charge"][inside]
            phase = abs(np.angle(z))/m if abs(z)>1e-10 else 0.0  # phase undefined at zero coherence
            vals[p,s]=(z.real,abs(z),phase,np.mean(d[ids])/spacing,
                       np.nansum(abs(h)),np.nansum(abs(q)))
    return vals,mask,counts


def edge_set(out):
    return {tuple(e) for e in out["edge_index"].T.tolist()}


class NumpyGeodesicProbeAdapter:
    def __init__(self,store): self.store=store

    def probe(self,request):
        req=request.source
        passed=None
        if request.check_invariance:
            check=NumpyGaugeInvarianceAdapter(self.store).check(GaugeCheckRequest(request=req))
            if not check.passed:
                raise TensorContractError("base gauge invariance failed; geodesic readings refused")
            passed=True
        X=normalise(np.asarray(self.store.get(req.embeddings),dtype=np.float64))
        ids,rank,flow,loops,kw=_inputs(req,X)
        focal=[ids.index(i) for i in request.focal_ids]
        base=reduce_arrays(X,rank,flow,loops=loops,**kw)
        nb,nd=knn(X,req.params.k); frames,lam=patches(X,nb)
        spacing=float(np.median(nd[:,0]))
        if spacing<=1e-12:
            raise TensorContractError("duplicate/degenerate embeddings give zero nearest-neighbor spacing")
        desc,valid,counts=readout(X,base,focal,rank,request.radii,spacing,request.minimum_neighbors,req.params.director_mode)
        response=np.zeros((len(focal),len(request.epsilon),len(request.radii),6))
        rvalid=np.zeros(response.shape[:3],dtype=bool); frac=np.zeros_like(rvalid,dtype=float)
        jac=np.zeros(response.shape[:2]); B=edge_set(base)
        for p,i in enumerate(focal):
            for h,eps in enumerate(request.epsilon):
                vals=[]; masks=[]; jacs=[]
                for axis in (0,1):
                    for sign in (-1,1):
                        Y=X.copy(); Y[i]+=sign*eps*nd[i].mean()*frames[i,:,axis]
                        # Rebuild neighborhoods, local frames, connection and graph. Nothing silently frozen.
                        out=reduce_arrays(Y,rank,flow,loops=loops,**kw)
                        v,ok,_=readout(normalise(Y),out,[i],rank,request.radii,spacing,request.minimum_neighbors,req.params.director_mode)
                        vals.append(v[0]); masks.append(ok[0]); E=edge_set(out)
                        jacs.append(len(B&E)/len(B|E) if B|E else 1.)
                vals=np.array(vals); masks=np.array(masks)
                frac[p,h]=masks.mean(axis=0); jac[p,h]=np.mean(jacs)
                joint=valid[p]&masks.all(axis=0); rvalid[p,h]=joint
                delta=(vals-desc[p])/eps
                response[p,h,joint]=np.sqrt(np.mean(delta[:,joint,:]**2,axis=0))
        arrays=dict(descriptor=desc,valid=valid,neighbor_count=counts,response_rms=response,response_valid=rvalid,
                    edge_jaccard=jac,valid_fraction=frac)
        refs={n:self.store.put(s,arrays[n],producer="NumpyGeodesicProbeAdapter") for n,s in GeodesicProbeResult.TENSORS.items()}
        return GeodesicProbeResult(request_digest=request.digest(),embeddings_sha256=req.embeddings.sha256,
                                   focal_ids=request.focal_ids,radii=request.radii,epsilon=request.epsilon,
                                   invariant_battery_passed=passed,**refs)


def build_numpy_geodesic_probe(store=None):
    """Return (service, shared store), compatible with build_numpy_gauge and build_numpy_simulation."""
    store=InMemoryNumpyTensorStore() if store is None else store
    return GeodesicProbeService(store,NumpyGeodesicProbeAdapter(store)),store


def warped_cylinder_christoffel(radius, first, second):
    """Levi-Civita coefficients for X(theta,z)=(R(z)cos(theta),R(z)sin(theta),z).

    g=diag(R^2,1+R'^2). Axis order (theta,z). Returns Gamma[mu,alpha,beta].
    Fixed R: all zero intrinsically despite nonzero extrinsic cylinder curvature.
    """
    if not np.isfinite([radius,first,second]).all() or radius<=0:
        raise ValueError("finite R>0, R', R'' required")
    G=np.zeros((2,2,2)); G[0,0,1]=G[0,1,0]=first/radius
    G[1,0,0]=-radius*first/(1+first**2)
    G[1,1,1]=first*second/(1+first**2)
    return G
