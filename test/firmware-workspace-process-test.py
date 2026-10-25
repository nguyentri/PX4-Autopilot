#!/usr/bin/env python3
"""Process lifecycle and environment isolation unit tests for firmware workspace."""

import os
import contextlib
import io
import select
import signal
import subprocess
import tempfile
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from firmware_workspace.process import ManagedProcess, get_scrubbed_env


class TestFirmwareWorkspaceProcess(unittest.TestCase):
    """Test process execution, environment scrubbing, and cancellation."""

    def test_01_environment_scrubbing(self):
        """Verify hostile compiler environment variables are stripped."""
        test_env = {
            "CC": "gcc-custom",
            "CMAKE_C_COMPILER": "clang",
            "CFLAGS": "-O3",
            "PATH": "/usr/bin:/bin",
            "CUSTOM_VAR": "preserved"
        }
        old_env = os.environ.copy()
        try:
            os.environ.update(test_env)
            scrubbed = get_scrubbed_env()
            self.assertNotIn("CC", scrubbed)
            self.assertNotIn("CMAKE_C_COMPILER", scrubbed)
            self.assertNotIn("CFLAGS", scrubbed)
            self.assertEqual(scrubbed.get("CUSTOM_VAR"), "preserved")
            self.assertEqual(scrubbed.get("GIT_SUBMODULES_ARE_EVIL"), "1")
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_02_managed_process_execution(self):
        """Verify basic command execution and output capture."""
        proc = ManagedProcess(["echo", "hello-firmware"])
        rc, out, err = proc.run(stream_stderr=False)
        self.assertEqual(rc, 0)
        self.assertIn("hello-firmware", out)

    def test_03_managed_process_cancellation(self):
        """Verify graceful termination of long-running command."""
        proc = ManagedProcess(["sleep", "10"])
        start = time.time()
        # Launch asynchronously in thread or run with short timeout
        with self.assertRaises(TimeoutError):
            proc.run(timeout=0.2)
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0)
        # Ensure process has terminated
        self.assertIsNotNone(proc.proc.poll())

    def test_04_logs_arrive_before_child_exits(self):
        script = ('from firmware_workspace.process import ManagedProcess\n'
                  'import sys\n'
                  'ManagedProcess([sys.executable,"-u","-c",'
                  '"import time; print(\\\"ready\\\",flush=True); time.sleep(0.8)"]).run()')
        env = dict(os.environ, PYTHONPATH=str(TOOLS_DIR))
        child = subprocess.Popen([sys.executable, '-u', '-c', script], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            ready, _, _ = select.select([child.stderr], [], [], 2)
            self.assertTrue(ready)
            self.assertIn(b'ready', child.stderr.readline())
            self.assertIsNone(child.poll())
            self.assertEqual(child.wait(timeout=3), 0)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()

    def test_05_signal_cancels_owned_descendant_even_after_leader_exits(self):
        # The descendant ignores TERM and holds the output pipe. Cancellation
        # must still kill the owned group when its leader exits first.
        from firmware_workspace.locks import process_start
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            descendant = 'import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(os.getpid(),flush=True); time.sleep(30)'
            leader = f'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-u","-c",{descendant!r}]); open({str(pidfile)!r},"w").write(str(p.pid)); time.sleep(30)'
            script = f'from firmware_workspace.process import ManagedProcess\nimport sys\nr=ManagedProcess([sys.executable,"-u","-c",{leader!r}]).run()\nraise SystemExit(r[0])'
            child = subprocess.Popen([sys.executable, '-u', '-c', script], env=dict(os.environ, PYTHONPATH=str(TOOLS_DIR)),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            descendant_pid = None
            try:
                ready, _, _ = select.select([child.stderr], [], [], 5)
                self.assertTrue(ready)
                descendant_pid = int(child.stderr.readline())
                child.send_signal(signal.SIGTERM)
                self.assertEqual(child.wait(timeout=8), 130)
                stat = Path(f'/proc/{descendant_pid}/stat')
                # A container init may reap a killed orphan later; zombie has
                # no held pipes, memory, or running firmware command.
                self.assertTrue(not stat.exists() or stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z')
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=8)
                if descendant_pid:
                    try:
                        os.kill(descendant_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.stdout.close()
                child.stderr.close()


if __name__ == "__main__":
    unittest.main()
