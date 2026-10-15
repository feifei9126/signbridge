"""Deduplicated training archive preserves variants and never overwrites source runs."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-training-dedup.py'
spec=importlib.util.spec_from_file_location('training_dedup',SCRIPT)
dedup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(dedup)

class DedupTests(unittest.TestCase):
    def test_same_bytes_map_to_one_object_but_round_references_remain(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp:
            root=Path(tmp);a=root/'T08';b=root/'T09';a.mkdir();b.mkdir()
            (a/'same.bin').write_bytes(b'identical');(b/'same.bin').write_bytes(b'identical')
            records,objects=dedup.inventory_files({'T08':a,'T09':b},root/'out')
            self.assertEqual(len(records),2)
            self.assertEqual(len(objects),1)
            self.assertEqual(records[0]['sha256'],records[1]['sha256'])

    def test_distinct_mask_variants_and_checkpoints_are_not_collapsed(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp:
            root=Path(tmp);a=root/'T08';b=root/'T09';a.mkdir();b.mkdir()
            (a/'tokenizer.pt').write_bytes(b'checkpoint-a')
            (b/'tokenizer.pt').write_bytes(b'checkpoint-b')
            (a/'mask.npy').write_bytes(b'mask-v1')
            (b/'mask.npy').write_bytes(b'mask-v2')
            _,objects=dedup.inventory_files({'T08':a,'T09':b},root/'out')
            self.assertEqual(len(objects),4)

    def test_round_manifest_rejects_unqualified_or_mismatched_report(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp:
            root=Path(tmp);run=root/'run';motion=root/'motion';run.mkdir();motion.mkdir()
            report={'schema':'signbridge-tokenizer-smoke-v1','status':'research_smoke_trained_not_deployable',
                    'research_only':True,'training_ready':False,'deployment_ready':False,
                    'text_to_sign_trained':False,'checkpoint_sha256':'a'*64,'checkpoint_step':10,
                    'checkpoint_reload_passed':True,'sequences':[{'segment_id':'clip-1','frames':4}],
                    'input_sha256':['b'*64]}
            (run/'report.json').write_text(json.dumps(report))
            (run/'tokenizer-smoke.pt').write_bytes(b'checkpoint')
            row={'segment_id':'clip-1','frames':4,'features':'samples/clip-1/features.npy'}
            sample=motion/'samples'/'clip-1';sample.mkdir(parents=True)
            (sample/'features.npy').write_bytes(b'feature')
            manifest={'schema':'test','created_at':'now','converted':1,'rejected':[],
                      'soke_commit':dedup.smoke.SOKE_COMMIT,'training_ready':False}
            (motion/'verification.json').write_text(json.dumps(manifest))
            (motion/'motions.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'checkpoint digest'):
                dedup.validate_round('T08',run,motion)

    def test_mismatched_segment_scope_is_rejected(self):
        report={'sequences':[{'segment_id':'clip-a','frames':4}]}
        rows=[{'segment_id':'clip-b','frames':4}]
        with self.assertRaisesRegex(ValueError,'scope differs'):
            dedup.validate_sequence_scope(report,rows)

if __name__=='__main__':unittest.main()
