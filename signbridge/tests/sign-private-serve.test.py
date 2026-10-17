import http.client
import importlib.util
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-private-serve.py'
spec = importlib.util.spec_from_file_location('private_serve', TOOL)
server_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_tool)


class StubParser:
    def predict(self, text):
        return {'status': 'parsed', 'roles': {'actor': text}, 'csl_translation_trained': False}


class PrivateServeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'private').mkdir()
        (root / 'private/index.html').write_text('<title>private-client</title>')
        (root / 'weights.npz').write_bytes(b'not-for-client')
        (root / 'secret.txt').write_text('never serve directory')
        self.token = secrets.token_urlsafe(32)
        self.server = server_tool.make_server(StubParser(), root, self.token, port=0, rate_limit=3)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path='/v1/understand', body=None, headers=None, method='POST'):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        data = json.dumps({'text': '我帮你'}) if body is None else body
        fields = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        fields.update(headers or {})
        conn.request(method, path, data.encode('utf-8') if method == 'POST' else None, fields)
        response = conn.getresponse()
        result = (response.status, dict(response.headers), response.read())
        conn.close()
        return result

    def test_authenticated_inference_no_cache(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertFalse(json.loads(body)['csl_translation_trained'])

    def test_no_auth_wrong_auth_and_cross_origin_blocked(self):
        for fields, expected in [({'Authorization': ''}, 401), ({'Authorization': 'Bearer bad'}, 401),
                                 ({'Origin': 'https://attacker.example'}, 403),
                                 ({'Host': f'attacker.example:{self.port}'}, 403)]:
            with self.subTest(fields=fields):
                self.assertEqual(self.request(headers=fields)[0], expected)

    def test_same_origin_cors_is_explicit(self):
        origin = f'http://127.0.0.1:{self.port}'
        code, headers, _ = self.request(headers={'Origin': origin})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], origin)
        self.assertNotIn('Access-Control-Allow-Credentials', headers)

    def test_only_explicit_extension_origins_may_infer(self):
        origin = 'chrome-extension://' + 'a' * 32
        self.assertEqual(self.request(headers={'Origin': origin})[0], 403)
        self.server.extension_origins.add(origin)
        code, headers, _ = self.request(headers={'Origin': origin})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], origin)
        self.assertEqual(self.request(headers={'Origin': 'chrome-extension://' + 'b' * 32})[0], 403)

    def test_no_directory_dataset_or_model_routes(self):
        for path in ['/', '/weights.npz', '/secret.txt', '/private/../secret.txt', '/private/%2e%2e/secret.txt', '/v1/lexicon', '/v1/understand?export=all']:
            self.assertEqual(self.request(path=path, method='GET')[0], 404)
        self.assertEqual(self.request(path='/private/index.html', method='GET')[0], 200)

    def test_size_json_type_fields_and_rate_limits(self):
        for body, expected in [('x' * 8193, 413), ('[1,2]', 400), ('{"text":3}', 400),
                               ('{"text":"我", "dump":true}', 400)]:
            self.assertEqual(self.request(body=body)[0], expected)
        self.assertEqual(self.request(headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request(body='{"text":"' + '我' * 501 + '"}')[0], 400)
        self.assertEqual([self.request()[0] for _ in range(4)], [200, 200, 200, 429])

    def test_cli_rejects_external_bind_or_weak_tokens(self):
        with self.assertRaises(ValueError):
            server_tool.make_server(StubParser(), Path(self.tmp.name), 'short', port=0)


if __name__ == '__main__':
    unittest.main()
