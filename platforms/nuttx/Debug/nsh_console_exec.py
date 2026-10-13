#!/usr/bin/env python3
"""Run NuttX NSH commands non-interactively and capture their output.

Transports (works with any NuttX/PX4 NSH console):
  --rtt [HOST:]PORT      (default, :19021) SEGGER RTT ch0 bridged by JLinkExe;
                         start it with nuttx-rtt-bridge.sh first
  --serial DEV           UART console, e.g. /dev/ttyUSB0 (--baud, 115200 8N1)

Each command is sent, then output is read until the next `nsh> ` prompt (or
--timeout). The echoed command line is stripped. Exit code 1 if a command
timed out without a prompt (hung shell / wrong console / CPU halted).

  nsh_console_exec.py 'uname -a' 'ps' 'free'
  nsh_console_exec.py --serial /dev/ttyUSB0 'dmesg'
  svd_register_tool.py cmd nsh R_SCI4.CCR0 R_SCI4.CESR \
      | nsh_console_exec.py -f - | svd_register_tool.py decode-log  # CPU-side reads
  nsh_console_exec.py -f cmds.txt --log /tmp/nsh.log
  nsh_console_exec.py --monitor --timeout 3 > drain.log   # listen only
  nsh_console_exec.py --timeout 60 --until 'IPCTEST_RESULT .*mode=ping' \
      'ipctest --ping -d /dev/ipcc1'          # wait for a background builtin

--marker ends each command on an `echo <unique marker>` sent right after it
instead of on the trailing prompt. Use it when tasks print log lines while the
shell is idle (PX4 images with DEBUG_INFO): a line that lands after `nsh> `
leaves the buffer not ending in a prompt, and the prompt mode times out.
  nsh_console_exec.py --marker 'ps' 'free' 'uorb top -1'

--monitor sends nothing: it prints console output until --timeout or SIGTERM.
Use it to drain lines a background task printed while no client was attached
(RTT keeps them in the target's up-buffer) without disturbing the shell.

Never send commands the user did not ask for: NSH can write memory (mw addr=v),
reboot, or kill tasks. Read-only commands are safe defaults.
"""
import argparse
import os
import re
import signal
import socket
import sys
import time

PROMPT = b"nsh> "
# VT100 CSI sequences (CONFIG_NSH_VT100 emits ESC[K after each prompt).
ANSI_CSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


class Serial:
    def __init__(self, port, baud):
        import serial  # pyserial
        self.s = serial.Serial(port, baud, timeout=0.05)

    def write(self, data):
        self.s.write(data)

    def read(self):
        return self.s.read(4096)

    def close(self):
        self.s.close()


class Rtt:
    # JLinkExe greets each client with a banner (carrying the probe serial) and
    # serves one client at a time: a new client is refused until the previous
    # one (or a port probe) is released. Retry briefly; never echo the banner.
    BUSY = b"already is an active connection"
    BANNER_END = b"Process: JLinkExe\r\n"

    def __init__(self, spec, retry_s=5.0):
        host, _, port = spec.rpartition(":")
        deadline = time.monotonic() + retry_s
        while True:
            self.s = socket.create_connection((host or "127.0.0.1", int(port)), timeout=3)
            self.s.settimeout(0.05)
            self.pending, busy = self._skip_banner()
            if not busy:
                return
            self.s.close()
            if time.monotonic() > deadline:
                raise ConnectionError("RTT bridge busy: another client is connected")
            time.sleep(0.3)

    def _skip_banner(self, wait=0.5):
        buf, end = b"", time.monotonic() + wait
        while time.monotonic() < end and self.BANNER_END not in buf:
            try:
                data = self.s.recv(4096)
            except socket.timeout:
                continue
            if not data:
                return b"", True
            buf += data
            if self.BUSY in buf:
                return b"", True
        if self.BANNER_END in buf:
            return buf.split(self.BANNER_END, 1)[1], False
        return buf, False  # no banner (non-SEGGER bridge): keep everything

    def write(self, data):
        # RTT down-buffer is drained by a 1 ms poll; pace bytes so none drop.
        for b in data:
            self.s.sendall(bytes([b]))
            time.sleep(0.002)

    def read(self):
        if self.pending:
            data, self.pending = self.pending, b""
            return data
        try:
            data = self.s.recv(4096)
        except socket.timeout:
            return b""
        if data == b"":
            raise ConnectionError("RTT bridge closed the connection")
        return data

    def close(self):
        self.s.close()


def read_until_prompt(io, timeout, quiet=0.15):
    """Read until PROMPT is seen and the line has been quiet for `quiet` s."""
    buf, deadline, last = b"", time.monotonic() + timeout, time.monotonic()
    while time.monotonic() < deadline:
        chunk = io.read()
        if chunk:
            buf, last = buf + chunk, time.monotonic()
        elif ANSI_CSI.sub(b"", buf).rstrip().endswith(PROMPT.rstrip()) and \
                time.monotonic() - last > quiet:
            return buf, True
    return buf, False


def read_until_match(io, pattern, buf, deadline):
    """Keep reading past the prompt until a complete line matches `pattern`.
    NSH without CONFIG_SCHED_WAITPID runs builtins in the background
    ("app [pid:prio]"), so their output lands after the prompt."""
    rx = re.compile(pattern.encode(), re.M)
    while time.monotonic() < deadline:
        if any(rx.search(ln) for ln in ANSI_CSI.sub(b"", buf).split(b"\n")[:-1]):
            return buf, True
        buf += io.read()
    return buf, False


def read_until_marker(io, marker, timeout):
    """Read until a complete line equals `marker` (the output of `echo marker`,
    not its echo, which carries the `echo ` prefix)."""
    want = marker.encode()
    buf, deadline = b"", time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = ANSI_CSI.sub(b"", buf).replace(b"\r", b"").split(b"\n")
        if any(ln.strip() == want for ln in lines[:-1]):
            return buf, True
        buf += io.read()
    return buf, False


def clean_marker(raw, cmd, marker):
    """Drop the echoed command, the marker echo and output, and bare prompts."""
    text = ANSI_CSI.sub(b"", raw).decode(errors="replace").replace("\r", "")
    drop = {cmd.strip(), f"echo {marker}", marker, ""}
    out = []
    for line in text.split("\n"):
        body = line.strip()
        while body.startswith("nsh>"):
            body = body[4:].strip()
        if body in drop and (body or not out):
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def clean(raw, cmd):
    text = ANSI_CSI.sub(b"", raw).decode(errors="replace").replace("\r", "")
    lines = text.split("\n")
    if lines and lines[0].strip().endswith(cmd.strip()):
        lines = lines[1:]  # drop echoed command line
    while lines and lines[-1].strip() in ("nsh>", ""):
        lines.pop()
    return "\n".join(lines)


def monitor(io, duration):
    """Print console output as it arrives, sending nothing, until `duration`
    seconds pass or SIGTERM/SIGINT arrives (both end cleanly with exit 0)."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            chunk = io.read()
            if chunk:
                sys.stdout.write(chunk.decode(errors="replace").replace("\r", ""))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--serial", metavar="DEV", help="UART console device")
    g.add_argument("--rtt", metavar="[HOST:]PORT", nargs="?", const="19021",
                   help="RTT bridge (default transport, port 19021)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=5.0,
                    help="per command (or --monitor duration), seconds")
    ap.add_argument("--eol", default="\r\n", help="line terminator (default CRLF)")
    ap.add_argument("-f", "--file", help="read commands from file (one per line, - = stdin)")
    ap.add_argument("--log", help="append raw transcript to this file")
    ap.add_argument("--monitor", action="store_true",
                    help="listen only: print output for --timeout s, send nothing")
    ap.add_argument("--until", metavar="REGEX",
                    help="after the LAST command, keep reading (within --timeout) "
                    "until an output line matches REGEX; for background builtins")
    ap.add_argument("--marker", action="store_true",
                    help="end each command on an echoed unique marker line, not "
                    "on the prompt; robust against log lines after the prompt")
    ap.add_argument("commands", nargs="*")
    a = ap.parse_args()

    def open_io():
        return Serial(a.serial, a.baud) if a.serial else Rtt(a.rtt or "19021")

    if a.monitor:
        if a.commands or a.file or a.log or a.until:
            ap.error("--monitor sends nothing: drop commands/-f/--log/--until, redirect stdout")
        io = open_io()
        try:
            monitor(io, a.timeout)
        finally:
            io.close()
        return

    cmds = list(a.commands)
    if a.file:
        fh = sys.stdin if a.file == "-" else open(a.file)
        cmds += [ln.rstrip("\n") for ln in fh if ln.strip() and not ln.startswith("#")]
    if not cmds:
        ap.error("no commands given")

    io = open_io()
    log = open(a.log, "ab") if a.log else None
    rc = 0
    tag = f"NSHX_{os.getpid()}"
    try:
        if a.marker:
            # Sync on a marker too: stale up-buffer output is read and dropped.
            io.write(f"echo {tag}_0".encode() + a.eol.encode())
            raw, ok = read_until_marker(io, f"{tag}_0", a.timeout)
        else:
            io.write(a.eol.encode())  # sync: get a fresh prompt, flush stale output
            raw, ok = read_until_prompt(io, a.timeout)
        if log:
            log.write(raw)
        if not ok:
            hint = ("0 bytes: core not running this console image, halted, or hung"
                    if not raw else f"{len(raw)} bytes, no prompt: wrong baud or "
                    f"not NSH; tail={raw[-40:]!r}")
            what = "sync marker" if a.marker else f"'{PROMPT.decode()}' prompt"
            sys.exit(f"no {what} within {a.timeout}s ({hint})")
        for n, cmd in enumerate(cmds, 1):
            io.write(cmd.encode() + a.eol.encode())
            deadline = time.monotonic() + a.timeout
            if a.marker:
                marker = f"{tag}_{n}"
                io.write(f"echo {marker}".encode() + a.eol.encode())
                raw, ok = read_until_marker(io, marker, a.timeout)
                what = f"no {marker} line"
            else:
                raw, ok = read_until_prompt(io, a.timeout)
                what = "no prompt"
            if ok and a.until and n == len(cmds):
                raw, ok = read_until_match(io, a.until, raw, deadline)
                what = f"no line matching {a.until!r}"
            if log:
                log.write(raw)
            print(f"### nsh> {cmd}")
            print(clean_marker(raw, cmd, marker) if a.marker else clean(raw, cmd))
            if not ok:
                print(f"### TIMEOUT after {a.timeout}s ({what})", file=sys.stderr)
                rc = 1
                break
    finally:
        io.close()
        if log:
            log.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
