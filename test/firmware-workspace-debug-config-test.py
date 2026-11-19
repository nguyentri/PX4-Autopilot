#!/usr/bin/env python3
"""Cortex-Debug in-memory resolution unit tests for firmware workspace."""

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from firmware_workspace.artifacts import compute_sha256, create_receipt
from firmware_workspace.contracts import EXIT_BLOCKED_RECOVERY, EXIT_OK
from firmware_workspace.debug import cmd_debug_config

FIXTURE_DIR = REPO_ROOT / "build" / "test-dbg-fixtures"


class MockArgs:
    def __init__(self, selection: str, receipt: str, serial: str = None, json: bool = True, core: str = None):
        self.selection = selection
        self.receipt = receipt
        self.serial = serial
        self.json = json
        self.core = core


class TestFirmwareWorkspaceDebugConfig(unittest.TestCase):
    """Test in-memory Cortex-Debug configuration generation and safety attributes."""

    @classmethod
    def setUpClass(cls):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR, ignore_errors=True)

    def test_01_generate_cr8_0_attach_config(self):
        """Verify generated configuration contains correct device, commands, and SVD."""
        sel_file = FIXTURE_DIR / "cr8_0.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "rzv2h-default",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {"family": "px4", "target": "renesas_rdk-rzv2h_default", "mode": "incremental"},
            "debug": {"mode": "attach"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "firmware.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 40)
        sha = compute_sha256(dummy_art)

        rec_file = create_receipt(
            run_id="run-dbg-001", family="px4", board="rdk-rzv2h", core="cr8_0",
            selection_id="rzv2h-default",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": sha, "size": 44}],
            status="committed", target=sel["build"]["target"]
        )

        launch_json = REPO_ROOT / ".vscode" / "launch.json"
        orig_mtime = launch_json.stat().st_mtime if launch_json.is_file() else None

        import io
        old_stdout = sys.stdout
        captured = io.StringIO()
        sys.stdout = captured
        try:
            rc = cmd_debug_config(MockArgs(str(sel_file), str(rec_file), serial="1061999999"))
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, EXIT_OK)
        res = json.loads(captured.getvalue())
        self.assertEqual(res["status"], "ok")
        cfg = res["data"]["configuration"]

        self.assertEqual(cfg["type"], "cortex-debug")
        self.assertEqual(cfg["request"], "attach")
        self.assertEqual(cfg["servertype"], "jlink")
        self.assertEqual(cfg["device"], "R9A09G057H44_R8_0")
        self.assertEqual(cfg["serialNumber"], "1061999999")
        self.assertIn("monitor halt", cfg["overrideAttachCommands"])
        self.assertIn("monitor halt", cfg["overrideRestartCommands"])
        for cmd in cfg["overrideAttachCommands"]:
            self.assertNotIn("reset", cmd.lower())

        if orig_mtime is not None:
            self.assertEqual(launch_json.stat().st_mtime, orig_mtime)

    def test_02_block_debug_on_cm33(self):
        """Verify CM33 debug attempt returns blocked result."""
        sel_file = FIXTURE_DIR / "cm33.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "cm33-dbg",
            "board": "rdk-rzv2h",
            "core": "cm33",
            "build": {"family": "px4", "target": "renesas_rdk-rzv2h-io-cm33_default", "mode": "clean"},
            "debug": {"mode": "attach"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "cm33.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 40)

        rec_file = create_receipt(
            run_id="run-cm33-dbg", family="px4", board="rdk-rzv2h", core="cm33",
            selection_id="cm33-dbg",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": compute_sha256(dummy_art), "size": 44}],
            status="committed"
        )

        rc = cmd_debug_config(MockArgs(str(sel_file), str(rec_file)))
        self.assertEqual(rc, EXIT_BLOCKED_RECOVERY)

    def test_03_multicore_group_debug_config(self):
        """Verify multicore group debug config generates appropriate target device per core."""
        sel_file = FIXTURE_DIR / "group.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "rzv-px4-dualcr8",
            "board": "rdk-rzv2h",
            "core": "multicore",
            "group": "rzv-px4-dualcr8",
            "build": {"family": "px4", "mode": "incremental"},
            "debug": {"mode": "attach"}
        }
        sel_file.write_text(json.dumps(sel))

        art0 = FIXTURE_DIR / "cr8_0.elf"
        art0.write_bytes(b"\x7fELF" + b"\x00" * 40)
        art1 = FIXTURE_DIR / "cr8_1.elf"
        art1.write_bytes(b"\x7fELF" + b"\x00" * 40)

        rec_file = create_receipt(
            run_id="run-grp-dbg", family="px4", board="rdk-rzv2h", core="multicore",
            selection_id="rzv-px4-dualcr8",
            artifacts=[
                {"path": str(art0.relative_to(REPO_ROOT)), "sha256": compute_sha256(art0), "size": 44, "core": "cr8_0"},
                {"path": str(art1.relative_to(REPO_ROOT)), "sha256": compute_sha256(art1), "size": 44, "core": "cr8_1"},
            ],
            status="committed",
            group="rzv-px4-dualcr8"
        )

        import io
        for core, exp_device in [("cr8_0", "R9A09G057H44_R8_0"), ("cr8_1", "R9A09G057H44_R8_1")]:
            old_stdout = sys.stdout
            captured = io.StringIO()
            sys.stdout = captured
            try:
                rc = cmd_debug_config(MockArgs(str(sel_file), str(rec_file), core=core))
            finally:
                sys.stdout = old_stdout

            self.assertEqual(rc, EXIT_OK)
            res = json.loads(captured.getvalue())
            self.assertEqual(res["status"], "ok")
            cfg = res["data"]["configuration"]
            self.assertEqual(cfg["device"], exp_device)
            self.assertIn(core, cfg["executable"])


if __name__ == "__main__":
    unittest.main()
