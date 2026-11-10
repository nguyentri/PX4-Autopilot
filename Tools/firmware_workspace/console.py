"""Owned RTT console startup/teardown under a session-long probe reservation."""
from __future__ import annotations

import json
import os
import signal
import sys
import time

from .contracts import REPO_ROOT, EXIT_OK, make_result
from .load import operation_failure
from .locks import process_start
from .probe import ProbeLease, probe_directory, require_probe_available, resolve_serial
from .process import ManagedProcess
from .target_state import TargetState, atomic_json
from .verification import OperationError, admitted_inputs, debug_snapshot

BRIDGE = REPO_ROOT / "platforms/nuttx/Debug/nuttx-rtt-bridge.sh"
# Serves both CR8 consoles from one probe over the AXI-AP (no core connect).
DUAL_BRIDGE = REPO_ROOT / "platforms/nuttx/Debug/rzv2h-dual-rtt-bridge.py"
# JLinkExe's default RTT telnet port; FIRMWARE_RTT_PORT moves the console.
RTT_ENDPOINT_PORT = 19021
# CR8-1's port in dual mode; FIRMWARE_RTT_PORT_CR8_1 moves it.
RTT_ENDPOINT_PORT_CR8_1 = 19031


def rtt_port(variable="FIRMWARE_RTT_PORT", default=RTT_ENDPOINT_PORT):
    value = os.environ.get(variable, str(default))
    if not value.isdigit() or not 1024 <= int(value) <= 65535:
        raise OperationError(variable + " must be a TCP port number", "CONSOLE_PORT_INVALID")
    return int(value)


def bridge_command(owner, action):
    if owner.get("mode") == "dual":
        return [sys.executable, str(DUAL_BRIDGE), action]
    return [str(BRIDGE), action]


def endpoints(owner):
    ports = owner.get("ports") or {owner.get("core"): owner.get("port", RTT_ENDPOINT_PORT)}
    return {core: "127.0.0.1:%d" % port for core, port in ports.items()}


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
    code, _, error = ManagedProcess(bridge_command(owner, "stop"), cwd=str(REPO_ROOT),
                                    env={"STATE_DIR": str(probe_directory(serial) / "bridge")}).run()
    if code:
        raise OperationError(error or "Console has not released its owned process/port", "CONSOLE_STOP_FAILED", True)
    (probe_directory(serial) / "console.json").unlink(missing_ok=True)
    return True


def console_transport(selection, resolved, artifacts, core):
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


def start_owned_console(args, serial, token, detached=False):
    selection, resolved, receipt, artifacts = admitted_inputs(args, "console")
    dual = bool(getattr(args, "dual", False))
    cores = ["cr8_0", "cr8_1"] if dual else [getattr(args, "core", None) or selection["core"]]
    for core in cores:
        console_transport(selection, resolved, artifacts, core)
    state = TargetState(probe_directory(serial) / "target-state.json")
    state.require_ready(cores)
    require_probe_available(serial)
    if console_owner(serial):
        raise OperationError("An owned console is already active", "CONSOLE_BUSY", True)
    ports = {"cr8_0": rtt_port()} if dual else {cores[0]: rtt_port()}
    if dual:
        ports["cr8_1"] = rtt_port("FIRMWARE_RTT_PORT_CR8_1", RTT_ENDPOINT_PORT_CR8_1)
        if ports["cr8_0"] == ports["cr8_1"]:
            raise OperationError("The two console ports must differ", "CONSOLE_PORT_INVALID")
    snapshots = [str(debug_snapshot(artifacts[core])) for core in cores]
    owner = {"port": ports[cores[0]], "ports": ports, "pid": os.getpid(), "start": process_start(os.getpid()),
             "token": token, "root": str(REPO_ROOT.resolve()), "core": "multicore" if dual else cores[0],
             "cores": cores, "mode": "dual" if dual else "single", "detached": detached,
             "receiptId": receipt["receiptId"]}
    # Record intent before the bridge forks so interruption can still stop it.
    atomic_json(probe_directory(serial) / "console.json", owner)
    env = {"JLINK_SERIAL": serial, "STATE_DIR": str(probe_directory(serial) / "bridge")}
    if dual:
        command = bridge_command(owner, "start") + snapshots
        env.update(RTT_PORT_CR8_0=str(ports["cr8_0"]), RTT_PORT_CR8_1=str(ports["cr8_1"]))
    else:
        command = bridge_command(owner, "start") + [cores[0], snapshots[0]]
        env["RTT_PORT"] = str(ports[cores[0]])
    try:
        code, output, error = ManagedProcess(command, cwd=str(REPO_ROOT), env=env).run()
        if code:
            raise OperationError(error or output or "RTT bridge startup failed", "CONSOLE_START_FAILED", True)
    except BaseException:
        state.record(["cr8_0", "cr8_1", "cm33"], "indeterminate/recovery-required", receipt["receiptId"])
        stop_owned_console(serial, token)
        raise
    data = {"action": "start", "transport": "rtt", "core": owner["core"], "mode": owner["mode"], "running": True,
            "endpoint": "127.0.0.1:%d" % owner["port"]}
    if dual:
        data["endpoints"] = endpoints(owner)
    return data


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
            running = bool(owner and bridge_running(serial))
            data = {"action": "status", "running": running}
            if running:
                data.update(core=owner.get("core"), mode=owner.get("mode", "single"),
                            endpoint="127.0.0.1:%d" % owner.get("port", RTT_ENDPOINT_PORT))
                if owner.get("mode") == "dual":
                    data["endpoints"] = endpoints(owner)
        print(json.dumps(make_result("console", "ok", data=data)))
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError) as error:
        return operation_failure("console", error)
