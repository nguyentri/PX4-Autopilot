"""Owned RTT console startup/teardown under a session-long probe reservation."""
from __future__ import annotations

import json
import os
import signal
import time

from .contracts import REPO_ROOT, EXIT_OK, make_result
from .load import operation_failure
from .locks import process_start
from .probe import ProbeLease, probe_directory, require_probe_available, resolve_serial
from .process import ManagedProcess
from .target_state import TargetState, atomic_json
from .verification import OperationError, admitted_inputs, debug_snapshot

BRIDGE = REPO_ROOT / "platforms/nuttx/Debug/nuttx-rtt-bridge.sh"


def bridge_running(serial):
    pidfile = probe_directory(serial) / "bridge/bridge.pid"
    try:
        pid = int(pidfile.read_text().strip())
        start = (pidfile.parent / 'bridge.pid.identity').read_text().splitlines()[0]
        return start and process_start(pid) == start
    except (OSError, ValueError):
        return False


def console_owner(serial):
    path = probe_directory(serial) / "console.json"
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except (OSError, ValueError) as error:
        raise OperationError("Console ownership metadata is unreadable", "CONSOLE_OWNER_INVALID", True) from error


def stop_owned_console(serial, token=None):
    owner = console_owner(serial)
    if not owner:
        return False
    if owner.get("root") != str(REPO_ROOT.resolve()) or (token and owner.get("token") != token):
        raise OperationError("Console belongs to another workspace/session", "CONSOLE_OWNER_MISMATCH", True)
    if owner.get("detached") and owner["pid"] != os.getpid() and process_start(owner["pid"]) == owner.get("start"):
        os.kill(owner["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while console_owner(serial) and time.monotonic() < deadline:
            time.sleep(0.05)
        if console_owner(serial):
            raise OperationError("Console supervisor has not acknowledged teardown", "CONSOLE_STOP_FAILED", True)
        return True
    code, _, error = ManagedProcess([str(BRIDGE), "stop"], cwd=str(REPO_ROOT),
                                    env={"STATE_DIR": str(probe_directory(serial) / "bridge")}).run()
    if code:
        raise OperationError(error or "Console has not released its owned process/port", "CONSOLE_STOP_FAILED", True)
    (probe_directory(serial) / "console.json").unlink(missing_ok=True)
    return True


def start_owned_console(args, serial, token, detached=False):
    selection, resolved, receipt, artifacts = admitted_inputs(args, "console")
    core = getattr(args, "core", None) or selection["core"]
    if core == "multicore" or core not in artifacts:
        raise OperationError("Select a concrete console core in this image group", "CORE_REQUIRED")
    if selection["board"] != "rdk-rzv2h" or core not in ("cr8_0", "cr8_1"):
        raise OperationError("No managed console transport is admitted for this core", "CONSOLE_UNAVAILABLE", True)
    if selection.get("group"):
        transport = resolved["groupMeta"].get("console", {}).get(core)
    elif selection["build"]["family"] == "nuttx":
        manifest = json.loads((REPO_ROOT / "platforms/nuttx/Debug/rzv2h-all-sample-configs.json").read_text())
        row = next((row for row in manifest["profiles"] if row["profile"] == selection["build"]["config"]), {})
        transport = row.get("console")
    else:
        transport = "rtt" if artifacts[core].get("rttAddress") else None
    if transport != "rtt":
        raise OperationError("This image uses " + str(transport or "an unavailable transport") +
                             "; use nsh_console_exec.py --serial <device> for a UART console", "CONSOLE_UNAVAILABLE", True)
    state = TargetState(probe_directory(serial) / "target-state.json")
    state.require_ready([core])
    require_probe_available(serial)
    if console_owner(serial):
        raise OperationError("An owned console is already active", "CONSOLE_BUSY", True)
    snapshot = debug_snapshot(artifacts[core])
    owner = {"pid": os.getpid(), "start": process_start(os.getpid()), "token": token,
             "root": str(REPO_ROOT.resolve()), "core": core, "detached": detached,
             "receiptId": receipt["receiptId"]}
    # Record intent before the bridge forks so interruption can still stop it.
    atomic_json(probe_directory(serial) / "console.json", owner)
    try:
        code, output, error = ManagedProcess([str(BRIDGE), "start", core, str(snapshot)], cwd=str(REPO_ROOT),
                          env={"JLINK_SERIAL": serial, "STATE_DIR": str(probe_directory(serial) / "bridge")}).run()
        if code:
            raise OperationError(error or output or "RTT bridge startup failed", "CONSOLE_START_FAILED", True)
    except BaseException:
        state.record(["cr8_0", "cr8_1", "cm33"], "indeterminate/recovery-required", receipt["receiptId"])
        stop_owned_console(serial, token)
        raise
    return {"action": "start", "transport": "rtt", "core": core, "running": True,
            "endpoint": "127.0.0.1:19021"}


def cmd_console(args):
    try:
        serial = resolve_serial(getattr(args, "serial", None))
        if args.action == "start":
            if os.environ.get("FIRMWARE_PROBE_LEASE"):
                with ProbeLease(serial) as lease:
                    data = start_owned_console(args, serial, lease.token)
            else:
                from .sessions import launch_console_supervisor
                data = launch_console_supervisor(args, serial)
        elif args.action == "stop":
            stopped = stop_owned_console(serial)
            data = {"action": "stop", "running": False, "stopped": stopped}
        else:
            owner = console_owner(serial)
            if owner and owner.get("root") != str(REPO_ROOT.resolve()):
                raise OperationError("Console belongs to another workspace", "CONSOLE_OWNER_MISMATCH", True)
            data = {"action": "status", "running": bool(owner and bridge_running(serial))}
        print(json.dumps(make_result("console", "ok", data=data)))
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError) as error:
        return operation_failure("console", error)
