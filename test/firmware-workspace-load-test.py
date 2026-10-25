#!/usr/bin/env python3
"""Guarded loader and address admission unit tests for firmware workspace."""

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from firmware_workspace.artifacts import compute_sha256, create_receipt
from firmware_workspace.contracts import EXIT_BLOCKED_RECOVERY, EXIT_INVALID_INPUT
from firmware_workspace.load import cmd_load

FIXTURE_DIR = REPO_ROOT / "build" / "test-load-fixtures"


class MockArgs:
    def __init__(self, selection: str, receipt: str, serial: str = None, json: bool = True):
        self.selection = selection
        self.receipt = receipt
        self.serial = serial
        self.json = json


class TestFirmwareWorkspaceLoad(unittest.TestCase):
    """Test guarded target loader rules, address admission, and recovery gates."""

    @classmethod
    def setUpClass(cls):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR, ignore_errors=True)

    def test_01_reject_missing_files(self):
        """Reject non-existent selection or receipt."""
        args = MockArgs("nonexistent.json", "nonexistent.receipt.json")
        rc = cmd_load(args)
        self.assertEqual(rc, EXIT_INVALID_INPUT)

    def test_02_block_load_on_rzv2h_cm33(self):
        """Prohibit target loading on RZ/V2H CM33 (resets SoC)."""
        sel_file = FIXTURE_DIR / "cm33.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "cm33-test",
            "board": "rdk-rzv2h",
            "core": "cm33",
            "build": {"family": "px4", "target": "renesas_rdk-rzv2h-io-cm33_default", "mode": "clean"},
            "load": {"recipe": "direct-jlink"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "dummy_cm33.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 30)

        rec_file = create_receipt(
            run_id="run-cm33", family="px4", board="rdk-rzv2h", core="cm33",
            selection_id="cm33-test",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": compute_sha256(dummy_art), "size": 34}],
            status="committed"
        )

        rc = cmd_load(MockArgs(str(sel_file), str(rec_file)))
        self.assertEqual(rc, EXIT_BLOCKED_RECOVERY)

    def test_03_block_load_on_ra8p1(self):
        """Block loading on RA8P1 pending qualified ARMv8-M adapter."""
        sel_file = FIXTURE_DIR / "ra8p1.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "ra8p1-test",
            "board": "evk-ra8p1",
            "core": "cm85",
            "build": {"family": "px4", "target": "renesas_evk-ra8p1_default", "mode": "incremental"},
            "load": {"recipe": "armv8m-flash"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "dummy_ra8.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 30)

        rec_file = create_receipt(
            run_id="run-ra8p1", family="px4", board="evk-ra8p1", core="cm85",
            selection_id="ra8p1-test",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": compute_sha256(dummy_art), "size": 34}],
            status="committed"
        )

        rc = cmd_load(MockArgs(str(sel_file), str(rec_file)))
        self.assertEqual(rc, EXIT_BLOCKED_RECOVERY)

    def test_04_reject_hash_mismatch(self):
        """Reject loading if staged ELF was modified after receipt generation."""
        sel_file = FIXTURE_DIR / "rzv2h.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "rzv2h-simple",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {"family": "px4", "target": "renesas_rdk-rzv2h_simple", "mode": "incremental"},
            "load": {"recipe": "rzv-cr8-ram"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "dummy_mod.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 30)
        orig_sha = compute_sha256(dummy_art)

        rec_file = create_receipt(
            run_id="run-rzv-mod", family="px4", board="rdk-rzv2h", core="cr8_0",
            selection_id="rzv2h-simple",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": orig_sha, "size": 34}],
            status="committed", target=sel["build"]["target"]
        )

        # Modify file to trigger mismatch
        dummy_art.write_bytes(b"\x7fELF-TAMPERED-CONTENT")
        rc = cmd_load(MockArgs(str(sel_file), str(rec_file)))
        self.assertEqual(rc, EXIT_INVALID_INPUT)

    def test_05_group_load_validation(self):
        """Reject group load if receipt is missing pair members."""
        sel_file = FIXTURE_DIR / "group.selection.json"
        sel = {
            "schemaVersion": 1,
            "id": "rzv-px4-dualcr8",
            "board": "rdk-rzv2h",
            "core": "multicore",
            "group": "rzv-px4-dualcr8",
            "build": {"family": "px4", "mode": "incremental"},
            "load": {"recipe": "rzv-dual-cr8-ram"}
        }
        sel_file.write_text(json.dumps(sel))

        dummy_art = FIXTURE_DIR / "cr8_0_only.elf"
        dummy_art.write_bytes(b"\x7fELF" + b"\x00" * 30)

        rec_file = create_receipt(
            run_id="run-grp-incomplete", family="px4", board="rdk-rzv2h", core="multicore",
            selection_id="rzv-px4-dualcr8",
            artifacts=[{"path": str(dummy_art.relative_to(REPO_ROOT)), "sha256": compute_sha256(dummy_art), "size": 34, "core": "cr8_0"}],
            status="committed",
            group="rzv-px4-dualcr8"
        )

        rc = cmd_load(MockArgs(str(sel_file), str(rec_file)))
        self.assertEqual(rc, EXIT_INVALID_INPUT)


if __name__ == "__main__":
    unittest.main()
