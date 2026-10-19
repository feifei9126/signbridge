import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-research-optimization-dashboard.py'
spec=importlib.util.spec_from_file_location('research_dashboard',TOOL);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class DashboardTests(unittest.TestCase):
 def test_dashboard_binds_metrics_and_only_links_local_candidate_review(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   semantic=root/'semantic.json';motion=root/'motion.json';candidate=root/'candidate.json';output=root/'report'
   semantic.write_text(json.dumps({'fixture_sha256':'a'*64,'baseline':{'metrics':{'selective_accuracy':.7}},'scope_experiment':{'metrics':{'selective_accuracy':1,'false_accept_rate':0},'by_partition':{'structure_holdout':{'supported_coverage':1}}},'leakage_excluded_baseline':{'metrics':{'supported_coverage':.5}},'leakage_excluded_scope_experiment':{'metrics':{'supported_coverage':.8,'selective_accuracy':1,'false_accept_rate':0},'by_partition':{'structure_holdout':{'supported_coverage':.8}}},'old_training_text_overlap':['x']}))
   motion.write_text(json.dumps({'summary':{'clips':1,'numericComparisonPass':0,'existingWristMidpointP95MeanCm':1,'adaptiveWristMidpointP95MeanCm':2,'existingMinimumRangeRetention':.8,'adaptiveMinimumRangeRetention':.7,'meanColdCompileMs':20,'meanWarmLookupMs':.01,'maximumCacheNumericBytes':100},'records':[{'text':'通知','id':'a','profiles':{'existing':{'metrics':{'wristMidpointP95Cm':1}},'adaptive':{'metrics':{'wristMidpointP95Cm':2},'minimumWristRangeRetention':.7,'fingerEndJointDisplacementP95Cm':3}},'adaptivePassesNumericComparison':False}]}))
   candidate.write_text(json.dumps({'candidates':[{'proposed_text':'来','decode':{'frames':5}}],'verified_word_units':0}))
   result=module.run(semantic,motion,candidate,output)
   self.assertFalse(result['human_approved']);self.assertFalse(result['model_training_ready'])
   page=(output/'index.html').read_text()
   self.assertIn('../unit-candidates-final/index.html',page)
   self.assertIn('../browser-feature-v3/sample-existing-profile.png',page)
   self.assertEqual(result['unit_candidate_decoded_frames'],5)
   hashes=(output/'SHA256SUMS').read_text().splitlines()
   for line in hashes:
    digest,name=line.split('  ',1)
    self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),digest)
   with self.assertRaises(FileExistsError):module.run(semantic,motion,candidate,output)

if __name__=='__main__':unittest.main()
