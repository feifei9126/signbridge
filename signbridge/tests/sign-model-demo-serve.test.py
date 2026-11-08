"""Same-origin model demo keeps learning artifacts private and motion gates distinct."""
import http.client
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-model-demo-serve.py'


def module():
    spec = importlib.util.spec_from_file_location('model_demo_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class PlanTests(unittest.TestCase):
    def test_refusal_scope_and_direction_never_trigger_partial_motion(self):
        m = module(); catalog = [{'id': 'a', 'text': '我', 'source': 'experimental', 'human_approved': True,
                                  'approval_scope': 'motion_quality_only', 'semantic_status': 'unverified'}]
        for p in [{'status': 'abstained', 'roles': {}},
                  {'status': 'parsed', 'roles': {'actor': '我', 'predicate': '帮', 'patient': '你'}, 'operators': []},
                  {'status': 'parsed', 'roles': {'actor': '我', 'predicate': '去', 'negation': '不'}, 'operators': ['negation:不']}]:
            result = m.motion_plan('我帮你', p, catalog)
            self.assertEqual(result['items'], [])
            self.assertFalse(result['csl_translation_verified'])
            self.assertFalse(result['training_ready'])

    def test_exact_label_is_reference_preview_not_semantic_certification(self):
        m = module(); catalog = [{'id': 'a', 'text': '通知', 'source': 'experimental', 'human_approved': True,
                                  'approval_scope': 'motion_quality_only', 'semantic_status': 'unverified'}]
        result = m.motion_plan('通知', {'status': 'parsed', 'roles': {'predicate': '通知'}, 'operators': []}, catalog)
        self.assertEqual(result['items'][0]['id'], 'a')
        self.assertEqual(result['basis'], 'exact_recorded_label_reference')
        self.assertFalse(result['csl_translation_verified'])
        self.assertEqual(m.motion_plan('通知', {'status': 'abstained'}, catalog)['items'], [])


class BuildTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'demo/experimental').mkdir(parents=True)
        poses = [[[0, 0, 0]] * 55] * 2
        sha = lambda value: hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()
        entry = {'id': 'one', 'text': '通知', 'asset': 'experimental/one.json', 'human_approved': True,
                 'motion_approval_id': 'review', 'motion_review_status': 'approved_for_demo_motion',
                 'source_sha256': 'a' * 64, 'fitted_sha256': 'b' * 64}
        clip = {**entry, 'poses': poses}; entry['sha256'] = sha(clip)
        pose_digest = hashlib.sha256(','.join(['0'] * 330).encode()).hexdigest()
        approval = {'id': 'review', 'scope': 'motion_quality_only', 'clips': [
            {'id': 'one', 'source_sha256': 'a' * 64, 'fitted_sha256': 'b' * 64, 'poses_sha256': pose_digest}]}
        index = {'clips': [entry], 'motion_approval': {'id': 'review', 'scope': 'motion_quality_only', 'asset': 'experimental/review.json', 'sha256': sha(approval)}}
        library = {'entries': [{'id': 'one', 'text': '通知', 'source': 'experimental', 'human_approved': True,
            'stability': 'stable', 'metrics': {'finite': True, 'p95_adjacent_rotation_degrees': 1}, 'duration': 1,
            'display_stabilization_profile': 'quaternion-temporal-v1'}]}
        files = {'demo/model.html': b'<html></html>', 'demo/experimental-index.json': json.dumps(index, separators=(',', ':')).encode(),
                 'demo/motion-library-v2.json': json.dumps(library, separators=(',', ':')).encode(),
                 'demo/experimental/review.json': json.dumps(approval, separators=(',', ':')).encode(),
                 'demo/experimental/one.json': json.dumps(clip, separators=(',', ':')).encode()}
        for name, content in files.items(): (root / name).write_bytes(content)
        self.seal(root)

    def seal(self, root):
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name != 'BUILD.json'}
        (root / 'BUILD.json').write_text(json.dumps({'files': files}))

    def test_all_catalog_dependencies_must_be_verified_and_reviewed(self):
        m = module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); self.fixture(root)
            self.assertEqual(m.read_build(root)[1][0]['id'], 'one')
        for mutation in ['missing_index_in_build', 'unapproved_index', 'wrong_approval_id', 'altered_pose', 'resealed_pose']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); self.fixture(root)
                if mutation == 'missing_index_in_build':
                    build = json.loads((root / 'BUILD.json').read_text()); build['files'].pop('demo/experimental-index.json')
                    (root / 'BUILD.json').write_text(json.dumps(build))
                elif mutation in ['unapproved_index', 'wrong_approval_id']:
                    path = root / 'demo/experimental-index.json'; value = json.loads(path.read_text())
                    value['clips'][0]['human_approved' if mutation == 'unapproved_index' else 'motion_approval_id'] = False if mutation == 'unapproved_index' else 'wrong'
                    path.write_text(json.dumps(value)); self.seal(root)
                else:
                    path = root / 'demo/experimental/one.json'; value = json.loads(path.read_text()); value['poses'][0][0][0] = 1
                    path.write_text(json.dumps(value))
                    if mutation == 'resealed_pose':
                        index_path = root / 'demo/experimental-index.json'; index = json.loads(index_path.read_text())
                        index['clips'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                        index_path.write_text(json.dumps(index))
                    self.seal(root)
                with self.assertRaises(ValueError): m.read_build(root)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.m = module(); self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve(); (self.root / 'demo').mkdir()
        (self.root / 'demo/model.html').write_text('<html>model-demo</html>')
        (self.root / 'weights.pt').write_text('private')
        class Predictor:
            def predict(self, text): return {'input': text, 'prediction': {'status': 'parsed', 'roles': {'actor': text}}}
        self.server = self.m.make_server(Predictor(), self.root, {'demo/model.html'}, [], port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse(); result = response.status, dict(response.headers), response.read(); conn.close(); return result

    def test_static_allowlist_no_weights_directories_or_traversal(self):
        self.assertEqual(self.request('/demo/model.html')[0], 200)
        for path in ['/weights.pt', '/', '/demo/', '/demo/../weights.pt', '/%2e%2e/weights.pt', '/demo/model.html?x=1']:
            self.assertEqual(self.request(path)[0], 404)

    def test_same_origin_session_and_authenticated_model_inference(self):
        code, _, body = self.request('/v1/demo-session'); self.assertEqual(code, 200)
        token = json.loads(body)['token']
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
        code, headers, body = self.request('/v1/understand', 'POST', json.dumps({'text': '我'}), headers)
        self.assertEqual(code, 200); self.assertEqual(json.loads(body)['input'], '我')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("connect-src 'self' blob:", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/v1/understand', 'POST', '{}', {'Content-Type': 'application/json'})[0], 401)

    def test_only_configured_extension_gets_cors_session_and_preflight(self):
        origin = 'chrome-extension://' + 'a' * 32
        self.server.extension_origins = frozenset([origin])
        headers = {'Origin': origin, 'Sec-Fetch-Site': 'cross-site'}
        code, response, body = self.request('/v1/demo-session', headers=headers)
        self.assertEqual(code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], origin)
        self.assertEqual(json.loads(body)['protocol'], 'signbridge-model-demo-v1')
        token = json.loads(body)['token']
        code, response, _ = self.request('/v1/understand', 'OPTIONS', headers={**headers,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(code, 204)
        self.assertEqual(response['Access-Control-Allow-Origin'], origin)
        self.assertIn('Authorization', response['Access-Control-Allow-Headers'])
        code, _, _ = self.request('/v1/understand', 'POST', json.dumps({'text': '我'}), {
            **headers, 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        for wrong in ['https://evil.example', 'chrome-extension://' + 'b' * 32, origin + '.evil']:
            code, response, _ = self.request('/v1/demo-session', headers={'Origin': wrong})
            self.assertEqual(code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', response)
        self.assertEqual(self.request('/v1/demo-session', headers={**headers, 'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/v1/understand', 'OPTIONS', headers={**headers,
            'Access-Control-Request-Method': 'DELETE'})[0], 403)
        self.assertEqual(self.request('/weights.pt', 'OPTIONS', headers={**headers,
            'Access-Control-Request-Method': 'POST'})[0], 403)

    def test_invalid_extension_configuration_rejected(self):
        for origins in ['*', ['https://evil.example'], ['chrome-extension://bad']]:
            with self.assertRaises(ValueError):
                self.m.make_server(None, self.root, set(), [], extension_origins=origins)

    def test_bad_origin_host_and_oversized_payload_rejected(self):
        for headers in [{'Origin': 'https://evil.example'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.request('/v1/demo-session', headers=headers)[0], 403)
        token = json.loads(self.request('/v1/demo-session')[2])['token']
        for payload in [{'text': '我' * 201}, {'text': 4}, {'text': '我', 'path': 'weights.pt'}]:
            code, _, _ = self.request('/v1/understand', 'POST', json.dumps(payload),
                {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            self.assertEqual(code, 400)


if __name__ == '__main__': unittest.main()
