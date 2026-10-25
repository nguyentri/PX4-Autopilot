"""Live subprocess logs, inherited build ownership and bounded cancellation."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import threading
import time
import uuid

from .doctor import HOSTILE_VARS
from .locks import inherited_fds


def get_scrubbed_env(extra_env=None):
    env = os.environ.copy()
    for variable in HOSTILE_VARS:
        env.pop(variable, None)
    env["GIT_SUBMODULES_ARE_EVIL"] = "1"
    if extra_env:
        env.update(extra_env)
    return env


class ManagedProcess:
    def __init__(self, argv, cwd=None, env=None):
        self.argv, self.cwd = argv, cwd
        self.env = get_scrubbed_env(env)
        self.proc = None
        self.cancelled = False

    def run(self, stream_stderr=True, timeout=None, preserve_streams=False):
        descriptors = list(inherited_fds())
        try:
            probe_fd = int(self.env.get("FIRMWARE_PROBE_LOCK_FD", ""))
            os.fstat(probe_fd)
            descriptors.append(probe_fd)
        except (ValueError, OSError):
            pass
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True, pass_fds=tuple(set(descriptors)))
        ownership = None
        if self.env.get("FIRMWARE_PROBE_LEASE") and self.env.get("FIRMWARE_PROBE_SERIAL"):
            from .probe import probe_directory
            from .target_state import atomic_json
            from .locks import process_start
            ownership = probe_directory(self.env["FIRMWARE_PROBE_SERIAL"]) / f"process-{uuid.uuid4().hex}.json"
            try:
                atomic_json(ownership, {"pid": self.proc.pid, "start": process_start(self.proc.pid),
                                        "token": self.env["FIRMWARE_PROBE_LEASE"],
                                        "core": self.env.get("FIRMWARE_PROBE_CORE")})
            except BaseException:
                self.cancel()
                self.proc.stdout.close()
                self.proc.stderr.close()
                raise
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        previous = {}
        if threading.current_thread() is threading.main_thread():
            def interrupted(signum, frame):
                self.cancelled = True
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, interrupted)
        started = time.monotonic()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.proc.stdout, selectors.EVENT_READ, "stdout")
                selector.register(self.proc.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    if self.cancelled:
                        self.cancel()
                    if timeout is not None and time.monotonic() - started > timeout:
                        self.cancel()
                        raise TimeoutError(f"Process timed out after {timeout} seconds")
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        outputs[key.data].extend(chunk)
                        if len(outputs[key.data]) > 2 * 1024 * 1024:
                            del outputs[key.data][:-2 * 1024 * 1024]
                        if stream_stderr:
                            destination = sys.stdout if preserve_streams and key.data == "stdout" else sys.stderr
                            destination.write(chunk.decode("utf-8", errors="replace"))
                            destination.flush()
            self.proc.wait()
            code = 130 if self.cancelled else self.proc.returncode
            return code, outputs["stdout"].decode(errors="replace"), outputs["stderr"].decode(errors="replace")
        except BaseException:
            self.cancel()
            raise
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            self.proc.stdout.close()
            self.proc.stderr.close()
            if ownership:
                ownership.unlink(missing_ok=True)

    def cancel(self, grace_period=3.0):
        self.cancelled = True
        if not self.proc:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=grace_period)
        except subprocess.TimeoutExpired:
            pass
        # The leader may exit before a descendant holding our pipes. The group
        # is still ours, and must be reaped rather than leaving the reader hung.
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
