#!/usr/bin/env python3
"""Contract and schema unit tests for firmware workspace."""

import json
import sys
import unittest
from pathlib import Path

# Add Tools to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from firmware_workspace.catalog import (
    discover_nuttx_configs,
    discover_px4_targets,
    load_devices,
    load_groups,
    resolve_selection,
)
from firmware_workspace.contracts import (
    SCHEMAS_DIR,
    Draft7Validator,
    HAS_JSONSCHEMA,
    load_schema,
    validate_schema,
)


class TestFirmwareWorkspaceContracts(unittest.TestCase):
    """Test schema validity and selection resolution contracts."""

    def setUp(self):
        self.assertTrue(HAS_JSONSCHEMA, "jsonschema module must be installed")

    def test_01_all_schemas_are_valid_draft7(self):
        """Verify all schemas under Tools/vscode_extension/1kw-px4-nuttx/schemas are valid Draft 7."""
        schema_files = list(SCHEMAS_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 4)
        for sf in schema_files:
            schema = load_schema(sf.name)
            Draft7Validator.check_schema(schema)

    def test_02_catalog_counts(self):
        """Verify authoritative discovery counts: 14 PX4, 134 RZ NuttX, 30 RA8P1 NuttX."""
        px4_targets = discover_px4_targets()
        self.assertEqual(len(px4_targets), 14)

        rzv_configs = discover_nuttx_configs("rdk-rzv2h")
        self.assertEqual(len(rzv_configs), 134)

        ra8_configs = discover_nuttx_configs("evk-ra8p1")
        self.assertEqual(len(ra8_configs), 30)

    def test_03_devices_and_groups_valid(self):
        """Verify devices.json and groups.json conform to capabilities schema."""
        devs = load_devices()
        diags = validate_schema(devs, "device-capabilities")
        self.assertEqual(diags, [], f"devices.json schema validation failed: {diags}")

        groups = load_groups().get("groups", {})
        self.assertIn("rzv-native-ipc-rtt", groups)
        self.assertIn("rzv-native-ipc-serial", groups)
        self.assertIn("rzv-native-ipc-demo-serial", groups)
        self.assertIn("ra8p1-dual-ipc", groups)

    def test_04_valid_px4_selection(self):
        """Verify valid PX4 selection resolves cleanly."""
        sel = {
            "schemaVersion": 1,
            "id": "rzv2h-default",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {
                "family": "px4",
                "target": "renesas_rdk-rzv2h_default",
                "mode": "incremental"
            },
            "load": {"recipe": "rzv-cr8-ram"},
            "debug": {"mode": "attach"}
        }
        resolved, diags = resolve_selection(sel)
        self.assertEqual(diags, [])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["jlinkDevice"], "R9A09G057H44_R8_0")

    def test_05_valid_nuttx_selection(self):
        """Verify valid NuttX selection resolves cleanly."""
        sel = {
            "schemaVersion": 1,
            "id": "rzv2h-nsh",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {
                "family": "nuttx",
                "config": "nsh",
                "mode": "incremental"
            }
        }
        resolved, diags = resolve_selection(sel)
        self.assertEqual(diags, [])
        self.assertIsNotNone(resolved)

    def test_06_reject_unsupported_version(self):
        """Reject invalid schemaVersion (e.g. 99)."""
        sel = {
            "schemaVersion": 99,
            "id": "invalid-ver",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {
                "family": "px4",
                "target": "renesas_rdk-rzv2h_default",
                "mode": "incremental"
            }
        }
        resolved, diags = resolve_selection(sel)
        self.assertIsNone(resolved)
        self.assertTrue(any(d["code"] == "SCHEMA_VALIDATION_ERROR" for d in diags))

    def test_07_reject_unknown_properties(self):
        """Reject unknown properties due to additionalProperties: false."""
        sel = {
            "schemaVersion": 1,
            "id": "unknown-prop",
            "board": "rdk-rzv2h",
            "core": "cr8_0",
            "build": {
                "family": "px4",
                "target": "renesas_rdk-rzv2h_default",
                "mode": "incremental"
            },
            "command": "malicious_script.sh"
        }
        resolved, diags = resolve_selection(sel)
        self.assertIsNone(resolved)
        self.assertTrue(any(d["code"] == "SCHEMA_VALIDATION_ERROR" for d in diags))

    def test_08_reject_core_target_mismatch(self):
        """Reject core/target mismatch (e.g. cr8_1 core with cr8_0 target)."""
        sel = {
            "schemaVersion": 1,
            "id": "core-mismatch",
            "board": "rdk-rzv2h",
            "core": "cr8_1",
            "build": {
                "family": "px4",
                "target": "renesas_rdk-rzv2h_default",
                "mode": "incremental"
            }
        }
        resolved, diags = resolve_selection(sel)
        self.assertIsNone(resolved)
        self.assertTrue(any(d["code"] == "CORE_MISMATCH" for d in diags))

    def test_09_reject_load_on_unsupported_cm33(self):
        """Reject load recipe on RZ/V2H CM33 core (direct attach resets SoC)."""
        sel = {
            "schemaVersion": 1,
            "id": "cm33-load-attempt",
            "board": "rdk-rzv2h",
            "core": "cm33",
            "build": {
                "family": "px4",
                "target": "renesas_rdk-rzv2h-io-cm33_default",
                "mode": "clean"
            },
            "load": {"recipe": "direct-jlink"}
        }
        resolved, diags = resolve_selection(sel, operation="load")
        self.assertIsNone(resolved)
        self.assertTrue(any(d["code"] == "LOAD_UNAVAILABLE" for d in diags))

    def test_10_multicore_groups(self):
        """Verify multi-core PX4 and NuttX group profiles resolve cleanly."""
        for gid, fam in [("rzv-px4-dualcr8", "px4"), ("rzv-px4-demo", "px4"), ("rzv-native-ipc-rtt", "nuttx"),
                         ("rzv-native-ipc-demo-serial", "nuttx")]:
            sel = {
                "schemaVersion": 1,
                "id": gid,
                "board": "rdk-rzv2h",
                "core": "multicore",
                "group": gid,
                "build": {"family": fam, "mode": "incremental"},
                "load": {"recipe": "rzv-dual-cr8-ram"},
                "debug": {"mode": "attach"}
            }
            resolved, diags = resolve_selection(sel)
            self.assertIsNotNone(resolved, f"Failed resolving group {gid}: {diags}")
            self.assertEqual(diags, [])
            self.assertIn("groupMeta", resolved)
            self.assertEqual(len(resolved["groupMeta"]["members"]), 2)


if __name__ == "__main__":
    unittest.main()
