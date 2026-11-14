"""Whole-clip review media chooses real saved overlays and preserves original frame timing."""
import importlib.util,json,tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-sequence-media.py'
class SequenceMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s=importlib.util.spec_from_file_location('sequence_media',SCRIPT);cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)
    def test_temporal_fallback_uses_baseline_overlay_and_raw_fusion_remains_separate(self):
        self.assertEqual(self.m.overlay_name({'temporal_baseline_selected':True}),'baseline-overlay.jpg')
        self.assertEqual(self.m.overlay_name({'temporal_baseline_selected':False}),'candidate-overlay.jpg')
        with self.assertRaises(ValueError):self.m.overlay_name({})
    def test_video_preserves_full_frame_scope_source_fps_and_no_approval(self):
        r=self.m.media_contract('pilot-greeting-hello-001',166,25.)
        self.assertEqual(r['frames'],166);self.assertEqual(r['fps'],25.)
        self.assertFalse(r['training_ready']);self.assertFalse(r['temporal_interpolation'])
        with self.assertRaises(ValueError):self.m.media_contract('x',0,25.)
    def test_reconstruction_comparison_is_explicitly_in_sample_and_masked(self):
        r=self.m.media_contract('pilot-greeting-hello-001',166,25.,reconstruction=True)
        self.assertTrue(r['in_sample_reconstruction'])
        self.assertTrue(r['unaccepted_hands_preserved'])
        self.assertIn('Tokenizer',r['panels'][2])


class SequenceMediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        s=importlib.util.spec_from_file_location('sequence_media_runtime',SCRIPT)
        self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.batch=self.root/'batch';self.fusion=self.root/'fusion/results';self.motions=self.root/'motions'
        segment='pilot-greeting-hello-001'
        for frame in (1,2):
            image=self.batch/'samples'/segment/'images'/('%06d.jpg'%frame);image.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(1280,720),'white').save(image)
            folder=self.fusion/segment/('%06d'%frame);folder.mkdir(parents=True)
            Image.new('RGB',(1280,720),'blue').save(folder/'baseline-overlay.jpg')
            Image.new('RGB',(1280,720),'green').save(folder/'candidate-overlay.jpg')
        self.motions.mkdir()
        (self.motions/'motions.jsonl').write_text(json.dumps({'segment_id':segment,'frames':2,'fps':25.})+'\n')
        folder=self.motions/'samples'/segment;folder.mkdir(parents=True)
        (folder/'frame-quality.jsonl').write_text(''.join(json.dumps({'frame_1based':f,
            'temporal_baseline_selected':f==2})+'\n' for f in (1,2)))
        self.manifest(self.fusion.parent);self.manifest(self.motions)
        self.args=SimpleNamespace(batch=self.batch,fusion_results=self.fusion,motions=self.motions,output=self.root/'output')
    def manifest(self,folder):
        paths=sorted(p for p in folder.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
        (folder/'SHA256SUMS').write_text(''.join(self.m.evidence.digest(p)+'  '+str(p.relative_to(folder))+'\n' for p in paths))
    def test_encoded_video_retains_two_frames_and_records_baseline_fallback(self):
        output=self.m.create(self.args)
        r=json.loads((output/'pilot-greeting-hello-001-media.json').read_text())
        self.assertEqual(int(r['encoded']['nb_read_frames']),2)
        self.assertEqual(r['encoded']['avg_frame_rate'],'25/1')
        self.assertFalse(r['training_ready'])
        self.assertTrue(any(name.endswith('000002/baseline-overlay.jpg') for name in r['source_sha256']))
        self.m.evidence.verify_manifest(output,output/'SHA256SUMS')
    def test_tampered_overlay_is_rejected(self):
        path=self.fusion/'pilot-greeting-hello-001/000001/candidate-overlay.jpg'
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            self.m.create(self.args)
        self.assertFalse(self.args.output.exists())
if __name__=='__main__':unittest.main()
