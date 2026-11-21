"""Synthetic REF contract tests only; not ISO compliance or a runtime loader.

Fictional meta-standard examples, reuse of existing constructors, and explicit
expected failures for standards scaffolds that cannot yet represent metadata.
The enterprise ReferenceDictionary payload is deliberately not repurposed.
"""
"""Fictional test-content checks only. Not ISO conformity or a production schema."""
import hashlib,json
FORMS={'requirement':'shall','prohibition':'shall not','recommendation':'should','permission':'may','possibility':'can','capability':'can','statement':None}
PREDICATES={'marker_present':lambda r:bool(r.get('marker')),'marker_allowed':lambda r:r.get('marker') in ('ALPHA','BETA')}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def validate(f):
    if f.get('synthetic') is not True:raise ValueError('synthetic marker required')
    m=f['meta_content'];identity=m['identity']
    if not all(identity.get(x) for x in ['designation','title','edition','scope']):raise ValueError('identity metadata missing')
    if identity.get('publication_status')!='synthetic_test_only':raise ValueError('not an adopted standard')
    if digest(m)!=f['meta_content_sha256']:raise ValueError('content digest mismatch')
    refs=m['normative_references'];ids=[x['reference_id'] for x in refs]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate reference')
    for ref in refs:
        if ref.get('binding')!='dated' or not ref.get('edition'):raise ValueError('toy tests require edition pin')
        if ref.get('status')!='resolved' or ref.get('source')!='synthetic_inline':raise ValueError('normative reference unresolved')
    clauses=m['clauses'];keys=[c['id'] for c in clauses]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate clause')
    for c in clauses:
        if c['element_kind'] not in ('normative','informative'):raise ValueError('unknown element kind')
        kind=c['provision_kind']
        if kind not in FORMS or c['verbal_form']!=FORMS[kind]:raise ValueError('declared provision mismatch')
        if c['element_kind']=='informative' and kind!='statement':raise ValueError('informative text cannot create toy obligations')
        if any(x not in ids for x in c['reference_ids']):raise ValueError('unknown normative reference')
        pred=c.get('test_predicate')
        if kind in ('requirement','prohibition'):
            if pred not in PREDICATES:raise ValueError('test predicate unresolved')
        elif pred is not None:raise ValueError('non-requirement is not an obligation')
    return m

def evaluate(f,record):
    m=validate(f);results=[]
    for c in m['clauses']:
        if c['provision_kind'] not in ('requirement','prohibition'):continue
        # Do not infer applicability or epistemic truth from text or missing data.
        p=c['test_predicate'];verdict='unknown' if 'marker' not in record else ('satisfied' if PREDICATES[p](record) else 'not_satisfied')
        results.append({'clause_id':c['id'],'verdict':verdict})
    return {'toy_results':results,'approval':'not_established','compliance':'not_assessed'}

import copy,json,pathlib,unittest
W=pathlib.Path(__file__).resolve().parents[1]/'references/public'
class MetaTests(unittest.TestCase):
 def setUp(self):self.f=json.loads((W/'framework.meta.synthetic.v1.json').read_text())
 def refresh(self):self.f['meta_content_sha256']=digest(self.f['meta_content'])
 def invalid(self):
  with self.assertRaises(ValueError):validate(self.f)
 def test_valid(self):validate(self.f)
 def test_no_synthetic(self):self.f['synthetic']=False;self.invalid()
 def test_missing_edition(self):self.f['meta_content']['identity']['edition']='';self.refresh();self.invalid()
 def test_missing_scope(self):self.f['meta_content']['identity']['scope']='';self.refresh();self.invalid()
 def test_fake_adoption(self):self.f['meta_content']['identity']['publication_status']='adopted';self.refresh();self.invalid()
 def test_digest(self):self.f['meta_content']['identity']['title']='modified';self.invalid()
 def test_missing_ref_edition(self):self.f['meta_content']['normative_references'][0]['edition']=None;self.refresh();self.invalid()
 def test_unresolved_normative(self):self.f['meta_content']['normative_references'][0]['status']='unknown';self.refresh();self.invalid()
 def test_unresolved_informative_allowed(self):validate(self.f)
 def test_duplicate_refs(self):self.f['meta_content']['normative_references']*=2;self.refresh();self.invalid()
 def test_duplicate_clauses(self):self.f['meta_content']['clauses']*=2;self.refresh();self.invalid()
 def test_unknown_reference(self):self.f['meta_content']['clauses'][0]['reference_ids']=['missing'];self.refresh();self.invalid()
 def test_unknown_kind(self):self.f['meta_content']['clauses'][0]['provision_kind']='approval';self.refresh();self.invalid()
 def test_form_mismatch(self):self.f['meta_content']['clauses'][0]['verbal_form']='may';self.refresh();self.invalid()
 def test_no_keyword_auto_promotion(self):self.assertEqual(len(evaluate(self.f,{'marker':'ALPHA'})['toy_results']),2)
 def test_informative_no_obligation(self):self.f['meta_content']['clauses'][0]['element_kind']='informative';self.refresh();self.invalid()
 def test_recommendation_no_predicate(self):self.f['meta_content']['clauses'][2]['test_predicate']='marker_present';self.refresh();self.invalid()
 def test_no_dynamic_predicate(self):self.f['meta_content']['clauses'][0]['test_predicate']='__import__';self.refresh();self.invalid()
 def test_known_marker(self):self.assertTrue(all(x['verdict']=='satisfied' for x in evaluate(self.f,{'marker':'ALPHA'})['toy_results']))
 def test_unknown_marker(self):self.assertEqual(evaluate(self.f,{'marker':'GAMMA'})['toy_results'][1]['verdict'],'not_satisfied')
 def test_missing_marker_unknown(self):self.assertTrue(all(x['verdict']=='unknown' for x in evaluate(self.f,{})['toy_results']))
 def test_blank_marker_not_satisfied(self):self.assertEqual(evaluate(self.f,{'marker':''})['toy_results'][0]['verdict'],'not_satisfied')
 def test_no_approval(self):self.assertEqual(evaluate(self.f,{'marker':'ALPHA'})['approval'],'not_established')
 def test_no_compliance_claim(self):self.assertEqual(evaluate(self.f,{'marker':'ALPHA'})['compliance'],'not_assessed')
 def test_can_ambiguity_explicit(self):self.assertEqual({c['provision_kind'] for c in self.f['meta_content']['clauses'] if c['verbal_form']=='can'},{'possibility','capability'})

"""No eval, arbitrary imports, or JSON-selected executable constructors."""
import hashlib,json,os,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pydantic import ValidationError
from app.domain.reference.reference_set import ReferenceSet
from app.domain.reference.reference_value import ReferenceValue
from app.domain.standards.standards_organization import StandardsOrganization
from app.domain.standards.standard import Standard
from app.domain.standards.standard_edition import StandardEdition
from app.domain.standards.standard_clause import StandardClause
from app.domain.standards.specification_reference import SpecificationReference
ALLOWED={c.__name__:c for c in [ReferenceSet,ReferenceValue,StandardsOrganization,Standard,StandardEdition,StandardClause,SpecificationReference]}
W=ROOT/'references/public'

def construct(row):
    if set(row)!={'test_label','object_type','payload'}:raise ValueError('unexpected fixture fields')
    if row['object_type'] not in ALLOWED:raise ValueError('type not allowed')
    return ALLOWED[row['object_type']].model_validate(row['payload'])

class FrameworkTests(unittest.TestCase):
    def setUp(self):self.d=json.loads((W/'framework.meta.synthetic.v1.json').read_text())
    def test_synthetic_marker(self):self.assertIs(self.d['synthetic'],True)
    def test_no_authority(self):self.assertTrue(self.d['authority'].startswith('none'))
    def test_known_classes_only(self):self.assertTrue(all(x['object_type'] in ALLOWED for x in self.d['records']))
    def test_no_dynamic_class_import(self):
        with self.assertRaises(ValueError):construct({'test_label':'bad','object_type':'os.system','payload':{}})
    def test_no_injected_envelope_fields(self):
        x=dict(self.d['records'][0],python='arbitrary')
        with self.assertRaises(ValueError):construct(x)
    def test_reference_values_link_fixture_set(self):
        objects=[construct(x) for x in self.d['records']];refs=[o for o in objects if isinstance(o,ReferenceSet)]
        for o in objects:
            if isinstance(o,ReferenceValue):self.assertEqual(o.reference_set_id,refs[0].entity_id)
    def test_scaffold_metadata_still_blocked(self):
        for rejection in self.d['expected_scaffold_rejections']:
            row=next(x for x in self.d['records'] if x['object_type']==rejection['object_type']);p=dict(row['payload']);p[rejection['field']]=rejection['value']
            with self.subTest(object_type=row['object_type']):
                with self.assertRaises(ValidationError):ALLOWED[row['object_type']].model_validate(p)
    def test_inventory_dictionary_not_repurposed(self):
        self.assertNotIn('ReferenceDictionary',ALLOWED);self.assertNotIn('units',self.d)
    def test_metadata_does_not_imply_graph_hydration(self):self.assertIn('NOT a new runtime',self.d['scope'])
    def test_no_real_mapping(self):
        t=json.dumps(self.d['meta_content']);self.assertNotIn('F1',t);self.assertNotIn('KCM',t)

def add_tests():
    d=json.loads((W/'framework.meta.synthetic.v1.json').read_text())
    for i,row in enumerate(d['records']):
        def parse(self,row=row):
            obj=construct(row);self.assertEqual(str(obj.entity_id),row['payload']['entity_id'])
        setattr(FrameworkTests,f'test_construct_{i:02d}_{row["object_type"]}',parse)
        def not_accepted(self,row=row):
            obj=construct(row)
            with self.assertRaises(NotImplementedError):obj.require_accepted_definition()
        setattr(FrameworkTests,f'test_no_false_acceptance_{i:02d}_{row["object_type"]}',not_accepted)
add_tests()


class PublicReferenceBoundaryTests(unittest.TestCase):
    def test_exact_public_fixture_allowed(self):
        from scripts.check_release import allowed
        self.assertTrue(allowed('references/public/framework.meta.synthetic.v1.json'))
    def test_other_ref_not_implicitly_allowed(self):
        from scripts.check_release import allowed
        self.assertFalse(allowed('references/public/unreviewed.json'))
    def test_private_ref_still_forbidden(self):
        from scripts.check_release import allowed
        self.assertFalse(allowed('references/private/framework.meta.synthetic.v1.json'))
    def test_digest_roundtrip(self):
        f=json.loads((W/'framework.meta.synthetic.v1.json').read_text())
        self.assertEqual(digest(f['meta_content']),f['meta_content_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
