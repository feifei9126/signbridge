"""Same-origin loopback UI + real pinned semantic model; learning files stay private."""
import argparse
from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
import importlib.util
import json
import mimetypes
import math
from pathlib import Path
import re
import secrets
import os
import threading
import time
import webbrowser


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


private = load('sign-private-serve.py')
GATES = {'research_only': True, 'human_approved': False, 'semantics_approved': False,
         'training_ready': False, 'model_training_ready': False, 'csl_translation_verified': False}


def motion_plan(text, prediction, catalog):
    plan = {**GATES, 'items': [], 'basis': 'none', 'gaps': [], 'complete_CSL_expression': False}
    if prediction.get('status') != 'parsed': plan['gaps'] = ['model_abstained']; return plan
    roles = prediction.get('roles', {})
    if prediction.get('operators') or roles.get('negation') or roles.get('modal'):
        plan['gaps'] = ['operator_motion_unverified']; return plan
    if roles.get('patient') in ('我', '你', '他', '她', '我们', '你们', '他们'):
        plan['gaps'] = ['directional_motion_unverified']; return plan
    # Complete recorded labels only: never partial word stitching or mirrored help.
    normalized = text.strip().rstrip('。.!！?？')
    entry = next((c for c in catalog if c['text'] == normalized and c.get('human_approved') is True
                  and c.get('approval_scope') == 'motion_quality_only'), None)
    if entry:
        plan.update(items=[{'id': entry['id'], 'source': 'experimental', 'matchedText': entry['text']}],
                    basis='exact_recorded_label_reference')
    else:
        plan['gaps'] = ['no_complete_reviewed_motion']
    return plan


def read_build(directory):
    directory = Path(directory).absolute()
    if directory.is_symlink(): raise ValueError('Build root symlink rejected')
    build = json.loads((directory / 'BUILD.json').read_text())
    files = build.get('files', {})
    if not files: raise ValueError('Verified BUILD.json required')
    allowed = set()
    for name, digest in files.items():
        if not name.startswith(('demo/', 'avatar/')) or Path(name).suffix not in ('.html', '.css', '.js', '.json', '.glb', '.jpg'): continue
        path = directory / name
        if Path(name).is_absolute() or '..' in Path(name).parts or any(p.is_symlink() for p in [path, *path.parents]) or not path.is_file():
            raise ValueError('Invalid public asset path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise ValueError('Public asset digest differs: ' + name)
        allowed.add(name)
    def checked(name):
        if 'demo/' + name not in allowed: raise ValueError('Required motion metadata missing from verified build: ' + name)
        return (directory / 'demo' / name).read_bytes()
    index = json.loads(checked('experimental-index.json'))
    approval = index['motion_approval']
    approval_bytes = checked(approval['asset'])
    if hashlib.sha256(approval_bytes).hexdigest() != approval['sha256']: raise ValueError('Approval digest differs')
    record = json.loads(approval_bytes)
    if (record.get('scope') != 'motion_quality_only' or record.get('id') != approval.get('id')
            or approval.get('scope') != record['scope']): raise ValueError('Approval scope/id differs')
    reviewed = {p['id']: p for p in record['clips']}
    entries = {p['id']: p for p in index['clips']}
    library = json.loads(checked('motion-library-v2.json'))
    eligible = [p for p in library['entries'] if p['source'] == 'experimental' and p.get('human_approved') is True
                and p['id'] in reviewed and p['stability'] == 'stable' and p['metrics']['finite'] is True
                and p['metrics']['p95_adjacent_rotation_degrees'] <= 13.5 and p['duration'] <= 14]
    # Prefer short labels for an honest independent reference catalog.
    eligible.sort(key=lambda p: (len(p['text']) > 4, p['metrics']['p95_adjacent_rotation_degrees'], p['id']))
    catalog = []
    for item in eligible[:8]:
        entry = entries[item['id']]
        if (entry.get('human_approved') is not True or entry.get('motion_approval_id') != record['id']
                or entry.get('motion_review_status') != 'approved_for_demo_motion' or entry.get('text') != item['text']
                or entry['source_sha256'] != reviewed[item['id']]['source_sha256']
                or entry['fitted_sha256'] != reviewed[item['id']]['fitted_sha256']): raise ValueError('Motion source/approval binding differs')
        clip_bytes = checked(entry['asset'])
        if hashlib.sha256(clip_bytes).hexdigest() != entry['sha256']: raise ValueError('Reviewed motion bytes differ')
        clip = json.loads(clip_bytes)
        keys = ['id', 'text', 'human_approved', 'motion_approval_id', 'motion_review_status', 'source_sha256', 'fitted_sha256']
        if any(clip.get(k) != entry.get(k) for k in keys): raise ValueError('Clip approval metadata differs')
        poses = clip.get('poses')
        if (not isinstance(poses, list) or len(poses) < 2 or any(not isinstance(frame, list) or len(frame) != 55
                or any(not isinstance(v, list) or len(v) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in frame)
                for frame in poses)):
            raise ValueError('Invalid native pose frames')
        digest_input = ','.join(str(math.floor(x * 1e6 + .5)) for frame in poses for vector in frame for x in vector)
        if hashlib.sha256(digest_input.encode()).hexdigest() != reviewed[item['id']]['poses_sha256']:
            raise ValueError('Reviewed pose binding differs')
        catalog.append({'id': item['id'], 'text': item['text'], 'source': 'experimental',
            'human_approved': True, 'approval_scope': 'motion_quality_only', 'semantic_status': 'unverified',
            'sha256': entry['sha256'], 'source_sha256': entry['source_sha256'], 'fitted_sha256': entry['fitted_sha256'],
            'duration': item['duration'], 'stability': item['stability'], 'display_profile': item['display_stabilization_profile'],
            'raw_metrics': item['metrics'], 'approval_id': approval['id']})
    if not catalog: raise ValueError('No reviewed stable references')
    return allowed, catalog


class Predictor:
    def __init__(self, config):
        self.tool = load('sign-csl-semantic-consistency.py')
        root = Path(config['root'])
        self.runtime = self.tool.c.load_runtime(root / config['prepared'], root / config['results'], root / config['encoder'])
        self.checkpoint_sha256 = self.runtime['checkpoint_sha256']

    def predict(self, text):
        output = self.tool.predict_texts(self.runtime, [text])[0]
        raw = output['result']
        return {**GATES, 'input': text, 'checkpoint_sha256': self.checkpoint_sha256,
                'prediction': raw['prediction'], 'raw_kind': raw.get('raw_kind'), 'raw_BIO': raw.get('raw_BIO'),
                'original_prediction': raw.get('original_prediction'),
                'kind_resolved_by_explicit_structure': raw.get('kind_resolved_by_explicit_structure', False),
                'inference_ms': output['timing']['batch_end_to_end_seconds'] * 1000}


class Handler(BaseHTTPRequestHandler):
    server_version = 'SignBridgeModelDemo'
    sys_version = ''

    def setup(self):
        self.request.settimeout(8); super().setup()

    def log_message(self, *args): pass

    def trusted(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        origins = {f'http://{h}' for h in hosts}
        return (len(self.headers.get_all('Host', [])) == 1 and self.headers['Host'] in hosts
                and self.headers.get('Origin') in origins | {None}
                and self.headers.get('Sec-Fetch-Site') not in ('cross-site', 'same-site'))

    def send(self, status, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self' blob:; frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def do_GET(self):
        if not self.trusted(): return self.send(403, {'error': 'forbidden_origin_or_host'})
        if self.path == '/health': return self.send(200, {'status': 'ok', 'model_loaded': True,
            'instance': self.server.instance, 'checkpoint_sha256': getattr(self.server.predictor, 'checkpoint_sha256', '')})
        if self.path == '/v1/demo-session':
            return self.send(200, {'token': self.server.token, 'catalog': self.server.catalog,
                'checkpoint_sha256': getattr(self.server.predictor, 'checkpoint_sha256', ''), **GATES})
        name = self.path.removeprefix('/')
        if name not in self.server.allowed or self.path != '/' + name: return self.send(404, {'error': 'not_found'})
        path = self.server.directory / name
        if path.is_symlink() or not path.is_file(): return self.send(404, {'error': 'not_found'})
        return self.send(200, path.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream')

    def do_POST(self):
        if not self.trusted(): return self.send(403, {'error': 'forbidden_origin_or_host'})
        if self.path != '/v1/understand': return self.send(404, {'error': 'not_found'})
        auth = self.headers.get_all('Authorization', [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ('Bearer ' + self.server.token).encode()):
            return self.send(401, {'error': 'unauthorized'})
        sizes = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(sizes) != 1 or not re.fullmatch(r'[0-9]{1,6}', sizes[0]):
            return self.send(400, {'error': 'invalid_length'})
        if int(sizes[0]) > 4096: return self.send(413, {'error': 'request_too_large'})
        if self.headers.get_content_type() != 'application/json': return self.send(415, {'error': 'json_required'})
        try:
            body = json.loads(self.rfile.read(int(sizes[0])).decode())
            if not isinstance(body, dict) or set(body) != {'text'} or not isinstance(body['text'], str) or not 1 <= len(body['text']) <= 200:
                raise ValueError('payload')
        except (ValueError, UnicodeError, RecursionError): return self.send(400, {'error': 'invalid_payload'})
        with self.server.guard:
            now = time.monotonic()
            while self.server.requests and self.server.requests[0] < now - 60: self.server.requests.popleft()
            if len(self.server.requests) >= 180: return self.send(429, {'error': 'rate_limited'})
            if not self.server.inference.acquire(blocking=False): return self.send(503, {'error': 'busy'})
            self.server.requests.append(now)
        try:
            result = self.server.predictor.predict(body['text'])
            result['motion_plan'] = motion_plan(body['text'], result['prediction'], self.server.catalog)
        except Exception: return self.send(500, {'error': 'inference_failed'})
        finally: self.server.inference.release()
        return self.send(200, result)


def make_server(predictor, directory, allowed, catalog, port=0):
    server = private.LimitedServer(('127.0.0.1', port), Handler)
    server.slots = threading.BoundedSemaphore(16); server.inference = threading.BoundedSemaphore(1)
    server.guard = threading.Lock(); server.requests = deque(); server.token = secrets.token_urlsafe(32)
    server.predictor = predictor; server.directory = Path(directory); server.allowed = set(allowed); server.catalog = catalog
    server.instance = secrets.token_urlsafe(24)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true'); parser.add_argument('--state-file', type=Path)
    args = parser.parse_args(); config = json.loads(args.config.read_text())
    config['root'] = str(args.config.absolute().parent)
    directory = Path(config['root']) / config['web']
    allowed, catalog = read_build(directory)
    predictor = Predictor(config)
    with make_server(predictor, directory, allowed, catalog, args.port) as server:
        url = f'http://127.0.0.1:{server.server_port}/demo/model.html'
        if args.state_file: args.state_file.write_text(json.dumps({'url': url, 'port': server.server_port, 'pid': os.getpid(),
            'instance': server.instance, 'checkpoint_sha256': predictor.checkpoint_sha256}))
        print('SignBridge model Demo: ' + url, flush=True)
        print('Keep this terminal open. Ctrl+C stops the local service.', flush=True)
        if not args.no_open: webbrowser.open(url, new=2)
        try: server.serve_forever()
        except KeyboardInterrupt: pass


if __name__ == '__main__': main()
