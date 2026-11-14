"""Do not turn course text corrections into invented lexical/motion approval."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-csl-lexical-audit.py'
def module():
 spec=importlib.util.spec_from_file_location('lexical_audit_test',TOOL);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class LexicalAuditTests(unittest.TestCase):
 def test_normalization_does_not_merge_opposed_terms(self):
  m=module()
  self.assertEqual(m.text_key(' “我” ／ 你 '),'我/你')
  self.assertNotEqual(m.text_key('上午'),m.text_key('下午'))
  self.assertNotEqual(m.text_key('我'),m.text_key('我们'))
 def test_sentence_context_never_becomes_isolated_word(self):
  m=module()
  self.assertEqual(m.classify_interval('word','我','我很好','sentence_context'),'context_only')
  self.assertEqual(m.classify_interval('word','我','“我”就是用食指指一下自己','explicit_instruction'),'instruction_subunit_not_certified_boundary')
  self.assertEqual(m.classify_interval('word','上午','上午','visible_title'),'source_label_not_motion_approval')
 def test_instruction_must_be_in_actual_timed_source_ocr(self):
  m=module();lesson={'raw_spatial_ocr':[{'seconds':7.,'lines':[{'text':'伸出食指'},{'text':'指向前面表示“你”'}]}]}
  self.assertTrue(m.instruction_matches(lesson,7.,'指向前面表示你'))
  self.assertFalse(m.instruction_matches(lesson,7.,'伸出中指'))
  self.assertFalse(m.instruction_matches(lesson,17.,'伸出食指'))
 def test_automatic_annotations_cannot_raise_gates(self):
  m=module();base={'human_approved':False,'training_ready':False,'national_standard_match':'not_checked'}
  m.no_approval(base)
  for change in [{'human_approved':True},{'semantics_approved':True},{'training_ready':True},{'model_training_ready':True},{'national_standard_match':'verified'}]:
   with self.assertRaises(ValueError):m.no_approval({**base,**change})
 def test_corrections_apply_only_at_source_and_time_scope(self):
  m=module();rule={'source_id':'a','seconds':10.,'raw_text':'没美系','corrected_text':'没关系'}
  self.assertEqual(m.correct_line('没美系','a',10.,[rule]),('没关系',[0]))
  self.assertEqual(m.correct_line('没美系','b',10.,[rule]),('没美系',[]))
  self.assertEqual(m.correct_line('没美系','a',40.,[rule]),('没美系',[]))
 def test_interval_bounds_and_typing_are_checked(self):
  m=module();lesson={'source_id':'one','number':1,'duration':20.,'raw_spatial_ocr':[]}
  term={'canonical_text':'我','unit_type':'word','meaning':'说话者本人','source_intervals':[{'start':1.,'end':2.,'basis':'visible_title'}],'evidence_status':'assistant_source_audited'}
  row={'source_id':'one','number':1,'course_title':'问候','course_type':'lexical_teaching','lesson_summary':'说明','terms':[term],'visual_sheets_inspected':[],'text_corrections':[],'excluded_or_context_only':[],'gaps':[]}
  self.assertEqual(m.validate_annotations(lesson,row),[])
  for interval in [{'start':False,'end':2.,'basis':'visible_title'},{'start':2.,'end':1.,'basis':'visible_title'},{'start':1.,'end':21.,'basis':'visible_title'},{'start':1.,'end':2.,'basis':'guessed'}]:
   with self.assertRaises(ValueError):m.validate_annotations(lesson,{**row,'terms':[{**term,'source_intervals':[interval]}]})
 def test_safe_artifact_paths_and_symlinks_rejected(self):
  m=module()
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'valid.json').write_text('{}')
   self.assertEqual(m.safe_file(root,'valid.json'),root/'valid.json')
   for name in ['../outside','/tmp/x','a\\b','./valid.json']:
    with self.assertRaises(ValueError):m.safe_file(root,name)
   (root/'link.json').symlink_to(root/'valid.json')
   with self.assertRaises(ValueError):m.safe_file(root,'link.json')

 def test_filtered_correction_refs_keep_original_indices(self):
  m=module();rules=[{'source_id':'a','seconds':1.,'raw_text':'误','corrected_text':'一','auto_apply':False,'correction_id':'first'}, {'source_id':'a','seconds':2.,'raw_text':'误','corrected_text':'二','auto_apply':True,'correction_id':'second'}]
  self.assertEqual(m.correct_line('误','a',2.,rules),('二',[1]))
  self.assertEqual(m.correct_line('误','a',1.,rules),('误',[]))
 def test_fixed_scope_requires_all_48_distinct_sources_and_62_aliases(self):
  m=module();index=[{'source_id':str(i),'sha256':str(i),'number':i+1} for i in range(48)]
  sources=[{'source_id':str(i),'sha256':str(i),'aliases':['a','b'] if i<14 else ['a']} for i in range(48)]
  inv={'unique_sources':sources,'counts':{'files':62}}
  m.validate_index(index,inv)
  for broken in [[],index[:-1],index[:-1]+[index[0]]]:
   with self.assertRaises(ValueError):m.validate_index(broken,inv)
 def test_read_snapshot_hashes_the_same_bytes_it_parses(self):
  m=module()
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'input.json';raw=b'{"value":"original"}';path.write_bytes(raw)
   data,digest,content=m.read_snapshot(path)
   path.write_text('{"value":"replaced"}')
   import hashlib
   self.assertEqual(data,{'value':'original'});self.assertEqual(content,raw);self.assertEqual(digest,hashlib.sha256(raw).hexdigest())

if __name__=='__main__':unittest.main()
