"""Physical-probe reservations and owned process identity checks."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import time
import uuid
from pathlib import Path

from .contracts import REPO_ROOT
from .doctor import enumerate_jlink_probes
from .locks import process_start
from .target_state import atomic_json
from .verification import OperationError

PROBE_PROCESS_NAMES = {"JLinkExe", "JLinkGDBServer", "JLinkGDBServerCLExe", "JLinkRTTClient", "JLinkRTTLogger"}
CRITICAL_PORTS = {19021: "RTT console bridge", 50000: "GDB server"}


def runtime_root():
    root = Path(os.environ.get("FIRMWARE_WORKSPACE_RUNTIME", f"/tmp/px4-firmware-{os.getuid()}"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise OperationError("Runtime directory is not owned by this user", "INVALID_RUNTIME", True)
    root.chmod(0o700)
    return root


def probe_directory(serial):
    root = runtime_root() / hashlib.sha256(serial.encode()).hexdigest()
    root.mkdir(exist_ok=True, mode=0o700)
    return root


def probe_history_path(serial):
    """Read-only lookup: never creates a runtime directory or reserves hardware."""
    root = Path(os.environ.get("FIRMWARE_WORKSPACE_RUNTIME", f"/tmp/px4-firmware-{os.getuid()}"))
    directory = root / hashlib.sha256(serial.encode()).hexdigest()
    for path in (root, directory):
        if path.is_symlink() or (path.exists() and path.stat().st_uid != os.getuid()):
            raise OperationError("Runtime directory is not owned by this user", "INVALID_RUNTIME", True)
    return directory / "target-state.json"


def resolve_serial(requested=None):
    serial = requested or os.environ.get("FIRMWARE_PROBE_SERIAL") or os.environ.get("JLINK_SERIAL")
    if not serial:
        probes = enumerate_jlink_probes()
        if len(probes) == 1:
            serial = probes[0]["serial"]
    if not serial or not serial.strip() or "\n" in serial:
        raise OperationError("Select one exact J-Link probe before this operation", "PROBE_REQUIRED", True)
    return serial.strip()


def is_port_listening(port):
    suffix = f":{port:04X}"
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in Path(name).read_text().splitlines()[1:]:
                columns = line.split()
                if columns[1].upper().endswith(suffix) and columns[3] == "0A":
                    return True
        except (OSError, IndexError):
            continue
    return False


def get_active_probe_processes():
    found = []
    for root in Path("/proc").glob("[0-9]*"):
        try:
            name = (root / "comm").read_text().strip()
            if name in PROBE_PROCESS_NAMES or name.startswith("JLinkGDBServer"):
                args = (root / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                found.append({"pid": int(root.name), "comm": name, "cmdline": args})
        except OSError:
            pass
    return found


def check_probe_availability(authorized_serial=None):
    errors = []
    probes = enumerate_jlink_probes()
    if not any(item["serial"] == authorized_serial for item in probes):
        errors.append("The selected J-Link probe is not connected on this workspace host")
    for port, description in CRITICAL_PORTS.items():
        if is_port_listening(port):
            errors.append(f"{description} port {port} is occupied")
    for item in get_active_probe_processes():
        # A serial-less process has unknown ownership; never terminate it.
        if not authorized_serial or authorized_serial in item["cmdline"] or "-select" not in item["cmdline"]:
            errors.append(f"Probe may be owned by {item['comm']} (PID {item['pid']})")
    return not errors, errors


def require_probe_available(serial):
    available, errors = check_probe_availability(serial)
    if not available:
        # Consoles are started by hand; point at the usual owner of the probe.
        if any("RTT console bridge" in error or "JLinkExe" in error for error in errors):
            errors.append("Stop the manual RTT console first: platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop")
        raise OperationError("; ".join(errors), "PROBE_BUSY", True)


class ProbeLease:
    def __init__(self, serial):
        self.serial = serial
        self.directory = probe_directory(serial)
        self.path = self.directory / "probe.lock"
        self.metadata = self.directory / "owner.json"
        self.fd = None
        self.token = None
        self.nested = False
        self.previous = {}
        self.child = self.directory / f"child-{os.getpid()}.json"

    def acquire(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        inherited = os.environ.get("FIRMWARE_PROBE_LEASE")
        if inherited:
            try:
                owner = json.loads(self.metadata.read_text())
                alive = process_start(owner["pid"]) == owner["start"] and owner["start"] is not None
                if owner["token"] != inherited or not alive or owner["root"] != str(REPO_ROOT.resolve()):
                    raise ValueError("lease owner changed")
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.nested = True
                if not self.nested:
                    raise ValueError("reservation no longer held")
                self.token = inherited
                if owner["pid"] != os.getpid():
                    atomic_json(self.child, {"pid": os.getpid(), "start": process_start(os.getpid()), "token": self.token})
                return self
            except (OSError, ValueError, KeyError, TypeError) as error:
                os.close(self.fd)
                self.fd = None
                raise OperationError("Probe reservation is no longer valid", "PROBE_LEASE_EXPIRED", True) from error
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self.fd)
            self.fd = None
            message = "Another session reserves this physical probe"
            # An owned RTT bridge holds the lease for as long as it runs.
            if (probe_directory(self.serial) / "console.json").exists():
                message += "; an RTT console bridge owns it: use Stop RTT Bridge in Firmware Setup first"
            raise OperationError(message, "PROBE_BUSY", True) from error
        self.token = uuid.uuid4().hex
        owner = {"pid": os.getpid(), "start": process_start(os.getpid()),
                 "token": self.token, "root": str(REPO_ROOT.resolve())}
        atomic_json(self.metadata, owner)
        keys = ("FIRMWARE_PROBE_LEASE", "FIRMWARE_PROBE_SERIAL", "FIRMWARE_PROBE_LOCK_FD")
        self.previous = {key: os.environ.get(key) for key in keys}
        os.set_inheritable(self.fd, True)
        os.environ.update(FIRMWARE_PROBE_LEASE=self.token, FIRMWARE_PROBE_SERIAL=self.serial,
                          FIRMWARE_PROBE_LOCK_FD=str(self.fd))
        return self

    def release(self):
        if self.fd is None:
            return
        if self.nested:
            try:
                if json.loads(self.child.read_text()).get("token") == self.token:
                    self.child.unlink()
            except (OSError, ValueError):
                pass
            os.close(self.fd)
            self.fd = None
            return
        # Interrupt only children registered to this exact reservation/process generation.
        processes = []
        for path in self.directory.glob("process-*.json"):
            try:
                child = json.loads(path.read_text())
                if child.get("token") == self.token and child.get("start") and process_start(child["pid"]) == child["start"]:
                    processes.append((path, child))
            except (OSError, ValueError, KeyError):
                pass
        for path in self.directory.glob("child-*.json"):
            try:
                child = json.loads(path.read_text())
                if child.get("token") == self.token and child["pid"] != os.getpid() and process_start(child["pid"]) == child["start"]:
                    os.kill(child["pid"], signal.SIGTERM)
                    deadline = time.monotonic() + 10
                    while process_start(child["pid"]) == child["start"] and time.monotonic() < deadline:
                        time.sleep(0.05)
                    if process_start(child["pid"]) == child["start"]:
                        # Do not unlock while a registered command still owns
                        # hardware. Inherited descriptors retain the lease.
                        os.close(self.fd)
                        self.fd = None
                        raise OperationError("Owned command has not acknowledged cancellation", "PROBE_BUSY", True)
                path.unlink(missing_ok=True)
            except OperationError:
                raise
            except (OSError, ValueError, KeyError):
                pass
        known = {path for path, _ in processes}
        for path in self.directory.glob("process-*.json"):
            if path in known:
                continue
            try:
                child = json.loads(path.read_text())
                if child.get("token") == self.token and child.get("start"):
                    processes.append((path, child))
            except (OSError, ValueError, KeyError):
                pass
        for path, child in processes:
            if process_start(child["pid"]) == child["start"]:
                # ManagedProcess creates a new session/group; the recorded
                # generation proves this is our server/loader, not a user PID.
                try:
                    os.killpg(child["pid"], signal.SIGTERM)
                    deadline = time.monotonic() + 3
                    while process_start(child["pid"]) == child["start"] and time.monotonic() < deadline:
                        time.sleep(0.05)
                    os.killpg(child["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
                core = child.get("core")
                if core in ("cr8_0", "cr8_1", "cm85", "cm33"):
                    from .target_state import TargetState
                    TargetState(self.directory / 'target-state.json').record(
                        ["cr8_0", "cr8_1", "cm33"] if core.startswith('cr8_') else [core],
                        "indeterminate/recovery-required", "debug-owner-lost")
            path.unlink(missing_ok=True)
        self.metadata.unlink(missing_ok=True)
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()
