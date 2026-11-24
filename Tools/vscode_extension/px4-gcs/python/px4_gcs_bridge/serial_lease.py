"""Host-wide serial lease shared with Tools/firmware_workspace/serial_console.py.

Convention (must match the firmware workspace; the lease test compares both):
runtime root `$FIRMWARE_WORKSPACE_RUNTIME` or `/tmp/px4-firmware-<uid>` (0700,
owned by the user, not a symlink); lock `<root>/uart/<major>-<minor>.lock` held
with `flock(LOCK_EX | LOCK_NB)`; metadata `<major>-<minor>.json` beside it. The
kernel lock is the authority, the metadata is diagnostic only.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from .protocol import BridgeError

LEASE_SUPPORTED = sys.platform.startswith("linux")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def runtime_root() -> Path:
    root = Path(os.environ.get("FIRMWARE_WORKSPACE_RUNTIME", f"/tmp/px4-firmware-{os.getuid()}"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise BridgeError("PERMISSION_DENIED", f"runtime directory {root} is not owned by this user")
    root.chmod(0o700)
    return root


def device_identity(device: str):
    """Resolve the device and return (canonical path, '<major>-<minor>')."""
    try:
        canonical = Path(device).resolve(strict=True)
        info = canonical.stat()
    except FileNotFoundError:
        raise BridgeError("PORT_NOT_FOUND", f"serial device {device} does not exist") from None
    except PermissionError:
        raise BridgeError("PERMISSION_DENIED", f"cannot inspect {device}") from None
    if not stat.S_ISCHR(info.st_mode):
        raise BridgeError("BAD_ARGUMENT", f"{device} is not a character device")
    if not os.access(canonical, os.R_OK | os.W_OK):
        raise BridgeError("PERMISSION_DENIED", f"no read/write access to {canonical}")
    return canonical, f"{os.major(info.st_rdev)}-{os.minor(info.st_rdev)}"


def _process_start(pid: int):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def read_owner(directory: Path, identity: str):
    """The current owner's metadata, or None when unreadable."""
    try:
        data = json.loads((directory / f"{identity}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get("root")
    kind = "gcs" if isinstance(root, str) and (Path(root) / "px4_gcs_bridge").is_dir() else "firmware-workspace"
    return {"kind": kind, "sessionId": data.get("sessionId"), "pid": data.get("pid"),
            "device": data.get("device"), "tcpPort": data.get("tcpPort")}


class SerialLease:
    """Holds the flock for one character device until `release`."""

    def __init__(self, device: str, session_id: str):
        self.canonical, self.identity = device_identity(device)
        self.session_id = session_id
        self._fd = None
        self.directory = None

    def acquire(self) -> None:
        if not LEASE_SUPPORTED:
            return
        import fcntl
        directory = runtime_root() / "uart"
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid():
            raise BridgeError("PERMISSION_DENIED", "unsafe UART runtime directory")
        directory.chmod(0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(directory / f"{self.identity}.lock", flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            owner = read_owner(directory, self.identity)
            raise BridgeError("PORT_BUSY", f"{self.canonical} is in use by another session",
                              {"owner": owner}) from None
        except BaseException:
            os.close(fd)
            raise
        self._fd, self.directory = fd, directory
        _atomic_json(directory / f"{self.identity}.json", self.metadata())

    def metadata(self) -> dict:
        return {"sessionId": self.session_id, "pid": os.getpid(), "start": _process_start(os.getpid()),
                "device": str(self.canonical), "identity": self.identity, "root": str(PACKAGE_ROOT),
                "tcpPort": None}

    def release(self) -> None:
        if self._fd is None:
            return
        path = self.directory / f"{self.identity}.json"
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("sessionId") == self.session_id:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass
        os.close(self._fd)
        self._fd = None
