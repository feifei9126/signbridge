"""New folders retain source provenance and never gain invented corpus labels."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-csl-reference-extra.py'
spec=importlib.util.spec_from_file_location('reference_extra_test',SCRIPT)
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


class ExtraReferenceTests(unittest.TestCase):
    def fixture(self, root):
        root=root.resolve();intake=root/'intake';intake.mkdir();stage=root/'stage';stage.mkdir();(stage/'provenance').mkdir()
        original=root/'original.mp4';original.write_bytes(b'wholecourse');prior=root/'prior';prior.mkdir();clip=prior/'clip.mp4';clip.write_bytes(b'candidateclip')
        source={'source_id':'extra-source-abc','folder_id':'extra-folder-1','absolute_path':str(original),'sha256':e.core.ce.sha(original),'duration_seconds':10.,'aliases':[str(original)],'probe':{}}
        row={'id':'csl_candidate_a','source_sha256':source['sha256'],'proposed_text':'我','source_window_seconds':[1.,3.], 'human_approved':False,'training_ready':False,'model_training_ready':False,'reference_clip':'clip.mp4','clip_sha256':e.core.ce.sha(clip),'decoded_video':{'frames':50,'fps':25.}}
        report=prior/'report.json';e.core.write_json(report,{'candidates':[row]});wrapped={**row,'intake':{'prior_report_absolute_path':str(report),'prior_report_sha256':e.core.ce.sha(report)}}
        e.core.write_json(intake/'inventory.json',{'sources':[source]});e.core.write_json(intake/'report.json',{'status':'passed','issues':[]});e.core.write_jsonl(intake/'prior-window-candidates.jsonl',[wrapped])
        return intake,stage,original,wrapped

    def test_course_has_empty_chinese_and_gloss_caption_is_only_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            intake,stage,original,_=self.fixture(Path(d));media=e.core.MediaCopies(stage)
            datasets,samples,windows,summary=e.prepare(stage,intake,media,[{'id':'ce-term','label':'我','in_ce_csl':True}])
            self.assertEqual(len(datasets),2);self.assertEqual(len(samples),2)
            lesson=next(x for x in samples if x['source_split']=='reference');self.assertEqual(lesson['raw']['Chinese Sentences'],'');self.assertEqual(lesson['raw']['Gloss'],'')
            candidate=next(x for x in samples if x['source_split']=='candidates');self.assertFalse(candidate['training_ready']);self.assertFalse(candidate['human_approved']);self.assertEqual(windows[0]['matched_ce_term_id'],'ce-term');self.assertFalse(windows[0]['same_sign_verified'])
            self.assertEqual(summary['new_approved_labels'],0);self.assertEqual(original.read_bytes(),b'wholecourse')

    def test_modified_prior_label_is_rejected_even_when_report_hash_matches(self):
        with tempfile.TemporaryDirectory() as d:
            intake,stage,original,row=self.fixture(Path(d));row['proposed_text']='伪标签';e.core.write_jsonl(intake/'prior-window-candidates.jsonl',[row])
            with self.assertRaises(ValueError):e.prepare(stage,intake,e.core.MediaCopies(stage),[])
            self.assertEqual(original.read_bytes(),b'wholecourse')

    def test_unsafe_candidate_id_never_writes_outside_stage(self):
        with tempfile.TemporaryDirectory() as d:
            intake,stage,original,row=self.fixture(Path(d));row['id']='a/../../outside';e.core.write_jsonl(intake/'prior-window-candidates.jsonl',[row])
            with self.assertRaises(ValueError):e.prepare(stage,intake,e.core.MediaCopies(stage),[])
            self.assertEqual(original.read_bytes(),b'wholecourse');self.assertFalse((Path(d)/'outside').exists())

    def test_exact_window_duplicates_keep_alias_without_duplicate_sample(self):
        with tempfile.TemporaryDirectory() as d:
            intake,stage,_,row=self.fixture(Path(d));e.core.write_jsonl(intake/'prior-window-candidates.jsonl',[row,row])
            _,samples,windows,summary=e.prepare(stage,intake,e.core.MediaCopies(stage),[])
            self.assertEqual(len(windows),1);self.assertEqual(len(samples),2);self.assertEqual(summary['collapsed_exact_window_duplicates'],1)


if __name__=='__main__':unittest.main()
