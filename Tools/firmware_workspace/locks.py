"""Exclusive build coordination with verified, inherited kernel lock handles."""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import uuid
from pathlib import Path

from .contracts import REPO_ROOT

LOCK_ENV_VAR = "FIRMWARE_BUILD_LOCK_TOKEN"
FD_ENV_VAR = "FIRMWARE_BUILD_LOCK_FD"
NUTTX_TREE_DIR = REPO_ROOT / "platforms/nuttx/NuttX/nuttx"
DEFAULT_LOCK_FILE = NUTTX_TREE_DIR.resolve().parent / ".build.lock"
DEFAULT_META_FILE = DEFAULT_LOCK_FILE.with_suffix(".lock.meta")


def process_start(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def inherited_fds():
    value = os.environ.get(FD_ENV_VAR, "")
    try:
        fd = int(value)
        os.fstat(fd)
        return (fd,)
    except (ValueError, OSError):
        return ()


class BuildLockContentionError(RuntimeError):
    pass


class BuildLock:
    def __init__(self, lock_path=None, timeout=10.0):
        self.lock_path = Path(lock_path or os.environ.get("FIRMWARE_BUILD_LOCK_PATH", DEFAULT_LOCK_FILE))
        self.meta_path = self.lock_path.with_suffix(".lock.meta")
        self.timeout = timeout
        self._fd = None
        self._token = None
        self._is_nested = False
        self._previous = {}

    def inherited(self):
        """A token alone is never ownership: require the live inherited flock FD."""
        try:
            fd = int(os.environ[FD_ENV_VAR])
            meta = json.loads(self.meta_path.read_text())
            descriptor, actual = os.fstat(fd), self.lock_path.stat()
            if (descriptor.st_dev, descriptor.st_ino) != (actual.st_dev, actual.st_ino):
                return False
            if not meta.get("token") or meta["token"] != os.environ.get(LOCK_ENV_VAR):
                return False
            if not process_start(meta["pid"]) or process_start(meta["pid"]) != meta.get("start"):
                return False
            # This succeeds for a shared open-file description, fails for an
            # unrelated descriptor while the real owner holds the lock.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd, self._token, self._is_nested = fd, meta["token"], True
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def acquire(self):
        if self.inherited():
            return self._token
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise BuildLockContentionError("Another build owns this physical NuttX tree")
                time.sleep(0.05)
        os.set_inheritable(self._fd, True)
        self._token = uuid.uuid4().hex
        self._previous = {key: os.environ.get(key) for key in (LOCK_ENV_VAR, FD_ENV_VAR)}
        meta = {"pid": os.getpid(), "start": process_start(os.getpid()), "token": self._token}
        self.meta_path.write_text(json.dumps(meta))
        os.environ[LOCK_ENV_VAR] = self._token
        os.environ[FD_ENV_VAR] = str(self._fd)
        return self._token

    def release(self):
        if self._is_nested or self._fd is None:
            return
        try:
            self.meta_path.unlink(missing_ok=True)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
            for key, value in self._previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def main():
    if sys.argv[1:] == ["check"]:
        return 0 if BuildLock().inherited() else 1
    if len(sys.argv) < 3 or sys.argv[1] != "exec":
        print("Usage: python3 -m firmware_workspace.locks exec <command...> | check", file=sys.stderr)
        return 2
    try:
        with BuildLock() as lock:
            from .process import ManagedProcess
            code, _, _ = ManagedProcess(sys.argv[2:]).run(preserve_streams=True)
            return code
    except BuildLockContentionError as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
