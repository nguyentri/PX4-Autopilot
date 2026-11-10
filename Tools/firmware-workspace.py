#!/usr/bin/env python3
"""Unified CLI frontend for PX4 and NuttX firmware workspace integration.

Supports catalog discovery, doctor checks, profile resolution, build locking,
artifact staging, guarded target loading, and Cortex-Debug config generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from firmware_workspace.catalog import (
    discover_nuttx_configs,
    discover_px4_targets,
    group_fingerprint,
    load_devices,
    load_groups,
    resolve_selection,
)
from firmware_workspace.contracts import (
    EXIT_BLOCKED_RECOVERY,
    EXIT_FAILED,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    make_diagnostic,
    make_result,
)


def cmd_catalog(args: argparse.Namespace) -> int:
    """List discovered PX4 targets, NuttX configs, and profiles."""
    px4_targets = discover_px4_targets()
    rzv_configs = discover_nuttx_configs("rdk-rzv2h")
    ra8_configs = discover_nuttx_configs("evk-ra8p1")
    devices = load_devices().get("boards", {})
    groups = load_groups().get("groups", {})
    groups = {name: dict(group, definitionSha256=group_fingerprint(group)) for name, group in groups.items()}

    payload = {
        "px4Targets": px4_targets,
        "nuttxConfigs": {
            "rdk-rzv2h": rzv_configs,
            "evk-ra8p1": ra8_configs,
        },
        "devices": devices,
        "groups": groups,
        "capabilities": {"importImages": 1, "receiptVersions": [1, 2], "preparedIdentity": 1,
                         "strictLoadedIdentity": 1, "progressEvents": 1, "targetHistory": 1},
        "counts": {
            "px4": len(px4_targets),
            "rzv2hNuttx": len(rzv_configs),
            "ra8p1Nuttx": len(ra8_configs),
        }
    }

    if args.json:
        res = make_result("catalog", "ok", data=payload)
        print(json.dumps(res, indent=2))
    else:
        print(f"PX4 targets ({len(px4_targets)}):")
        for t in px4_targets:
            print(f"  {t['target']} ({t['board']}:{t['core']})")
        print(f"\nRZ/V2H NuttX configs ({len(rzv_configs)}):")
        for c in rzv_configs[:10]:
            print(f"  {c['config']} ({c['core']})")
        if len(rzv_configs) > 10:
            print(f"  ... and {len(rzv_configs) - 10} more")
        print(f"\nRA8P1 NuttX configs ({len(ra8_configs)}):")
        for c in ra8_configs:
            print(f"  {c['config']} ({c['core']})")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    """Resolve and validate a selection file."""
    sel_path = Path(args.selection)
    if not sel_path.is_file():
        err = make_diagnostic("error", "SELECTION_FILE_NOT_FOUND", f"File not found: {sel_path}")
        if args.json:
            print(json.dumps(make_result("resolve", "failed", diagnostics=[err]), indent=2))
        else:
            print(f"Error: {err['message']}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    try:
        with open(sel_path, "r", encoding="utf-8") as f:
            raw_sel = json.load(f)
    except Exception as e:
        err = make_diagnostic("error", "INVALID_JSON", f"Failed to parse JSON: {e}")
        if args.json:
            print(json.dumps(make_result("resolve", "failed", diagnostics=[err]), indent=2))
        else:
            print(f"Error: {err['message']}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    resolved, diags = resolve_selection(raw_sel, operation=getattr(args, "operation", "build"))
    if not resolved or any(d["level"] == "error" for d in diags):
        status = "blocked" if any(d["code"] in ("LOAD_UNAVAILABLE", "DEBUG_UNAVAILABLE") for d in diags) else "failed"
        exit_code = EXIT_BLOCKED_RECOVERY if status == "blocked" else EXIT_INVALID_INPUT
        if args.json:
            print(json.dumps(make_result("resolve", status, diagnostics=diags), indent=2))
        else:
            for d in diags:
                print(f"[{d['level'].upper()}] {d['code']}: {d['message']} ({d.get('path', '')})", file=sys.stderr)
        return exit_code

    if args.json:
        print(json.dumps(make_result("resolve", "ok", data=resolved, diagnostics=diags), indent=2))
    else:
        print(f"Resolved selection: {resolved['selection']['id']}")
        print(f"  Board: {resolved['board']['name']} ({resolved['selection']['board']})")
        print(f"  Core:  {resolved['selection']['core']}")
        print(f"  Debug device: {resolved['jlinkDevice']}")
    return EXIT_OK


def main() -> int:
    if sys.argv[1:2] == ["jlink-server"]:
        from firmware_workspace.server import cmd_jlink_server
        return cmd_jlink_server(sys.argv[2:])
    parser = argparse.ArgumentParser(description="PX4/NuttX Firmware Workspace CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # catalog
    p_cat = subparsers.add_parser("catalog", help="List available targets, configs and devices")
    p_cat.add_argument("--json", action="store_true", help="Output JSON result")

    # resolve
    p_res = subparsers.add_parser("resolve", help="Validate and resolve a selection file")
    p_res.add_argument("--selection", required=True, help="Path to selection JSON file")
    p_res.add_argument("--operation", choices=["build", "load", "debug", "console"], default="build")
    p_res.add_argument("--json", action="store_true", help="Output JSON result")

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Check prerequisite tools and probes")
    p_doc.add_argument("--selection", help="Optional selection JSON file")
    p_doc.add_argument("--serial", help="Read-only load history for an exact probe serial")
    p_doc.add_argument("--json", action="store_true", help="Output JSON result")

    # build
    p_import = subparsers.add_parser("import-images", help="Capture and validate explicitly assigned CR8 images without hardware")
    p_import.add_argument("--input", required=True, help="Path to schema-versioned import request JSON")
    p_import.add_argument("--json", action="store_true", help="Output JSON result")

    p_bld = subparsers.add_parser("build", help="Build firmware for selected profile")
    p_bld.add_argument("--selection", required=True, help="Path to selection JSON file")
    p_bld.add_argument("--receipt", help="Output receipt path")
    p_bld.add_argument("--clean", action="store_true", help="Clean rebuild without changing the saved selection")
    p_bld.add_argument("--low-priority", action="store_true", help="Run the build under nice -n 19 (an RTT bridge is reading the target)")
    p_bld.add_argument("--json", action="store_true", help="Output JSON result")

    # load
    p_load = subparsers.add_parser("load", help="Guarded load of firmware image to target")
    p_load.add_argument("--selection", required=True, help="Path to selection JSON file")
    p_load.add_argument("--receipt", required=True, help="Path to validated artifact receipt")
    p_load.add_argument("--serial", help="Authorized J-Link probe serial")
    p_load.add_argument("--recover", action="store_true", help="Explicit recovery reload after an interrupted/failed operation")
    p_load.add_argument("--expect-receipt-id", help="Reject a replaced prepared receipt before probe interaction")
    p_load.add_argument("--expect-pair-sha256", help="Require exact prepared pair bytes")
    p_load.add_argument("--json", action="store_true", help="Output JSON result")

    # debug-config
    p_dbg = subparsers.add_parser("debug-config", help="Resolve Cortex-Debug launch configuration")
    p_dbg.add_argument("--selection", required=True, help="Path to selection JSON file")
    p_dbg.add_argument("--receipt", required=True, help="Path to validated artifact receipt")
    p_dbg.add_argument("--core", help="Target core to debug (e.g. cr8_0, cr8_1)")
    p_dbg.add_argument("--serial", help="Authorized J-Link probe serial")
    p_dbg.add_argument("--gdb", help="GDB executable override")
    p_dbg.add_argument("--require-loaded", action="store_true", help="Require exact verified paired load history")
    p_dbg.add_argument("--expect-receipt-id", help="Require exact prepared receipt ID")
    p_dbg.add_argument("--expect-pair-sha256", help="Require exact prepared pair bytes")
    p_dbg.add_argument("--json", action="store_true", help="Output JSON result")

    # console
    p_con = subparsers.add_parser("console", help="Manage an owned RTT console session")
    p_con.add_argument("--selection", required=True, help="Path to selection JSON file")
    p_con.add_argument("--receipt", required=True, help="Path to validated artifact receipt")
    p_con.add_argument("--action", choices=["start", "stop", "status"], default="status")
    p_con.add_argument("--serial", help="Authorized J-Link probe serial")
    p_con.add_argument("--core", help="Concrete console core for an image group")
    p_con.add_argument("--dual", action="store_true",
                       help="Serve both CR8 consoles from one probe (CR8-0 19021, CR8-1 19031)")
    p_con.add_argument("--json", action="store_true", help="Output JSON result")

    p_session = subparsers.add_parser("probe-session", help="Reserve a probe until stdin closes")
    p_session.add_argument("--serial", help="Selected J-Link serial")
    p_session.add_argument("--json", action="store_true")
    p_session.add_argument("--console-start", action="store_true", help=argparse.SUPPRESS)
    p_session.add_argument("--selection", help=argparse.SUPPRESS)
    p_session.add_argument("--receipt", help=argparse.SUPPRESS)
    p_session.add_argument("--core", help=argparse.SUPPRESS)
    p_session.add_argument("--dual", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.command == "catalog":
        return cmd_catalog(args)
    elif args.command == "resolve":
        return cmd_resolve(args)
    else:
        from firmware_workspace import doctor
        if args.command == "doctor":
            return doctor.cmd_doctor(args)
        elif args.command == "build":
            from firmware_workspace import build
            return build.cmd_build(args)
        elif args.command == "import-images":
            from firmware_workspace.import_images import cmd_import_images
            return cmd_import_images(args)
        elif args.command == "load":
            from firmware_workspace import load
            return load.cmd_load(args)
        elif args.command == "debug-config":
            from firmware_workspace import debug
            return debug.cmd_debug_config(args)
        elif args.command == "console":
            from firmware_workspace import console
            return console.cmd_console(args)
        elif args.command == "probe-session":
            from firmware_workspace.sessions import cmd_probe_session
            return cmd_probe_session(args)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
