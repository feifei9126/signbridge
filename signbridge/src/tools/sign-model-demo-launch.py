"""Launch the packaged Mac Demo with its already-installed pinned local runtime."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.parse import urlsplit
import webbrowser


def existing_url(state, checkpoint_sha256):
    old = json.loads(Path(state).read_text())
    if not isinstance(old, dict): raise ValueError('Invalid saved state')
    url = urlsplit(old['url'])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/demo/model.html'
            or url.username or url.password or url.query or url.fragment or not url.port
            or not isinstance(old.get('instance'), str) or len(old['instance']) < 16):
        raise ValueError('Invalid saved local URL')
    with urlopen(f'http://127.0.0.1:{url.port}/health', timeout=1) as response: health = json.load(response)
    if not isinstance(health, dict): raise ValueError('Invalid local health response')
    if health.get('instance') != old['instance'] or health.get('checkpoint_sha256') != checkpoint_sha256:
        raise ValueError('Different local process')
    return old['url']


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--state-file', type=Path, default=root / 'running-service.json')
    args = parser.parse_args()
    config = root / 'model-config.json'
    settings = json.loads(config.read_text())
    python = root / settings['runtime']
    if not python.is_file():
        print('Pinned local runtime missing. Keep the documented sibling runtime directory beside this Demo.', file=sys.stderr)
        print('See README.md in this package.', file=sys.stderr)
        sys.exit(2)
    state = args.state_file
    try:
        url = existing_url(state, settings['checkpoint_sha256'])
        print('SignBridge model Demo: ' + url, flush=True)
        if not args.no_open: webbrowser.open(url, new=2)
        return
    except (OSError, ValueError, KeyError): pass
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
    command = [str(python), str(root / 'tools/sign-model-demo-serve.py'), '--config', str(config), '--state-file', str(state)]
    if args.no_open: command.append('--no-open')
    os.execve(str(python), command, environment)


if __name__ == '__main__': main()
