"""Serve loop of the dual RTT bridge: one TCP listener per CR8 core, one client each.

Loaded by `rzv2h-dual-rtt-bridge.py serve`; `serve(..., memory=...)` lets tests
run the loop against a fake word memory instead of the J-Link DLL.
"""
from __future__ import annotations

import os
import selectors
import signal
import socket
import threading
import time
from pathlib import Path

DROP_CHECK_S = 1.0
REATTACH_S = 1.0


def marker(text: str) -> bytes:
    return f"\r\n<<rtt-bridge: {text}>>\r\n".encode()


class CoreLink:
    """One core: its RTT channel, listener, client and host backlog."""

    def __init__(self, core: str, listener: socket.socket, target, transport, memory, backlog: int):
        self.core, self.transport, self.memory, self.limit = core, transport, memory, backlog
        self.control_block, self.drop_counter = target
        self.listener = listener
        self.client: socket.socket | None = None
        self.backlog = bytearray()
        self.down = bytearray()
        self.channel = None
        self.lost_at = 0.0
        self.attach()

    def attach(self) -> None:
        try:
            self.channel = self.transport.RttChannel(self.memory, self.core, self.control_block, self.drop_counter)
            self.reported_drops = 0
        except ValueError as error:
            self.channel, self.lost_at = None, time.monotonic()
            self.queue(marker(f"control block lost: {error}"))

    def queue(self, data: bytes) -> None:
        self.backlog += data
        if len(self.backlog) > self.limit:
            trimmed = len(self.backlog) - self.limit
            del self.backlog[:trimmed]
            self.backlog[:0] = marker(f"host backlog trimmed: {trimmed} B")

    def accept(self) -> socket.socket | None:
        """The newly admitted client, or None when the console already has one."""
        conn, _ = self.listener.accept()
        if self.client:
            conn.sendall(marker(f"{self.core} console already has a client"))
            conn.close()
            return None
        conn.setblocking(False)
        self.client = conn
        return conn

    def drop_client(self) -> None:
        if self.client:
            self.client.close()
        self.client = None

    def receive(self) -> None:
        try:
            data = self.client.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if data:
            self.down += data
        else:
            self.drop_client()

    def poll(self, now: float, check_drops: bool) -> None:
        if not self.channel:
            if now - self.lost_at >= REATTACH_S:
                self.attach()
            return
        try:
            if check_drops:
                self.channel.verify()
            data = self.channel.read()
            if self.down:
                del self.down[:self.channel.write(bytes(self.down))]
            if check_drops and self.drop_counter is not None:
                dropped = self.channel.dropped_since_attach()
                if dropped > self.reported_drops:
                    self.queue(data)
                    data = marker(f"output dropped: {dropped - self.reported_drops} B")
                    self.reported_drops = dropped
        except ValueError as error:
            # A reload re-initialises the control block; wait for it again.
            self.channel, self.lost_at = None, now
            data = marker(f"control block lost: {error}")
        if data:
            self.queue(data)

    def flush(self) -> None:
        if not self.client or not self.backlog:
            return
        try:
            sent = self.client.send(self.backlog)
            del self.backlog[:sent]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self.drop_client()

    def close(self) -> None:
        self.drop_client()
        self.listener.close()


def serve(config: dict, transport, state_dir: Path, backlog: int, memory=None, stop_after: float | None = None) -> int:
    """Runs until SIGTERM. Exit 3 on a probe connect failure or DAP error."""
    stopping = []
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    links: list[CoreLink] = []
    # Bind before opening the J-Link DLL: JLINKARM_OpenEx starts SEGGER's own
    # RTT telnet server on 19021 (plus 19030/19080) and skips a port already taken.
    listeners: dict[str, socket.socket] = {}
    try:
        for core in ("cr8_0", "cr8_1"):
            listeners[core] = socket.create_server(("127.0.0.1", int(config["ports"][core])), reuse_port=False)
            listeners[core].setblocking(False)
    except OSError as error:
        for listener in listeners.values():
            listener.close()
        (state_dir / "bridge.failed").write_text(f"{error}\n")
        print(f"dual RTT bridge: {error}", flush=True)
        return 1
    try:
        if memory is None:
            memory = transport.AxiApMemory(config["serial"], int(os.environ.get("JLINK_SPEED", "4000")))
    except transport.DapError as error:
        for listener in listeners.values():
            listener.close()
        (state_dir / "bridge.failed").write_text(f"{error}\n")
        print(f"!! dual RTT bridge: {error}. Not retried; diagnose before reconnecting.", flush=True)
        return 3
    poll = int(os.environ.get("POLL_MS", "10")) / 1000
    selector = selectors.DefaultSelector()
    code = 0
    try:
        for core in ("cr8_0", "cr8_1"):
            link = CoreLink(core, listeners.pop(core), tuple(config["targets"][core]), transport, memory, backlog)
            links.append(link)
            selector.register(link.listener, selectors.EVENT_READ, link)
        (state_dir / "bridge.ready").write_text("up\n")
        print("dual RTT bridge serving " + ", ".join(f"{l.core}:{l.listener.getsockname()[1]}" for l in links), flush=True)
        started = last_drop = time.monotonic()
        while not stopping and (stop_after is None or time.monotonic() - started < stop_after):
            for key, _ in selector.select(poll):
                link = key.data
                if key.fileobj is link.listener:
                    admitted = link.accept()
                    if admitted:
                        selector.register(admitted, selectors.EVENT_READ, link)
                else:
                    link.receive()
                    if not link.client:
                        selector.unregister(key.fileobj)
            memory.check()
            now = time.monotonic()
            check_drops = now - last_drop >= DROP_CHECK_S
            last_drop = now if check_drops else last_drop
            for link in links:
                link.poll(now, check_drops)
                had_client = link.client
                link.flush()
                if had_client and not link.client:
                    selector.unregister(had_client)
    except transport.DapError as error:
        # The DAP is in an unknown state: no further memory access of any kind.
        (state_dir / "bridge.failed").write_text(f"{error}\n")
        print(f"!! dual RTT bridge: {error}. Stopped; diagnose before reconnecting.", flush=True)
        code = 3
    except OSError as error:
        (state_dir / "bridge.failed").write_text(f"{error}\n")
        print(f"dual RTT bridge: {error}", flush=True)
        code = 1
    finally:
        for link in links:
            link.close()
        for listener in listeners.values():
            listener.close()
        selector.close()
        memory.close()
    return code
