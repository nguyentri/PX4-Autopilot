"""Observable probe reservation lifetime for editor and standalone consoles."""
from __future__ import annotations

import json
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from .contracts import REPO_ROOT, EXIT_OK, make_result
from .console import console_owner, start_owned_console, stop_owned_console
from .load import operation_failure
from .probe import ProbeLease, probe_directory, require_probe_available, resolve_serial
from .target_state import TargetState
from .process import get_scrubbed_env
from .verification import OperationError


def cmd_probe_session(args):
    try:
        serial = resolve_serial(getattr(args, "serial", None))
        def stop(signum, frame):
            raise KeyboardInterrupt
        old = {number: signal.signal(number, stop) for number in (signal.SIGTERM, signal.SIGINT)}
        try:
            with ProbeLease(serial) as lease:
                require_probe_available(serial)
                try:
                    if getattr(args, "console_start", False):
                        data = start_owned_console(args, serial, lease.token, detached=True)
                    else:
                        data = {"leaseToken": lease.token, "serial": serial}
                    print(json.dumps(make_result("probe-session", "ok", data=data)), flush=True)
                    if getattr(args, "console_start", False):
                        while console_owner(serial):
                            from .console import bridge_running
                            if not bridge_running(serial):
                                owner = console_owner(serial)
                                TargetState(probe_directory(serial) / "target-state.json").record(
                                    [owner["core"]], "indeterminate/recovery-required", owner["receiptId"])
                                break
                            time.sleep(0.5)
                    else:
                        # The editor owns this pipe. EOF/crash ends the lease.
                        for line in sys.stdin:
                            event = json.loads(line)
                            core = event.get("core")
                            if event.get("event") == "debug-failed" and core in ("cr8_0", "cr8_1", "cm85", "cm33"):
                                # A failed RZ/V2H connect may reset the entire SoC.
                                TargetState(probe_directory(serial) / "target-state.json").record(
                                    ["cr8_0", "cr8_1", "cm33"] if core.startswith('cr8_') else [core],
                                    "indeterminate/recovery-required", "debug-connect-failed")
                finally:
                    stop_owned_console(serial, lease.token)
        except KeyboardInterrupt:
            pass
        finally:
            for number, handler in old.items():
                signal.signal(number, handler)
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError) as error:
        return operation_failure("probe-session", error)


def launch_console_supervisor(args, serial):
    command = [sys.executable, str(REPO_ROOT / "Tools/firmware-workspace.py"), "probe-session",
               "--serial", serial, "--console-start", "--selection", str(Path(args.selection).resolve()),
               "--receipt", str(Path(args.receipt).resolve()), "--json"]
    if getattr(args, "core", None):
        command += ["--core", args.core]
    log_dir = REPO_ROOT / "build/workspace-artifacts/.console"
    log_dir.mkdir(parents=True, exist_ok=True)
    acknowledged = False
    with open(log_dir / "supervisor.log", "ab") as log:
        child = subprocess.Popen(command, cwd=REPO_ROOT, env=get_scrubbed_env(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=log, start_new_session=True)
    previous = {}
    try:
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, interrupted)
        ready, _, _ = select.select([child.stdout], [], [], 100)
        if not ready:
            raise OperationError("Console startup timed out", "CONSOLE_START_FAILED", True)
        result = json.loads(child.stdout.readline())
        if result["status"] != "ok":
            raise OperationError("; ".join(item["message"] for item in result["diagnostics"]), "CONSOLE_START_FAILED", True)
        acknowledged = True
        return result["data"]
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        child.stdout.close()
        if not acknowledged:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
