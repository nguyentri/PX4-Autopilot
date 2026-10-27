"""Exact-image RAM loading with canonical address admission and recovery gates."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

from .contracts import (REPO_ROOT, EXIT_OK, EXIT_FAILED, EXIT_INVALID_INPUT,
                        EXIT_BLOCKED_RECOVERY, EXIT_CANCELLED, make_diagnostic, make_result)
from .process import ManagedProcess
from .probe import ProbeLease, probe_directory, require_probe_available, resolve_serial
from .target_state import TargetState
from .verification import OperationError, admitted_inputs, artifact_snapshots, prepared_identity

ALLOWLIST_SCRIPT = REPO_ROOT / "platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py"


class LoadProgress:
    def __init__(self, operation_id, log_dir):
        self.operation_id, self.log_dir = operation_id, log_dir
        self.buffer = ""
        self.steps = []

    def output(self, chunk, stream):
        if stream != "stderr":
            return
        self.buffer += chunk
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            match = re.fullmatch(r"PX4_WORKSPACE_STEP (cr8_[01]) (load|verify) (begin|ok|fail)", line.strip())
            if match:
                core, phase, state = match.groups()
                event = {"eventVersion": 1, "operationInstanceId": self.operation_id,
                         "phase": phase, "core": core, "state": state,
                         "logPath": str(self.log_dir / f"{phase}-CR8-{core[-1]}.log")}
                self.steps.append(event)
                print("PX4_WORKSPACE_EVENT " + json.dumps(event), file=sys.stderr, flush=True)

    def finish(self):
        if self.steps and self.steps[-1]["state"] == "begin":
            self.steps.append(dict(self.steps[-1], state="indeterminate"))


def check_rz_allowlist(elf_path, device=None, digest=None):
    if not ALLOWLIST_SCRIPT.is_file():
        raise OperationError("Canonical ELF admission checker is missing", "ADMISSION_UNAVAILABLE", True)
    if not device or not digest:
        raise OperationError("ELF admission requires the exact device and receipt hash", "INVALID_ADMISSION")
    command = [sys.executable, str(ALLOWLIST_SCRIPT), "--elf", str(elf_path),
               "--device", device, "--expect-sha256", digest]
    code, output, error = ManagedProcess(command, cwd=str(REPO_ROOT)).run(stream_stderr=False)
    if code != 0 or "RESULT=ADDRESS_CONTRACT_VERIFIED" not in output:
        raise OperationError("ELF address admission failed: " + (error or output)[-2000:], "ALLOWLIST_VIOLATION")


def operation_failure(name, error):
    blocked = isinstance(error, OperationError) and error.blocked
    status = "blocked" if blocked else "failed"
    code = getattr(error, "code", "OPERATION_FAILED")
    print(json.dumps(make_result(name, status, data={"recoveryRequired": code == "RECOVERY_REQUIRED"},
                                diagnostics=[make_diagnostic("error", code, str(error))])))
    return EXIT_BLOCKED_RECOVERY if blocked else EXIT_INVALID_INPUT


def cmd_load(args):
    try:
        selection, resolved, receipt, artifacts = admitted_inputs(args, "load")
        identity = prepared_identity(selection, resolved, receipt, artifacts)
        operation_id = str(uuid.UUID(os.environ.get("FIRMWARE_WORKSPACE_OPERATION_ID", str(uuid.uuid4()))))
        if selection["board"] != "rdk-rzv2h" or set(artifacts) - {"cr8_0", "cr8_1"}:
            raise OperationError("This board/core has no admitted managed RAM loader", "LOAD_UNAVAILABLE", True)
        if "group" in selection:
            expected_recipe = resolved["groupMeta"].get("loadRecipe")
        else:
            expected_recipe = "rzv-cr8-ram"
        if selection.get("load", {}).get("recipe", expected_recipe) != expected_recipe:
            raise OperationError("Load recipe does not match the selected device/group", "LOAD_UNAVAILABLE", True)
        serial = resolve_serial(getattr(args, "serial", None))
        with ProbeLease(serial):
            state = TargetState(probe_directory(serial) / "target-state.json")
            state.require_ready(artifacts, recover=getattr(args, "recover", False))
            with artifact_snapshots(artifacts) as snapshots:
                for core, snapshot in snapshots.items():
                    device = resolved["board"]["cores"][core]["jlinkDevice"]
                    check_rz_allowlist(snapshot, device, artifacts[core]["sha256"])
                require_probe_available(serial)
                if "group" in selection:
                    if set(snapshots) != {"cr8_0", "cr8_1"}:
                        raise OperationError("Group requires both CR8 members", "MISSING_PAIR_MEMBERS")
                    script = REPO_ROOT / "platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh"
                    command = [str(script), str(snapshots["cr8_0"]), str(snapshots["cr8_1"])]
                else:
                    core = selection["core"]
                    script = REPO_ROOT / "platforms/nuttx/Debug/rzv2h-ipc/rzv2h-load-one-core.sh"
                    command = [str(script), core, str(snapshots[core])]
                logs_root = probe_directory(serial) / "load-logs"
                logs_root.mkdir(exist_ok=True, mode=0o700)
                log_dir = Path(tempfile.mkdtemp(prefix=operation_id + "-", dir=logs_root))
                progress = LoadProgress(operation_id, log_dir)
                metadata = {"digests": identity["artifactDigests"], "group": identity["groupDefinitionSha256"],
                            "pair_id": identity["pairSha256"], "operation_id": operation_id,
                            "steps": progress.steps, "log_path": str(log_dir)}
                state.record(artifacts, "started", receipt["receiptId"], **metadata)
                try:
                    code, _, _ = ManagedProcess(command, cwd=str(REPO_ROOT), env={"JLINK_SERIAL": serial, "LOAD_ATTEMPTS": "1",
                        "LOG_DIR": str(log_dir), "FIRMWARE_WORKSPACE_STEPS": "1", "FIRMWARE_WORKSPACE_OPERATION_ID": operation_id}).run(on_output=progress.output)
                except BaseException:
                    progress.finish()
                    state.record(["cr8_0", "cr8_1", "cm33"], "indeterminate/recovery-required", receipt["receiptId"], **metadata)
                    raise
                progress.finish()
                outcome = dict(identity, operationInstanceId=operation_id, steps=progress.steps, logPath=str(log_dir))
                if code != 0:
                    state.record(["cr8_0", "cr8_1", "cm33"], "indeterminate/recovery-required", receipt["receiptId"], **metadata)
                    status = "cancelled" if code == 130 else "failed"
                    result = make_result("load", status, data=dict(outcome, recoveryRequired=True),
                                         diagnostics=[make_diagnostic("error", "RECOVERY_REQUIRED", "Load did not verify; explicitly select recovery reload")], child_exit_code=code)
                    print(json.dumps(result))
                    return EXIT_CANCELLED if code == 130 else EXIT_FAILED
                state.record(artifacts, "verified", receipt["receiptId"], **metadata)
                outcome["timestamp"] = state.value["lastOperation"]["timestamp"]
        print(json.dumps(make_result("load", "ok", data=dict(outcome, core=selection["core"], status="verified", recoveryRequired=False))))
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError) as error:
        return operation_failure("load", error)
