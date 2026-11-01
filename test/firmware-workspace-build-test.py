#!/usr/bin/env python3
"""Build, lock, doctor, and artifact staging unit tests for firmware workspace."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from firmware_workspace.artifacts import (
    compute_sha256,
    create_receipt,
    get_git_info,
    read_elf_metadata,
)
from firmware_workspace.catalog import load_groups
from firmware_workspace.contracts import validate_schema
from firmware_workspace.doctor import check_tool, get_python_requirements, run_doctor
from firmware_workspace.locks import (
    BuildLock,
    BuildLockContentionError,
    DEFAULT_LOCK_FILE,
)


class TestFirmwareWorkspaceBuild(unittest.TestCase):
    """Test build lifecycle, locks, doctor checks and artifact staging."""

    def test_01_doctor_runs_cleanly(self):
        """Verify doctor runs and reports structured data."""
        data, diags = run_doctor()
        self.assertIn("tools", data)
        self.assertIn("submodules", data)
        self.assertTrue(data["submodules"]["nuttxInitialized"])
        py_ok, _ = get_python_requirements()
        self.assertTrue(py_ok)

    def test_02_build_lock_acquire_and_release(self):
        """Verify build lock acquires and cleans up cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / ".test.lock"
            lock = BuildLock(lock_path=lock_file, timeout=2.0)
            token = lock.acquire()
            self.assertTrue(token)
            self.assertTrue(lock_file.is_file())
            lock.release()
            self.assertFalse(lock.meta_path.is_file())

    def test_03_reentrant_nested_lock_inheritance(self):
        """Verify nested lock acquisition succeeds via token inheritance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / ".test.lock"
            with BuildLock(lock_path=lock_file, timeout=2.0) as parent_lock:
                # Nested lock acquisition using inherited token
                with BuildLock(lock_path=lock_file, timeout=1.0) as child_lock:
                    self.assertEqual(parent_lock._token, child_lock._token)
                    self.assertTrue(child_lock._is_nested)

    def test_04_lock_contention_detection(self):
        """Verify independent process fails to acquire locked resource within timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / ".test.lock"
            # Acquire lock in parent
            with BuildLock(lock_path=lock_file, timeout=2.0):
                # Clear env token so second lock behaves as independent process
                old_token = os.environ.pop("FIRMWARE_BUILD_LOCK_TOKEN", None)
                try:
                    with self.assertRaises(BuildLockContentionError):
                        BuildLock(lock_path=lock_file, timeout=0.3).acquire()
                finally:
                    if old_token:
                        os.environ["FIRMWARE_BUILD_LOCK_TOKEN"] = old_token

    def test_05_artifact_receipt_generation_and_validation(self):
        """Verify artifact receipt conforms to artifact-receipt schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_elf = Path(tmpdir) / "test.elf"
            test_elf.write_bytes(b"\x7fELF\x01\x01\x01\x00" + b"\x00" * 20)
            sha = compute_sha256(test_elf)
            git_info = get_git_info()
            self.assertTrue(git_info["revision"])

            artifacts = [{
                "path": str(test_elf),
                "sha256": sha,
                "size": test_elf.stat().st_size,
                "core": "cr8_0"
            }]
            run_id = "test-run-001"
            receipt_path = create_receipt(
                run_id=run_id,
                family="px4",
                board="rdk-rzv2h",
                core="cr8_0",
                selection_id="test-sel",
                artifacts=artifacts,
                status="committed",
                target="renesas_rdk-rzv2h_simple"
            )
            self.assertTrue(receipt_path.is_file())
            receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
            diags = validate_schema(receipt_data, "artifact-receipt")
            self.assertEqual(diags, [])

    def test_06_ra8_dual_recipe_descriptors_match_groups(self):
        """Verify dual builder --describe-json outputs match groups.json profiles."""
        groups = load_groups().get("groups", {})
        self.assertIn("ra8p1-dual-ipc", groups)
        self.assertIn("ra8p1-dual-mini", groups)

        ipc_helper = REPO_ROOT / "platforms" / "nuttx" / "NuttX" / "build_dual_ipc_ra8p1.sh"
        import subprocess
        out_ipc = subprocess.check_output([str(ipc_helper), "--describe-json"], text=True)
        desc_ipc = json.loads(out_ipc)
        self.assertEqual(desc_ipc["id"], "ra8p1-dual-ipc")
        self.assertEqual(len(desc_ipc["members"]), len(groups["ra8p1-dual-ipc"]["members"]))

    def test_07_incremental_nuttx_build_reconfigures_on_config_switch(self):
        """Incremental mode drops --no-clean when the shared tree holds another config."""
        from firmware_workspace.build import nuttx_build_command
        with tempfile.TemporaryDirectory() as tmpdir:
            tree = Path(tmpdir) / "nuttx"
            tree.mkdir()
            want = "ipcc-demo-cr8_0-serial"
            # Unconfigured tree: build.sh must configure.
            cmd = nuttx_build_command("rdk-rzv2h", want, "incremental", tree)
            self.assertNotIn("--no-clean", cmd)
            (tree / ".config").write_text("", encoding="utf-8")
            (tree / ".config-build-sh").write_text("rdk-rzv2h:nsh-cr8_1\n", encoding="utf-8")
            cmd = nuttx_build_command("rdk-rzv2h", want, "incremental", tree)
            self.assertNotIn("--no-clean", cmd)
            self.assertEqual(cmd[-1], want)
            (tree / ".config-build-sh").write_text(f"rdk-rzv2h:{want}\n", encoding="utf-8")
            cmd = nuttx_build_command("rdk-rzv2h", want, "incremental", tree)
            self.assertIn("--no-clean", cmd)
            self.assertTrue(cmd[0].endswith("build.sh"))
            self.assertNotIn("--no-clean", nuttx_build_command("rdk-rzv2h", want, "clean", tree))
            ra8 = nuttx_build_command("evk-ra8p1", "nsh", "incremental", tree)
            self.assertTrue(ra8[0].endswith("build_ra8p1.sh"))
            self.assertNotIn("--no-clean", ra8)


if __name__ == "__main__":
    unittest.main()
