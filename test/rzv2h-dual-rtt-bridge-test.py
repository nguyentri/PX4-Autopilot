#!/usr/bin/env python3
"""Host tests of the dual RTT bridge: ring arithmetic, TAR chunking and the serve loop on fake memory."""
from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

DEBUG = Path(__file__).resolve().parents[1] / "platforms/nuttx/Debug"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), DEBUG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = load("rzv2h-dual-rtt-transport")
serve_module = load("rzv2h-dual-rtt-serve")


class FakeMemory(transport.WordMemory):
    def __init__(self):
        self.bytes = bytearray(0x10000)
        self.lock = threading.Lock()

    def read_words(self, addr, count):
        assert addr % 4 == 0
        with self.lock:
            return [int.from_bytes(self.bytes[addr + 4 * i: addr + 4 * i + 4], "little") for i in range(count)]

    def write_word(self, addr, value):
        assert addr % 4 == 0
        with self.lock:
            self.bytes[addr: addr + 4] = value.to_bytes(4, "little")


class FakeTarget:
    """One RTT control block: 1 up and 1 down buffer, a drop counter."""

    def __init__(self, memory, base, up_size=64, down_size=16):
        self.memory, self.cb, self.drop = memory, base, base + 0x200
        self.up_buf, self.down_buf = base + 0x400, base + 0x800
        self.up_size, self.down_size = up_size, down_size
        memory.write_bytes(base, b"SEGGER RTT\0\0\0\0\0\0")
        memory.write_word(base + 0x10, 1)
        memory.write_word(base + 0x14, 1)
        for i, value in enumerate([0, self.up_buf, up_size, 0, 0, 0]):
            memory.write_word(base + 0x18 + 4 * i, value)
        for i, value in enumerate([0, self.down_buf, down_size, 0, 0, 0]):
            memory.write_word(base + 0x30 + 4 * i, value)
        memory.write_word(self.drop, 7)  # not zeroed at boot

    def emit(self, data: bytes):
        """Target-side up-buffer write (wraps)."""
        write, read = self.memory.read_words(self.cb + 0x18 + 12, 2)
        for byte in data:
            assert (write + 1) % self.up_size != read, "fake target overflow"
            self.memory.write_bytes(self.up_buf + write, bytes([byte]))
            write = (write + 1) % self.up_size
        self.memory.write_word(self.cb + 0x18 + 12, write)

    def take(self) -> bytes:
        """Target-side down-buffer read."""
        write, read = self.memory.read_words(self.cb + 0x30 + 12, 2)
        out = b""
        while read != write:
            out += self.memory.read_bytes(self.down_buf + read, 1)
            read = (read + 1) % self.down_size
        self.memory.write_word(self.cb + 0x30 + 16, read)
        return out


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def test_tar_chunks():
    expect(list(transport.tar_chunks(0x3F8, 4)) == [(0x3F8, 2), (0x400, 2)], "TAR must restart at a 1 KiB boundary")
    expect(list(transport.tar_chunks(0x1000, 256)) == [(0x1000, 256)], "a whole aligned block stays one burst")
    expect(sum(n for _, n in transport.tar_chunks(0x7FC, 600)) == 600, "chunking keeps the word count")


def test_ring_wrap_and_down_space():
    memory = FakeMemory()
    target = FakeTarget(memory, 0x1000)
    channel = transport.RttChannel(memory, "cr8_0", 0x1000, target.drop)
    target.emit(b"x" * 50)
    expect(channel.read() == b"x" * 50, "linear read")
    target.emit(b"0123456789abcdefghij")  # wraps at 64
    expect(channel.read() == b"0123456789abcdefghij", "wrapped read")
    expect(channel.read() == b"", "drained buffer reads empty")
    expect(channel.free() == 15, "empty down buffer keeps one slot free")
    expect(channel.write(b"A" * 20) == 15, "down write stops at free space")
    expect(target.take() == b"A" * 15, "target sees exactly the written bytes")
    target.take()
    expect(channel.write(b"hello\r\n") == 7 and target.take() == b"hello\r\n", "down write wraps")
    memory.write_word(target.drop, 7 + 300)
    expect(channel.dropped_since_attach() == 300, "drops are counted from attach, not boot")
    try:
        transport.RttChannel(memory, "cr8_1", 0x5000)
        raise AssertionError("missing control block accepted")
    except ValueError:
        pass


def read_until(conn, needle: bytes, timeout=3.0) -> bytes:
    conn.settimeout(0.2)
    data, deadline = b"", time.monotonic() + timeout
    while needle not in data and time.monotonic() < deadline:
        try:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        except socket.timeout:
            pass
    return data


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_serve_loop():
    memory = FakeMemory()
    targets = {"cr8_0": FakeTarget(memory, 0x1000), "cr8_1": FakeTarget(memory, 0x3000)}
    ports = {"cr8_0": free_port(), "cr8_1": free_port()}
    config = {"ports": ports, "targets": {core: [t.cb, t.drop] for core, t in targets.items()}}
    targets["cr8_0"].emit(b"boot-0\r\n")  # before any client: must be replayed
    with tempfile.TemporaryDirectory() as state:
        result = {}
        thread = threading.Thread(target=lambda: result.update(code=serve_module.serve(
            config, transport, Path(state), 1 << 20, memory=memory, stop_after=4.0)))
        thread.start()
        deadline = time.monotonic() + 3
        while not (Path(state) / "bridge.ready").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        expect((Path(state) / "bridge.ready").exists(), "serve never reported ready")
        a = socket.create_connection(("127.0.0.1", ports["cr8_0"]))
        b = socket.create_connection(("127.0.0.1", ports["cr8_1"]))
        expect(b"boot-0" in read_until(a, b"boot-0"), "boot output replayed to the first client")
        targets["cr8_1"].emit(b"core1 line\r\n")
        expect(b"core1 line" in read_until(b, b"core1 line"), "CR8-1 output on its own port")
        a.sendall(b"ps\r\n")
        deadline = time.monotonic() + 2
        got = b""
        while b"ps\r\n" not in got and time.monotonic() < deadline:
            got += targets["cr8_0"].take()
            time.sleep(0.02)
        expect(got == b"ps\r\n", f"input reaches the CR8-0 down buffer: {got!r}")
        expect(targets["cr8_1"].take() == b"", "input never leaks to the other core")
        second = socket.create_connection(("127.0.0.1", ports["cr8_1"]))
        expect(b"already has a client" in read_until(second, b"client"), "a second client is refused")
        second.close()
        memory.write_word(targets["cr8_1"].drop, 7 + 42)
        expect(b"output dropped: 42 B" in read_until(b, b"dropped"), "drop counter growth is reported in-band")
        memory.write_bytes(targets["cr8_0"].cb, b"XXXXXXXXXX")  # reload wipes the block
        expect(b"control block lost" in read_until(a, b"lost"), "a lost control block is reported")
        memory.write_bytes(targets["cr8_0"].cb, b"SEGGER RTT")
        targets["cr8_0"].emit(b"after reload\r\n")
        expect(b"after reload" in read_until(a, b"after reload"), "the bridge re-attaches after a reload")
        a.close()
        b.close()
        thread.join(6)
        expect(result.get("code") == 0, f"serve exit {result}")


class FaultyMemory(FakeMemory):
    def __init__(self, target_memory):
        super().__init__()
        self.bytes = target_memory.bytes
        self.armed = False

    def check(self):
        if self.armed:
            raise transport.DapError("DAP fault (CTRL/STAT=0xf0000032)")


def test_dap_error_stops_without_retry():
    base = FakeMemory()
    targets = {"cr8_0": FakeTarget(base, 0x1000), "cr8_1": FakeTarget(base, 0x3000)}
    memory = FaultyMemory(base)
    config = {"ports": {"cr8_0": free_port(), "cr8_1": free_port()},
              "targets": {core: [t.cb, None] for core, t in targets.items()}}
    memory.armed = True
    with tempfile.TemporaryDirectory() as state:
        code = serve_module.serve(config, transport, Path(state), 1 << 20, memory=memory, stop_after=2.0)
        expect(code == 3, "a DAP error exits 3")
        expect("DAP fault" in (Path(state) / "bridge.failed").read_text(), "the failure is recorded for status")


def test_ports_bound_before_the_probe_opens():
    """The J-Link DLL starts its own RTT telnet server on 19021 when it opens."""
    base = FakeMemory()
    targets = {"cr8_0": FakeTarget(base, 0x1000), "cr8_1": FakeTarget(base, 0x3000)}
    ports = {"cr8_0": free_port(), "cr8_1": free_port()}
    config = {"serial": 1, "ports": ports, "targets": {core: [t.cb, None] for core, t in targets.items()}}
    dll_listener = {}

    def opening_dll(serial, speed):
        try:
            dll_listener["socket"] = socket.create_server(("127.0.0.1", ports["cr8_0"]))
        except OSError:
            dll_listener["skipped"] = True  # what the DLL does when the port is taken
        return base

    probe = type("Transport", (), {"AxiApMemory": staticmethod(opening_dll), "DapError": transport.DapError,
                                   "RttChannel": transport.RttChannel})
    with tempfile.TemporaryDirectory() as state:
        code = serve_module.serve(config, probe, Path(state), 1 << 20, stop_after=0.5)
        if "socket" in dll_listener:
            dll_listener["socket"].close()
        expect(dll_listener.get("skipped"), "the bridge owns its port before the DLL opens")
        expect(code == 0 and (Path(state) / "bridge.ready").exists(), f"serve came up (exit {code})")


def test_cli_usage():
    bridge = DEBUG / "rzv2h-dual-rtt-bridge.py"
    with tempfile.TemporaryDirectory() as state:
        env = {"PATH": "/usr/bin:/bin", "STATE_DIR": state}
        usage = subprocess.run([sys.executable, str(bridge)], env=env, capture_output=True, text=True)
        expect(usage.returncode == 2, "no action is a usage error")
        no_serial = subprocess.run([sys.executable, str(bridge), "start", "0x1000", "0x2000"], env=env,
                                   capture_output=True, text=True)
        expect(no_serial.returncode == 2 and "JLINK_SERIAL" in no_serial.stderr, "start needs the probe serial")
        same = subprocess.run([sys.executable, str(bridge), "start", "0x1000", "0x2000"],
                              env=dict(env, JLINK_SERIAL="1", RTT_PORT_CR8_1="19021"), capture_output=True, text=True)
        expect(same.returncode != 0 and "differ" in same.stderr, "equal ports are refused")
        status = subprocess.run([sys.executable, str(bridge), "status"], env=env, capture_output=True, text=True)
        expect(status.returncode == 0 and "not running" in status.stdout, "status with no bridge")
        stop = subprocess.run([sys.executable, str(bridge), "stop"], env=env, capture_output=True, text=True)
        expect(stop.returncode == 0 and "no bridge running" in stop.stdout, "stop with no bridge")


if __name__ == "__main__":
    for test in (test_tar_chunks, test_ring_wrap_and_down_space, test_serve_loop,
                 test_dap_error_stops_without_retry, test_ports_bound_before_the_probe_opens, test_cli_usage):
        test()
        print(f"ok {test.__name__}")
    print("dual RTT bridge tests passed")
