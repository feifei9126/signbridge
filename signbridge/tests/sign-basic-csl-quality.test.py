"""Failed decode audits must stop automated stages, preserving diagnostics."""
import importlib.util
from pathlib import Path
import hashlib
import json
import tempfile
import types
import unittest
from unittest.mock import patch

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-basic-csl-quality.py'

class QualityTests(unittest.TestCase):
 def test_failed_full_decode_returns_nonzero_with_failed_report(self):
  spec=importlib.util.spec_from_file_location('basic_quality_test',TOOL)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'source.mp4';source.write_bytes(b'regression-fixture')
   inventory=root/'inventory.json';inventory.write_text(json.dumps({'unique_sources':[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}))
   observations=root/'observations';observations.mkdir();(observations/'observations-records.jsonl').write_text('')
   output=root/'new-audit';args=types.SimpleNamespace(inventory=inventory,observations=observations,output=output)
   fake=types.SimpleNamespace(returncode=1,stdout='',stderr='decode failed')
   with patch.dict('sys.modules',{'numpy':types.ModuleType('numpy'),'cv2':types.ModuleType('cv2')}),patch.object(module.subprocess,'run',return_value=fake):
    self.assertEqual(module.main(args),1)
   report=json.loads((output/'full-folder-decode.json').read_text())
   self.assertEqual(report['status'],'failed');self.assertEqual(report['records'][0]['exit_code'],1)
   self.assertEqual(report['records'][0]['stderr'],'decode failed')

if __name__=='__main__':unittest.main()
