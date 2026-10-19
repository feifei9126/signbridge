#!/usr/bin/env python3
"""Local-only, authenticated semantic inference with a shared process quota. Never serves corpora or weights."""
import argparse
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit


class LimitedServer(ThreadingHTTPServer):
    daemon_threads = True

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Avoid traceback/request text or token leakage into server logs.
        pass


def static_client_resource(target):
    """Serve exact allowlisted files, with one non-sensitive scope selector on the page."""
    parsed = urlsplit(target)
    resources = {
        '/private/index.html': ('index.html', 'text/html; charset=utf-8'),
        '/private/client.js': ('client.js', 'text/javascript; charset=utf-8'),
        '/private/client.css': ('client.css', 'text/css; charset=utf-8'),
    }
    if parsed.path not in resources:
        return None
    if parsed.path == '/private/index.html' and parsed.query in ('', 'scope=1'):
        return resources[parsed.path]
    if not parsed.query:
        return resources[parsed.path]
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = 'SignBridgePrivate'
    sys_version = ''
    timeout = 5

    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, *args):
        pass

    def permitted_origin(self):
        port = self.server.server_port
        allowed = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'} | self.server.extension_origins
        origin = self.headers.get('Origin')
        return origin is None or origin in allowed

    def trusted_request(self):
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        return len(self.headers.get_all('Host', [])) == 1 and self.headers.get('Host') in expected and self.permitted_origin()

    def send(self, status, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-RateLimit-Scope', 'process')
        if status == 429:
            self.send_header('Retry-After', '60')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' http://127.0.0.1:*; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        origin = self.headers.get('Origin')
        if origin and self.permitted_origin():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.trusted_request():
            return self.send(403, {'error': 'forbidden_origin_or_host'})
        # Exact allowlist only. No URL decoding, filesystem joins from user paths,
        # directory listings, source maps, model or dataset downloads.
        entry = static_client_resource(self.path)
        if not entry:
            return self.send(404, {'error': 'not_found'})
        path = self.server.client_root / 'private' / entry[0]
        if not path.is_file() or path.is_symlink():
            return self.send(404, {'error': 'not_found'})
        body = path.read_bytes()
        if entry[0] == 'index.html':
            body, count = re.subn(rb'<html(?=[\s>])', b'<html data-signbridge-service="true"', body, count=1)
            if count != 1:
                return self.send(404, {'error': 'invalid_client_page'})
        return self.send(200, body, entry[1])

    def do_OPTIONS(self):
        if not self.trusted_request() or self.path != '/v1/understand':
            return self.send(403, {'error': 'forbidden_origin_or_host'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', 'null'))
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'POST')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        if not self.trusted_request():
            return self.send(403, {'error': 'forbidden_origin_or_host'})
        if self.path != '/v1/understand':
            return self.send(404, {'error': 'not_found'})
        values = self.headers.get_all('Authorization', [])
        expected = 'Bearer ' + self.server.token
        if len(values) != 1 or len(values[0]) > 256 or not hmac.compare_digest(values[0].encode('utf-8'), expected.encode('utf-8')):
            return self.send(401, {'error': 'unauthorized'})
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,8}', lengths[0]):
            return self.send(400, {'error': 'invalid_length'})
        size = int(lengths[0])
        if size > 8192:
            return self.send(413, {'error': 'request_too_large'})
        if self.headers.get_content_type() != 'application/json':
            return self.send(415, {'error': 'json_required'})
        try:
            body = json.loads(self.rfile.read(size).decode('utf-8'))
            if not isinstance(body, dict) or set(body) != {'text'} or not isinstance(body['text'], str) or not 1 <= len(body['text']) <= 500:
                raise ValueError('payload')
        except (ValueError, UnicodeError, RecursionError):
            return self.send(400, {'error': 'invalid_payload'})
        with self.server.guard:
            now = time.monotonic()
            while self.server.requests and self.server.requests[0] < now - 60:
                self.server.requests.popleft()
            if len(self.server.requests) >= self.server.rate_limit:
                return self.send(429, {'error': 'rate_limited'})
            if not self.server.inference.acquire(blocking=False):
                return self.send(503, {'error': 'busy'})
            self.server.requests.append(now)
        try:
            result = self.server.parser.predict(body['text'])
        except Exception:
            return self.send(500, {'error': 'inference_failed'})
        finally:
            self.server.inference.release()
        return self.send(200, result)


def make_server(parser, client_root, token, port=8770, origins=(), rate_limit=60):
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,128}', token):
        raise ValueError('Use a random per-session token of at least 40 URL-safe characters')
    if any(not re.fullmatch(r'chrome-extension://[a-p]{32}', origin) for origin in origins):
        raise ValueError('Only exact Chrome extension origins may be added')
    server = LimitedServer(('127.0.0.1', port), Handler)
    server.parser, server.client_root, server.token = parser, Path(client_root).resolve(), token
    server.extension_origins, server.rate_limit = set(origins), rate_limit
    server.slots, server.inference = threading.BoundedSemaphore(12), threading.BoundedSemaphore(2)
    server.guard, server.requests = threading.Lock(), deque()
    return server


def load_parser(model, scope_experiment=False, unit_candidates=None):
    tool = 'sign-csl-scope.py' if scope_experiment else 'sign-csl-learned.py'
    spec = importlib.util.spec_from_file_location('csl_service_model', Path(__file__).with_name(tool))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not scope_experiment:
        if unit_candidates is not None:
            raise ValueError('Unit evidence requires explicit scope experiment')
        return module.load_model(model)
    evidence = []
    if unit_candidates is not None:
        evidence = load_unit_candidate_evidence(unit_candidates)
    return module.ScopeParser(module.base.load_model(model), evidence)


def load_unit_candidate_evidence(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5000000:
        raise ValueError('Candidate evidence must be a regular file under 5 MB')
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid candidate evidence JSON') from error
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('Candidate evidence must be a list of at most 1000 rows')
    ids, text_counts, evidence = set(), {}, []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Candidate evidence row must be an object')
        candidate_id, text = row.get('id'), row.get('proposed_text')
        if (not isinstance(candidate_id, str) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', candidate_id) or
                candidate_id in ids):
            raise ValueError('Candidate evidence ID is invalid or duplicated')
        if (not isinstance(text, str) or not 1 <= len(text) <= 80 or
                text != text.strip() or not text.isprintable()):
            raise ValueError('Candidate evidence text is invalid')
        for field in ('human_approved', 'word_boundaries_verified', 'training_ready',
                      'model_training_ready'):
            if field in row and row[field] is not False:
                raise ValueError('Candidate evidence contains an approved state')
        text_counts[text] = text_counts.get(text, 0) + 1
        if text_counts[text] > 8:
            raise ValueError('Candidate evidence exceeds the per-text response limit')
        ids.add(candidate_id)
        evidence.append({'id': candidate_id, 'proposed_text': text})
    return evidence


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--client', type=Path, required=True)
    ap.add_argument('--port', type=int, default=8770)
    ap.add_argument('--allow-extension', action='append', default=[])
    ap.add_argument('--scope-experiment', action='store_true')
    ap.add_argument('--unit-candidates', type=Path)
    args = ap.parse_args()
    parser = load_parser(args.model, args.scope_experiment, args.unit_candidates)
    token = secrets.token_urlsafe(32)
    with make_server(parser, args.client, token, args.port, args.allow_extension) as server:
        print(f'SignBridge private client: http://127.0.0.1:{server.server_port}/private/index.html', flush=True)
        print('Session token (terminal only; expires on restart): ' + token, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
