"""Synthetic checks of release boundaries, not a confidentiality certification."""
import importlib.util,sys,tempfile,unittest,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('release_checks',ROOT/'scripts/check_release.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)

class ReleaseBoundary(unittest.TestCase):
    def test_private_references_denied(self):
        for p in ['references/private/dictionary.json','references/projection.json','references/public/real_records.json','data/embeddings.csv','.env','src/app/infrastructure/outbound/private.py']:
            self.assertFalse(checks.allowed(p),p)
        self.assertTrue(checks.allowed('references/public/manifest.example.json'))
    def test_agency_slices_allowlisted(self):
        for p in ['src/app/application/process/contracts.py','src/app/application/plate/services.py','src/app/application/messaging/ports.py',
                  'src/app/infrastructure/plate/kernels.py','src/app/application/enrichment/contracts.py','src/app/application/probe/barrier.py','src/app/infrastructure/probe/kernels.py','src/app/application/ingest/ring.py','src/app/domain/shared/scaffold_record.py','src/app/domain/product/product_definition.py','docs/domain/DOMAIN_SCAFFOLD.md','docs/domain/domain_scaffold_manifest.json','src/app/infrastructure/ingest/adapters.py','docs/architecture/INGESTION.md','src/app/infrastructure/enrichment/kernels.py','src/app/infrastructure/messaging/memory.py','docs/domain/PROCESS_FIRST.md',
                  'docs/architecture/MESSAGE_BROKER.md','docs/contracts/schemas/agency/PlateRunResult.schema.json',
                  'src/app/application/common/contracts.py','src/app/application/hfgt/translation.py','src/app/infrastructure/hfgt/kernels.py',
                  'tests/fixtures/hfgt/wme_rack.synthetic.json','docs/pipelines/HFGT_CAPABILITY_GRAPH.md']:
            self.assertTrue(checks.allowed(p),p)
        self.assertFalse(checks.allowed('src/app/infrastructure/messaging/mqtt_private.json'))
    def test_private_file_not_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p=r/'references/private/example.json';p.parent.mkdir(parents=True);p.write_text('{"synthetic_private_sentinel":true}')
            public=r/'README.md';public.write_text('Public synthetic example')
            files,errors=checks.check(r,git_check=False)
            self.assertEqual(files,[public]);self.assertFalse(errors)
    def test_internal_url_detected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);(r/'README.md').write_text('https://'+'app.'+'clickup.com'+'/synthetic-test-only')
            _,errors=checks.check(r,git_check=False)
            self.assertTrue(any('internal URL' in x for x in errors))
    def test_only_reserved_synthetic_addresses_pass(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);(r/'README.md').write_text('From: a@example.invalid')
            self.assertFalse(checks.check(r,git_check=False)[1])
            (r/'README.md').write_text('From: a@example.invalid, b@'+'example.com')
            self.assertTrue(any('email address' in x for x in checks.check(r,git_check=False)[1]))
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);(r/'README.md').symlink_to(ROOT/'README.md')
            _,errors=checks.check(r,git_check=False)
            self.assertTrue(any('symlink forbidden' in x for x in errors))
    def test_forced_tracked_private_reference_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);subprocess.run(['git','init','-q',str(r)],check=True)
            p=r/'references/private/example.json';p.parent.mkdir(parents=True);p.write_text('{}')
            subprocess.run(['git','add','-f','references/private/example.json'],cwd=r,check=True)
            _,errors=checks.check(r)
            self.assertTrue(any('forbidden tracked path' in x for x in errors))
    def test_simulation_preserves_empty_shared_store(self):
        from app.infrastructure.tensors import InMemoryNumpyTensorStore,build_numpy_simulation
        from app.infrastructure.gauge import build_numpy_gauge
        store=InMemoryNumpyTensorStore();sim,same,_=build_numpy_simulation(store)
        gauge,also=build_numpy_gauge(store)
        self.assertIs(same,store);self.assertIs(also,store)
    def test_synthetic_field_gradient_matches_finite_difference(self):
        import numpy as np
        from app.infrastructure.tensors.numpy_kernels import field
        V=np.array([[-.3,0.,.2],[.4,.1,-.25],[0.,-.5,.15]])
        x=np.array([.1,.6]);y=np.array([.2,-.3]);h=1e-6
        a=field(V,x,y,.07,.02,6.)
        xp=field(V,x+h,y,.07,.02,6.);xm=field(V,x-h,y,.07,.02,6.)
        yp=field(V,x,y+h,.07,.02,6.);ym=field(V,x,y-h,.07,.02,6.)
        for got,want in [(a[2],(xp[0]-xm[0])/(2*h)),(a[3],(yp[0]-ym[0])/(2*h)),(a[4],(xp[1]-xm[1])/(2*h)),(a[5],(yp[1]-ym[1])/(2*h))]:
            np.testing.assert_allclose(got,want,atol=1e-8,rtol=1e-7)

if __name__=='__main__':unittest.main()
