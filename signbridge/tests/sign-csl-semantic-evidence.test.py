import importlib.util
from pathlib import Path
import tempfile
import unittest
import json

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-semantic-evidence.py'
spec = importlib.util.spec_from_file_location('csl_evidence', TOOL)
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)

class EvidenceTests(unittest.TestCase):
    def test_index_preserves_unverified_status_and_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source';source.mkdir()
            row={"annotation_id":"x","label":"去","source_sha256":"a"*64,"artifacts":{"clip.mp4":{"sha256":"b"*64}},"source_window_seconds":[1,2],"sample_type":"step_instruction","human_approved":False,"training_ready":False}
            (source/'fitting-reference-index.jsonl').write_text(json.dumps(row)+'\n')
            out=root/'out';tool.run(type('Args',(),{'source':source,'output':out})())
            data=json.loads((out/'semantic-evidence.json').read_text())
            self.assertEqual(len(data['focus_cases']),1)
            self.assertFalse(data['human_approved']);self.assertFalse(data['training_ready'])
            self.assertEqual(data['cases'][0]['semantic_evidence_status'],'assistant_candidate_only')

if __name__ == '__main__': unittest.main()
