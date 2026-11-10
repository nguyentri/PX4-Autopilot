"""Foreground serial client with a host-wide character-device lease.

Metadata is diagnostic only. Kernel flock ownership, including the inherited
client descriptor, is the authority; a missing supervisor never frees a live UART.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

from .contracts import REPO_ROOT
from .locks import process_start
from .probe import runtime_root
from .target_state import atomic_json
from .verification import OperationError

HELPER = REPO_ROOT / "platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-type-cr8_0-serial.sh"


def canonical_device(value):
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Select a workspace-host character device, preferably /dev/serial/by-id/…")
    device = Path(value).resolve(strict=True)
    info = device.stat()
    if not stat.S_ISCHR(info.st_mode) or not os.access(device, os.R_OK | os.W_OK):
        raise ValueError("serial device must be a readable/writable character device")
    return device, f"{os.major(info.st_rdev)}-{os.minor(info.st_rdev)}"


def device_lock(identity):
    directory = runtime_root() / "uart"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise ValueError("Unsafe UART runtime directory")
    directory.chmod(0o700)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / f"{identity}.lock", flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


def run(device, session_id):
    canonical, identity = canonical_device(device)
    if not HELPER.is_file() or not os.access(HELPER, os.X_OK) or not shutil.which("picocom"):
        raise ValueError("serial requires picocom and the repository interactive serial helper on the workspace host")
    fd = device_lock(identity)
    directory = runtime_root() / "uart"
    child = None
    received = []
    previous = {}
    try:
        metadata = {"sessionId": session_id, "pid": os.getpid(), "start": process_start(os.getpid()),
                    "device": str(canonical), "identity": identity, "root": str(REPO_ROOT)}
        atomic_json(directory / f"{identity}.json", metadata)
        def cancelled(signum, _frame):
            received.append(signum)
            if child is not None and child.poll() is None:
                child.send_signal(signum)
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, cancelled)
        # No new process group: picocom keeps the terminal's foreground TTY.
        child = subprocess.Popen([str(HELPER), str(canonical)], env={**os.environ, "BAUD": "115200"}, pass_fds=(fd,))
        metadata["childPid"] = child.pid
        metadata["childStart"] = process_start(child.pid)
        atomic_json(directory / f"{identity}.json", metadata)
        deadline = None
        while child.poll() is None:
            if received:
                if deadline is None:
                    child.send_signal(received[-1])
                    deadline = time.monotonic() + 2
                elif time.monotonic() >= deadline:
                    child.kill()
            time.sleep(0.02)
        return 130 if received else (0 if child.returncode == 0 else 1)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        # Never LOCK_UN: a client surviving supervisor death must retain flock.
        os.close(fd)


def run_tcp(device, session_id, port):
    """Holds the same device lease as the picocom client while the TCP relay runs."""
    from .serial_tcp_relay import relay
    canonical, identity = canonical_device(device)
    fd = device_lock(identity)
    try:
        atomic_json(runtime_root() / "uart" / f"{identity}.json",
                    {"sessionId": session_id, "pid": os.getpid(), "start": process_start(os.getpid()),
                     "device": str(canonical), "identity": identity, "root": str(REPO_ROOT), "tcpPort": port})
        return relay(canonical, port, lambda line: print(line, flush=True))
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--baud", choices=["115200"], required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--check", action="store_true", help="Check kernel lease availability without launching a client")
    parser.add_argument("--tcp", type=int, metavar="PORT",
                        help="Serve the UART raw on 127.0.0.1:PORT (one client) instead of launching picocom")
    args = parser.parse_args(argv)
    try:
        uuid.UUID(args.session_id)
        if args.check:
            _, identity = canonical_device(args.device)
            os.close(device_lock(identity))
            return 0
        if args.tcp is not None:
            if not 1024 <= args.tcp <= 65535:
                raise ValueError("--tcp must be a TCP port number")
            return run_tcp(args.device, args.session_id, args.tcp)
        return run(args.device, args.session_id)
    except BlockingIOError:
        print("UART_BUSY: stop the existing console owner before reopening this UART", file=sys.stderr)
        return 4
    except (OSError, ValueError, OperationError) as error:
        print(f"serial prerequisite: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
