import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-model-demo-launch.py'


class LauncherTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('demo_launch_test', TOOL)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def test_saved_url_cannot_contact_remote_host_or_another_local_instance(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'state.json'
            for url in ['https://evil.example/demo/model.html', 'http://localhost:8888/demo/model.html',
                        'http://127.0.0.1:8888/demo/model.html?token=x', 'http://user@127.0.0.1:8888/demo/model.html']:
                p.write_text(json.dumps({'url': url, 'instance': 'a' * 24}))
                with patch.object(m, 'urlopen') as opener:
                    with self.assertRaises(ValueError): m.existing_url(p, 'c' * 64)
                    opener.assert_not_called()
            p.write_text(json.dumps({'url': 'http://127.0.0.1:8888/demo/model.html', 'instance': 'a' * 24}))
            for instance, digest, valid in [('a' * 24, 'c' * 64, True), ('b' * 24, 'c' * 64, False), ('a' * 24, 'd' * 64, False)]:
                response = io.BytesIO(json.dumps({'instance': instance, 'checkpoint_sha256': digest}).encode())
                with patch.object(m, 'urlopen', return_value=response):
                    if valid: self.assertEqual(m.existing_url(p, 'c' * 64), 'http://127.0.0.1:8888/demo/model.html')
                    else:
                        with self.assertRaises(ValueError): m.existing_url(p, 'c' * 64)
            for malformed in [[], None, 'ok', 1]:
                with patch.object(m, 'urlopen', return_value=io.BytesIO(json.dumps(malformed).encode())):
                    with self.assertRaises(ValueError): m.existing_url(p, 'c' * 64)
            p.write_text('[]')
            with self.assertRaises(ValueError): m.existing_url(p, 'c' * 64)


if __name__ == '__main__': unittest.main()
