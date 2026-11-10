#!/usr/bin/env python3
"""Serve both RZ/V2H CR8 RTT consoles from one J-Link over the AXI-AP.

  JLINK_SERIAL=<sn> rzv2h-dual-rtt-bridge.py start <cr8_0-elf|0xADDR> <cr8_1-elf|0xADDR>
  rzv2h-dual-rtt-bridge.py status | stop

Channel 0 of CR8-0 is served raw on 127.0.0.1:${RTT_PORT_CR8_0:-19021} and of
CR8-1 on 127.0.0.1:${RTT_PORT_CR8_1:-19031}, one client each. The bridge reads
the control blocks over the system bus and never connects a core, so it cannot
halt or reset one; it still owns the probe while up (stop it before GDB).
Output is drained while no client is connected and replayed (last 1 MiB) to
the first one. Lost output is reported in-band as `<<rtt-bridge: ...>>` lines:
`g_syslog_rtt_dropped` growth on the target, or host backlog trimming.

Env: JLINK_SERIAL, STATE_DIR (${TMPDIR:-/tmp}/nuttx-rtt-bridge), RTT_PORT_CR8_0,
RTT_PORT_CR8_1, POLL_MS (10), JLINK_SPEED (4000 kHz).
Exit: 0 up/stopped, 1 failed (busy, port in use, no control block), 2 usage,
3 probe connect failure or DAP error (no retry, no further memory access).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rzv2h_dual_rtt_transport", HERE / "rzv2h-dual-rtt-transport.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)

CORES = ("cr8_0", "cr8_1")
STATE_DIR = Path(os.environ.get("STATE_DIR") or Path(os.environ.get("TMPDIR", "/tmp")) / "nuttx-rtt-bridge")
PIDFILE = STATE_DIR / "bridge.pid"
BACKLOG = 1 << 20
NM_FALLBACK = "/opt/arm-gnu-toolchain-13.2.Rel1/bin/arm-none-eabi-nm"


def ports() -> dict[str, int]:
    out = {}
    for core, default in zip(CORES, (19021, 19031)):
        value = os.environ.get("RTT_PORT_" + core.upper(), str(default))
        if not value.isdigit() or not 1024 <= int(value) <= 65535 or int(value) in (19022, 19030, 19080, 19081):
            sys.exit(f"RTT_PORT_{core.upper()} must be a free TCP port number (not a JLinkExe port)")
        out[core] = int(value)
    if len(set(out.values())) != 2:
        sys.exit("the two RTT ports must differ")
    return out


def symbols(image: str) -> tuple[int, int | None]:
    """_SEGGER_RTT and the optional drop counter from an ELF, or a bare address."""
    if image.lower().startswith("0x"):
        return int(image, 16), None
    nm = shutil.which("arm-none-eabi-nm") or NM_FALLBACK
    table = {}
    for line in subprocess.run([nm, image], check=True, capture_output=True, text=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            table[parts[2]] = int(parts[0], 16)
    if "_SEGGER_RTT" not in table:
        sys.exit(f"_SEGGER_RTT not in {image} (not an RTT-console build?)")
    return table["_SEGGER_RTT"], table.get("g_syslog_rtt_dropped")


def process_start(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def running() -> int | None:
    """The bridge PID when the recorded process is still the bridge (no PID reuse)."""
    try:
        pid = int(PIDFILE.read_text())
        start = (STATE_DIR / "bridge.pid.identity").read_text().splitlines()[0]
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError, IndexError):
        return None
    return pid if process_start(pid) == start and b"serve" in cmdline and any(b"rzv2h-dual-rtt-bridge" in a for a in cmdline) else None


def clear_state() -> None:
    for name in ("bridge.pid", "bridge.pid.identity", "bridge.pid.port", "bridge.ready", "bridge.failed"):
        (STATE_DIR / name).unlink(missing_ok=True)


def stop() -> int:
    pid = running()
    if pid:
        os.killpg(pid, signal.SIGTERM)
        for tick in range(100):
            if process_start(pid) is None:
                break
            if tick == 50:
                os.killpg(pid, signal.SIGKILL)
            time.sleep(0.05)
        else:
            print("dual RTT bridge has not exited", file=sys.stderr)
            return 1
    print("dual RTT bridge stopped, probe released" if pid else "no bridge running")
    clear_state()
    return 0


def start(images: list[str]) -> int:
    serial = os.environ.get("JLINK_SERIAL")
    if not serial or not serial.isdigit():
        print("set JLINK_SERIAL to the exact probe serial", file=sys.stderr)
        return 2
    port_map = ports()
    targets = {core: symbols(image) for core, image in zip(CORES, images)}
    if running():
        print("bridge already running", file=sys.stderr)
        return 1
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    clear_state()
    config = {"serial": int(serial), "ports": port_map, "targets": targets}
    log = open(STATE_DIR / "dual-rtt-bridge.log", "w")
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", json.dumps(config)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    PIDFILE.write_text(f"{child.pid}\n")
    (STATE_DIR / "bridge.pid.identity").write_text(f"{process_start(child.pid)}\ndual\n{serial}\ncr8_0+cr8_1\n")
    (STATE_DIR / "bridge.pid.port").write_text(f"{port_map['cr8_0']} {port_map['cr8_1']}\n")
    deadline = time.monotonic() + 20
    while not (STATE_DIR / "bridge.ready").exists():
        code = child.poll()
        if code is not None or time.monotonic() > deadline:
            if code is None:
                child.kill()
                child.wait()
            print((STATE_DIR / "dual-rtt-bridge.log").read_text()[-2000:], file=sys.stderr, end="")
            clear_state()
            return code if code in (1, 3) else 1
        time.sleep(0.05)
    for core in CORES:
        print(f"RTT bridge up: {core} _SEGGER_RTT=0x{targets[core][0]:08x} -> 127.0.0.1:{port_map[core]}")
    return 0


def status() -> int:
    pid = running()
    if not pid:
        failed = STATE_DIR / "bridge.failed"
        print("not running" + (f" (last failure: {failed.read_text().strip()})" if failed.exists() else ""))
        return 0
    port_text = (STATE_DIR / "bridge.pid.port").read_text().split()
    print(f"running pid {pid}, dual cr8_0:{port_text[0]} cr8_1:{port_text[1]}")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["start"] and len(argv) == 3:
        return start(argv[1:])
    if argv[:1] == ["serve"] and len(argv) == 2:
        serve_spec = importlib.util.spec_from_file_location("rzv2h_dual_rtt_serve", HERE / "rzv2h-dual-rtt-serve.py")
        serve = importlib.util.module_from_spec(serve_spec)
        serve_spec.loader.exec_module(serve)
        return serve.serve(json.loads(argv[1]), transport, STATE_DIR, BACKLOG)
    if argv in (["stop"], ["status"]):
        return stop() if argv[0] == "stop" else status()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
