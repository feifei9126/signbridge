"""Serve the built SignBridge Demo on localhost and open it in a browser."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser


def main():
    here = Path(__file__).resolve().parent
    default = here if (here / 'demo/index.html').is_file() else here.parents[1] / 'dist'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=default)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not (directory / 'demo/index.html').is_file():
        parser.error('Built Demo missing. Run npm run build from the extension project first.')
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        url = 'http://127.0.0.1:{}/demo/index.html'.format(server.server_port)
        print('SignBridge Demo: ' + url, flush=True)
        print('Keep this terminal open; Ctrl+C stops the local server.', flush=True)
        if not args.no_open:
            webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
