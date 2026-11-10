#!/usr/bin/env python3
"""Host-only serial-console supervisor contract tests using pseudo terminals."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class SerialConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uart owner ")
        self.directory = Path(self.temp.name)
        self.master, self.slave = pty.openpty()
        self.device = os.ttyname(self.slave)
        self.alias = self.directory / "device alias"
        self.alias.symlink_to(self.device)
        binary = self.directory / "picocom"
        binary.write_text('''#!/usr/bin/env python3
import os, select, sys, termios, tty
fd = os.open(sys.argv[-1], os.O_RDWR | os.O_NOCTTY)
tty.setraw(fd)
if os.environ.get("CLIENT_FAIL"): raise SystemExit(7)
print("CLIENT_READY", os.getpid(), flush=True)
while True:
    ready, _, _ = select.select([0, fd], [], [])
    for source in ready:
        data = os.read(source, 4096)
        if not data: raise SystemExit(0)
        os.write(fd if source == 0 else 1, data)
''')
        binary.chmod(0o755)
        self.process_environment = {**os.environ, "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
            "PYTHONPATH": str(ROOT / "Tools"), "FIRMWARE_WORKSPACE_RUNTIME": str(self.directory / "runtime")}
        self.children = []

    def tearDown(self):
        for process in self.children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        os.close(self.master)
        os.close(self.slave)
        self.temp.cleanup()

    def launch(self, device=None, tcp=None, check=False, **kwargs):
        args = [sys.executable, "-m", "firmware_workspace.serial_console", "--device", str(device or self.alias),
                "--baud", "115200", "--session-id", str(uuid.uuid4())]
        args += ["--tcp", str(tcp)] if tcp else []
        args += ["--check"] if check else []
        process = subprocess.Popen(args, cwd=ROOT, env=self.process_environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        self.children.append(process)
        return process

    def ready(self, process):
        deadline = time.monotonic() + 5
        output = b""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.05)
            if ready:
                output += os.read(process.stdout.fileno(), 4096)
                if b"CLIENT_READY" in output:
                    return
            self.assertIsNone(process.poll(), (output, process.stderr.read() if process.poll() is not None else b""))
        self.fail("client did not start")

    def test_alias_contention_and_reopen(self):
        owner = self.launch()
        self.ready(owner)
        contender = self.launch(self.device)
        _, error = contender.communicate(timeout=5)
        self.assertEqual(contender.returncode, 4)
        self.assertIn(b"UART_BUSY", error)
        owner.terminate()
        self.assertEqual(owner.wait(timeout=5), 130)
        reopened = self.launch(self.device)
        self.ready(reopened)
        reopened.terminate()
        self.assertEqual(reopened.wait(timeout=5), 130)
        self.assertFalse((self.directory / "runtime/probes").exists())

    def test_interactive_bidirectional_and_exact_child_reap(self):
        owner = self.launch()
        self.ready(owner)
        owner.stdin.write(b"ipctest\r")
        owner.stdin.flush()
        self.assertTrue(select.select([self.master], [], [], 3)[0])
        self.assertEqual(os.read(self.master, 4096), b"ipctest\r")
        os.write(self.master, b"nsh> hello\r\n")
        self.assertTrue(select.select([owner.stdout], [], [], 3)[0])
        self.assertEqual(os.read(owner.stdout.fileno(), 4096), b"nsh> hello\r\n")
        metadata = next((self.directory / "runtime/uart").glob("*.json"))
        child_pid = json.loads(metadata.read_text())["childPid"]
        owner.send_signal(signal.SIGHUP)
        self.assertEqual(owner.wait(timeout=5), 130)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_supervisor_crash_keeps_inherited_client_lock(self):
        owner = self.launch()
        self.ready(owner)
        metadata = json.loads(next((self.directory / "runtime/uart").glob("*.json")).read_text())
        child_pid = metadata["childPid"]
        try:
            owner.kill()
            owner.wait(timeout=5)
            contender = self.launch(self.device)
            contender.communicate(timeout=5)
            self.assertEqual(contender.returncode, 4, "client must retain flock through the helper exec")
        finally:
            # This exact PID was created by this test; metadata is not used by product cleanup.
            try:
                os.kill(child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def test_prerequisites_and_exit_mapping(self):
        for value in (self.directory, self.directory / "missing", "bad\npath"):
            process = self.launch(value)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 2)
        self.process_environment["CLIENT_FAIL"] = "1"
        process = self.launch()
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 1, "child exit 7 is not UART_BUSY")

    def test_check_only_and_unsafe_runtime(self):
        args = [sys.executable, "-m", "firmware_workspace.serial_console", "--device", self.device,
                "--baud", "115200", "--session-id", str(uuid.uuid4()), "--check"]
        checked = subprocess.run(args, cwd=ROOT, env=self.process_environment, capture_output=True, timeout=5)
        self.assertEqual(checked.returncode, 0)
        self.assertEqual(list((self.directory / "runtime/uart").glob("*.json")), [], "check must not launch a client")
        owner = self.launch()
        self.ready(owner)
        checked = subprocess.run(args, cwd=ROOT, env=self.process_environment, capture_output=True, timeout=5)
        self.assertEqual(checked.returncode, 4)
        owner.terminate()
        owner.wait(timeout=5)
        unsafe = self.directory / "unsafe"
        unsafe.symlink_to(self.directory / "runtime", target_is_directory=True)
        self.process_environment["FIRMWARE_WORKSPACE_RUNTIME"] = str(unsafe)
        checked = subprocess.run(args, cwd=ROOT, env=self.process_environment, capture_output=True, timeout=5)
        self.assertEqual(checked.returncode, 2)
        self.assertNotIn(b"Traceback", checked.stderr)

    def test_tcp_relay_holds_lease_replays_backlog_and_refuses_second_client(self):
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        relay = self.launch(tcp=port)
        deadline, line = time.monotonic() + 5, b""
        while b"serial relay up" not in line and time.monotonic() < deadline:
            if select.select([relay.stdout], [], [], 0.1)[0]:
                line += os.read(relay.stdout.fileno(), 4096)
        self.assertIn(b"serial relay up", line)
        os.write(self.master, b"boot banner\r\n")  # no client yet: kept for the first one
        time.sleep(0.3)
        contender = self.launch(self.device)
        contender.communicate(timeout=5)
        self.assertEqual(contender.returncode, 4, "the relay holds the device lease")
        client = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            received = b""
            while b"boot banner" not in received:
                received += client.recv(4096)
            client.sendall(b"ps\r")
            self.assertTrue(select.select([self.master], [], [], 3)[0])
            self.assertEqual(os.read(self.master, 4096), b"ps\r")
            second = socket.create_connection(("127.0.0.1", port), timeout=3)
            self.assertIn(b"already has a client", second.recv(4096))
            second.close()
        finally:
            client.close()
        relay.terminate()
        self.assertEqual(relay.wait(timeout=5), 130)
        reopened = self.launch(self.device, check=True)
        reopened.communicate(timeout=5)
        self.assertEqual(reopened.returncode, 0, "the lease is released when the relay stops")

    def test_real_terminal_stdin_is_retained(self):
        terminal_master, terminal_slave = pty.openpty()
        args = [sys.executable, "-m", "firmware_workspace.serial_console", "--device", self.device,
                "--baud", "115200", "--session-id", str(uuid.uuid4())]
        child = subprocess.Popen(args, cwd=ROOT, env=self.process_environment, stdin=terminal_slave,
                                 stdout=terminal_slave, stderr=terminal_slave)
        self.children.append(child)
        try:
            deadline = time.monotonic() + 5
            output = b""
            while b"CLIENT_READY" not in output and time.monotonic() < deadline:
                if select.select([terminal_master], [], [], 0.1)[0]:
                    output += os.read(terminal_master, 4096)
            self.assertIn(b"CLIENT_READY", output)
            os.write(terminal_master, b"hello\n")
            self.assertTrue(select.select([self.master], [], [], 3)[0])
            self.assertEqual(os.read(self.master, 4096), b"hello\n")
            child.send_signal(signal.SIGINT)
            self.assertEqual(child.wait(timeout=5), 130)
        finally:
            os.close(terminal_master)
            os.close(terminal_slave)


if __name__ == "__main__":
    unittest.main()
