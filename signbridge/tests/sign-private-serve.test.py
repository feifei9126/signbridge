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
        (root / 'private/index.html').write_text('<!doctype html><html lang="zh"><title>private-client</title></html>')
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

    def test_candidate_evidence_loader_returns_bounded_unreviewed_references(self):
        path = Path(self.tmp.name) / 'candidates.json'
        path.write_text(json.dumps([
            {'id': 'handref-001', 'proposed_text': '你好', 'human_approved': False,
             'word_boundaries_verified': False, 'training_ready': False,
             'source_absolute_path': '/private/source.mp4'}
        ]))
        self.assertEqual(server_tool.load_unit_candidate_evidence(path), [
            {'id': 'handref-001', 'proposed_text': '你好'}
        ])

    def test_candidate_evidence_loader_rejects_ambiguous_or_oversized_rows(self):
        path = Path(self.tmp.name) / 'candidates.json'
        invalid_sets = [
            [{'id': 'duplicate', 'proposed_text': '你好'},
             {'id': 'duplicate', 'proposed_text': '谢谢'}],
            [{'id': 'x' * 129, 'proposed_text': '你好'}],
            [{'id': 'long-text', 'proposed_text': '你' * 81}],
            [{'id': 'approved', 'proposed_text': '你好', 'human_approved': True}],
            [{'id': f'candidate-{n}', 'proposed_text': '你好'} for n in range(9)],
        ]
        for rows in invalid_sets:
            with self.subTest(rows=rows):
                path.write_text(json.dumps(rows))
                with self.assertRaises(ValueError):
                    server_tool.load_unit_candidate_evidence(path)

    def test_candidate_evidence_loader_rejects_symlinked_files(self):
        source = Path(self.tmp.name) / 'source.json'
        source.write_text(json.dumps([{'id': 'safe', 'proposed_text': '你好'}]))
        link = Path(self.tmp.name) / 'linked.json'
        link.symlink_to(source)
        with self.assertRaises(ValueError):
            server_tool.load_unit_candidate_evidence(link)

    def test_authenticated_inference_no_cache(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertFalse(json.loads(body)['csl_translation_trained'])

    def test_health_endpoint_is_read_only_and_cors_limited_to_loopback_pages(self):
        code, headers, body = self.request('/health', method='GET', headers={
            'Authorization': '', 'Origin': f'http://127.0.0.1:{self.port + 1}'
        })
        self.assertEqual(code, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'],
                         f'http://127.0.0.1:{self.port + 1}')
        self.assertEqual(json.loads(body), {'status': 'ok'})
        self.assertEqual(self.request('/health', method='GET', headers={
            'Origin': 'https://attacker.example'
        })[0], 403)
        self.assertEqual(self.request('/health?token=x', method='GET')[0], 404)

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

    def test_rate_limit_is_explicitly_shared_across_connections(self):
        for _ in range(3):
            self.assertEqual(self.request()[0], 200)
        status, headers, _ = self.request()
        self.assertEqual(status, 429)
        self.assertEqual(headers['X-RateLimit-Scope'], 'process')
        self.assertEqual(headers['Retry-After'], '60')

    def test_busy_requests_do_not_spend_the_shared_request_budget(self):
        import concurrent.futures
        started = threading.Barrier(3)
        release = threading.Event()
        class BlockingParser:
            def predict(self, text):
                started.wait(timeout=3)
                release.wait(timeout=3)
                return {'status': 'parsed', 'roles': {}, 'csl_translation_trained': False}
        self.server.parser = BlockingParser()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request) for _ in range(2)]
            try:
                started.wait(timeout=3)
                self.assertEqual(self.request()[0], 503)
            finally:
                release.set()
            self.assertEqual([f.result()[0] for f in futures], [200, 200])
        self.server.parser = StubParser()
        self.assertEqual(self.request()[0], 200)
        self.assertEqual(self.request()[0], 429)

    def test_cli_rejects_external_bind_or_weak_tokens(self):
        with self.assertRaises(ValueError):
            server_tool.make_server(StubParser(), Path(self.tmp.name), 'short', port=0)


    def test_scope_flag_routes_only_exact_client_index_variant(self):
        self.assertEqual(server_tool.static_client_resource('/private/index.html?scope=1'), ('index.html', 'text/html; charset=utf-8'))
        self.assertEqual(server_tool.static_client_resource('/private/index.html'), ('index.html', 'text/html; charset=utf-8'))
        for path in ['/private/index.html?scope=1&token=x', '/private/index.html?scope=0', '/private/client.js?scope=1', '/private/../secret.txt?scope=1']:
            with self.subTest(path=path): self.assertIsNone(server_tool.static_client_resource(path))

    def test_scope_static_route_serves_page_without_broadening_filesystem_allowlist(self):
        status, _, body = self.request('/private/index.html?scope=1', method='GET')
        self.assertEqual(status, 200)
        self.assertIn(b'private-client', body)
        self.assertIn(b'data-signbridge-service="true"', body)
        self.assertEqual(self.request('/secret.txt?scope=1', method='GET')[0], 404)



if __name__ == '__main__':
    unittest.main()
