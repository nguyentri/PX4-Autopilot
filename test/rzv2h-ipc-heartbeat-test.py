#!/usr/bin/env python3
"""Compile the rzv2h_heartbeat liveness state with the production v3 codec and run its host fixture."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "boards/renesas/rdk-rzv2h/ipc_heartbeat"


class IpcHeartbeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="rzv2h-heartbeat-")
        cls.binary = Path(cls.scratch.name) / "heartbeat-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT / "src"),
            "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-ipc-heartbeat-host-fixture.cpp"),
            str(ROOT / "src/apps/protocol.cpp"), "-o", str(cls.binary),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_monitor_fixture(self):
        result = subprocess.run([str(self.binary)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ipc heartbeat monitor: ok", result.stdout)

    def test_module_never_publishes_or_commands(self):
        source = (MODULE / "ipc-heartbeat.cpp").read_text()
        monitor = (MODULE / "ipc-heartbeat-monitor.hpp").read_text()
        for text in (source, monitor):
            for forbidden in ("<uORB/", "uORB::", "orb_advertise", "orb_publish", "px4io_status_s"):
                self.assertNotIn(forbidden, text)
            self.assertNotIn("encode(", text.replace("encode_heartbeat(", ""))
        self.assertIn("CONFIG_RZV_IPC_ROLE_INITIATOR", source)
        self.assertIn('MAIN rzv2h_heartbeat', (MODULE / "CMakeLists.txt").read_text())

    def test_only_initiator_recovers(self):
        source = (MODULE / "ipc-heartbeat.cpp").read_text()
        self.assertEqual(source.count("_link.recover()"), 1)
        self.assertIn("recover_due(now)", source)


if __name__ == "__main__":
    unittest.main()
