"""Resolve exact-core immutable Cortex-Debug attach configurations."""
from __future__ import annotations

import json
import os
import sys

from .contracts import REPO_ROOT, EXIT_OK, make_result
from .doctor import check_tool
from .load import operation_failure
from .probe import probe_directory, resolve_serial
from .target_state import TargetState
from .verification import OperationError, admitted_inputs, debug_snapshot


def cmd_debug_config(args):
    try:
        selection, resolved, receipt, artifacts = admitted_inputs(args, "debug")
        core = getattr(args, "core", None) or selection["core"]
        if core == "multicore":
            raise OperationError("Select a concrete core from this image group", "CORE_REQUIRED")
        if core not in artifacts:
            raise OperationError("Requested core is absent from the receipt", "RECEIPT_CORE_MISMATCH")
        capabilities = resolved["board"]["cores"].get(core, {})
        if not capabilities.get("debugAvailable"):
            raise OperationError("Managed debug is unavailable on this core", "DEBUG_UNAVAILABLE", True)
        # Config generation remains host-only. A session reservation enforces
        # probe ownership when the client actually starts a debug session.
        requested_serial = getattr(args, "serial", None)
        if requested_serial:
            state = TargetState(probe_directory(requested_serial) / "target-state.json")
            state.require_ready([core])
        snapshot = debug_snapshot(artifacts[core])
        explicit_gdb = getattr(args, "gdb", None)
        gdb = check_tool(explicit_gdb) if explicit_gdb else check_tool("gdb-multiarch") or check_tool("arm-none-eabi-gdb")
        if explicit_gdb and not gdb:
            raise OperationError("Configured GDB executable is unavailable", "GDB_NOT_FOUND", True)
        configuration = {
            "name": f"Firmware Workspace: {selection['id']} ({core})",
            "type": "cortex-debug", "request": "attach", "servertype": "jlink",
            "device": capabilities["jlinkDevice"], "interface": "swd",
            "executable": str(snapshot), "cwd": str(REPO_ROOT),
            "gdbPath": gdb or "gdb-multiarch", "showDevDebugOutput": "none",
            "serverArgs": ["-noreset", "-noir", "-singlerun", "-localhostonly"],
            "overrideAttachCommands": ["monitor halt"],
            "overrideResetCommands": ["monitor halt"],
            "overrideRestartCommands": ["monitor halt"],
            "preResetCommands": [], "postResetCommands": [],
            "preRestartCommands": [], "postRestartCommands": [],
            "postStartSessionCommands": [],
            "breakAfterReset": True, "rttConfig": {"enabled": False},
        }
        if requested_serial:
            configuration["serialNumber"] = requested_serial
        lease = os.environ.get("FIRMWARE_PROBE_LEASE")
        if lease:
            server = check_tool("JLinkGDBServerCLExe") or check_tool("JLinkGDBServer")
            if not server:
                raise OperationError("J-Link GDB server is unavailable on this workspace host", "SERVER_UNAVAILABLE", True)
            configuration["serverpath"] = str(REPO_ROOT / "Tools/firmware_workspace/jlink-server.sh")
            configuration["serverArgs"] += ["--firmware-lease=" + lease,
                                             "--firmware-serial=" + resolve_serial(requested_serial),
                                             "--firmware-core=" + core,
                                             "--firmware-python=" + sys.executable,
                                             "--firmware-server=" + server]
        svd = REPO_ROOT / "rzv2h.svd"
        if selection["board"] == "rdk-rzv2h" and svd.is_file():
            configuration["svdFile"] = str(svd)
        print(json.dumps(make_result("debug-config", "ok", data={"configuration": configuration,
                                      "artifactSha256": artifacts[core]["sha256"], "core": core})))
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError) as error:
        return operation_failure("debug-config", error)
