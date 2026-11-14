import importlib.util
from pathlib import Path
import socket
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'src/tools/sign-native-model-serve.py'


class NativeServeTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('native_model_test', PATH)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def test_parent_must_be_actual_live_parent(self):
        m = self.module()
        with patch.object(m.os, 'getppid', return_value=42):
            self.assertTrue(m.owned_by(42))
            self.assertFalse(m.owned_by(1))
            self.assertFalse(m.owned_by(43))

    def test_busy_preferred_port_uses_new_port_without_touching_listener(self):
        m = self.module()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0)); occupied.listen()
            port = occupied.getsockname()[1]
            with m.bind_server(None, Path('/tmp'), set(), [], port, []) as server:
                self.assertNotEqual(server.server_port, port)
                self.assertEqual(occupied.getsockname()[1], port)


    def test_parent_death_during_blocked_model_initialization_stops_child(self):
        child_code = """import importlib.util,json,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('watchdog_test',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.service.read_build=lambda _:(set(),[])
def blocked(_):
    Path(marker).write_text('entered')
    time.sleep(60)
m.service.Predictor=blocked
parent,config,marker=sys.argv[2:5]
sys.argv=['native','--config',config,'--state-file',marker+'.state','--parent-pid',parent]
m.main()
"""
        controller = """import subprocess,sys,os,time
from pathlib import Path
p=subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],sys.argv[2],str(os.getpid()),sys.argv[3],sys.argv[4]])
Path(sys.argv[5]).write_text(str(p.pid))
while True:time.sleep(1)
"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'config.json';config.write_text(json.dumps({'web':'web'}))
            marker=root/'entered';pidfile=root/'child.pid'; child_pid=None
            parent=subprocess.Popen([sys.executable,'-B','-c',controller,child_code,str(PATH),str(config),str(marker),str(pidfile)])
            try:
                for _ in range(100):
                    if marker.exists() and pidfile.exists():break
                    time.sleep(.05)
                self.assertTrue(marker.exists(),'model initialization fixture did not start')
                child_pid=int(pidfile.read_text())
                parent.kill();parent.wait(timeout=3)
                exited=False
                for _ in range(100):
                    probe=subprocess.run(['ps','-p',str(child_pid),'-o','stat='],capture_output=True,text=True)
                    if probe.returncode or probe.stdout.strip().startswith('Z'):exited=True;break
                    time.sleep(.05)
                self.assertTrue(exited,'model initialization child outlived its dead launcher')
            finally:
                if parent.poll() is None:parent.kill();parent.wait(timeout=3)
                if child_pid:
                    try:os.kill(child_pid,signal.SIGKILL)
                    except ProcessLookupError:pass


if __name__ == '__main__': unittest.main()
