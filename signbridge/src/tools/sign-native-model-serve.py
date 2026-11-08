"""Run the verified model Demo as an owned child of the native Mac launcher."""
import argparse
import errno
import importlib.util
import json
import os
from pathlib import Path
import threading

spec = importlib.util.spec_from_file_location('native_demo_service', Path(__file__).with_name('sign-model-demo-serve.py'))
service = importlib.util.module_from_spec(spec); spec.loader.exec_module(service)


def owned_by(parent_pid):
    return type(parent_pid) is int and parent_pid > 1 and os.getppid() == parent_pid


def bind_server(predictor, directory, allowed, catalog, port, origins):
    try: return service.make_server(predictor, directory, allowed, catalog, port, origins)
    except OSError as error:
        if error.errno != errno.EADDRINUSE or not port: raise
        return service.make_server(predictor, directory, allowed, catalog, 0, origins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state-file', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    if not owned_by(args.parent_pid): parser.error('Parent process identity differs')
    stopped = threading.Event()
    def watch_parent():
        while not stopped.wait(.25):
            # Startup can be blocked in model/asset initialization: terminate this
            # owned process without depending on a server having been created.
            if not owned_by(args.parent_pid): os._exit(0)
    watcher = threading.Thread(target=watch_parent, daemon=True); watcher.start()
    config = json.loads(args.config.read_text()); config['root'] = str(args.config.absolute().parent)
    directory = Path(config['root']) / config['web']
    allowed, catalog = service.read_build(directory)
    origins = list(service.validate_extension_origins(config.get('extension_origins', [])))
    predictor = service.Predictor(config)
    if not owned_by(args.parent_pid): return
    with bind_server(predictor, directory, allowed, catalog, args.port, origins) as server:
        state = {'url': f'http://127.0.0.1:{server.server_port}/demo/model.html', 'port': server.server_port,
                 'pid': os.getpid(), 'parent_pid': args.parent_pid, 'instance': server.instance,
                 'checkpoint_sha256': predictor.checkpoint_sha256, 'protocol': service.PROTOCOL}
        args.state_file.write_text(json.dumps(state))
        args.state_file.chmod(0o600)
        try: server.serve_forever(poll_interval=.2)
        finally: stopped.set()


if __name__ == '__main__': main()
