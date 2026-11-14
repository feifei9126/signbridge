import importlib.util
from pathlib import Path
import unittest
import math
import tempfile
import hashlib

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-basic-csl-relabel.py'
def module():
 spec=importlib.util.spec_from_file_location('basic_relabel_test',TOOL)
 value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

class RelabelTests(unittest.TestCase):
 def test_phrase_never_automatically_becomes_component_word(self):
  m=module()
  self.assertEqual(m.evidence_kind('我','我很好',False),'context_only')
  self.assertEqual(m.evidence_kind('早上','早上好',False),'context_only')
  self.assertEqual(m.evidence_kind('我','“我”就是用食指指一下自己',True),'explicit_instruction_subunit')
 def test_invalid_windows_and_phony_approval_rejected(self):
  m=module();row={'id':'unit-one','text':'我','start':1.,'end':2.,'source_sha256':'a'*64,'assistant_note':'source instruction','human_approved':False}
  m.validate_proposal(row,3.)
  for updates in [{'start':float('nan')},{'end':.5},{'end':4.},{'human_approved':True},{'id':'../x'},{'start':True},{'source_sha256':'g'*64},{'semantics_approved':True},{'boundaries_approved':True},{'training_ready':True},{'model_training_ready':True},{'text_verified':'我'},{'training_started':True}]:
   with self.assertRaises(ValueError):m.validate_proposal({**row,**updates},3.)
 def test_source_group_not_alias_or_frame_controls_split(self):
  m=module()
  a=m.training_group('a'*64,1.,2.);b=m.training_group('a'*64,2.,3.)
  self.assertEqual(a,b);self.assertNotEqual(a,m.training_group('b'*64,1.,2.))
 def test_missing_nonmanual_never_zero_filled(self):
  m=module()
  self.assertEqual(m.finite_summary([1,float('nan'),2]),{'count':2,'missing':1,'median':1.5,'p95':1.95})
  self.assertEqual(m.finite_summary([float('nan')])['count'],0)
 def test_primary_heading_excludes_footer_instruction_and_watermark(self):
  m=module()
  self.assertTrue(m.is_heading({'text':'下午好','bounding_box':[.35,.87,.3,.08],'confidence':1}))
  self.assertFalse(m.is_heading({'text':'下午好','bounding_box':[.3,.1,.4,.08],'confidence':1}))
  self.assertFalse(m.is_heading({'text':'挑战100天学会手语','bounding_box':[.2,.86,.7,.07],'confidence':1}))

 def test_actual_source_file_must_match_verified_inventory_path_and_digest(self):
  m=module()
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);a=root/'a.mp4';b=root/'b.mp4';a.write_bytes(b'video-A');b.write_bytes(b'video-B')
   digest=hashlib.sha256(a.read_bytes()).hexdigest();sources={digest:{'path':str(a)}}
   self.assertEqual(m.verified_proposal_source({'source_sha256':digest,'source_path':str(a)},sources,root),a.resolve())
   with self.assertRaises(ValueError):m.verified_proposal_source({'source_sha256':digest,'source_path':str(b)},sources,root)
 def test_failed_or_partial_extraction_cannot_be_called_completed(self):
  m=module()
  self.assertEqual(m.observation_status(0,[{'error':'decode'}]),'failed_no_observations')
  self.assertEqual(m.observation_status(1,[{'error':'decode'}]),'partial_observations_with_failures')
  self.assertEqual(m.observation_status(1,[]),'observation_extraction_completed')

if __name__=='__main__':unittest.main()
