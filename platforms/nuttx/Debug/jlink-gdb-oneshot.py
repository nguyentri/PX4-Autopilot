#!/usr/bin/env python3
"""Run GDB commands against a running core through a single-run J-Link GDB
server, then detach so the core keeps running. Read-only by default.

  JLINK_SERIAL=<sn> jlink-gdb-oneshot.py cr8_0 build/<t>/<t>.elf \\
      -ex 'bt' -ex 'p g_hrt' -ex 'info registers pc cpsr'
  JLINK_SERIAL=<sn> jlink-gdb-oneshot.py cr8_1 <cr8_1.elf> -x snippet.gdb

<core>: cr8_0 | cr8_1 (RZ/V2H Cortex-R8) or any J-Link device name.
cm33 is refused: SEGGER's RZ/V2H support resets and re-initialises the SoC on
every CM33 connect, which kills the CR8 images (pass --allow-mutation and
the J-Link device name only when that is intended).

What it does, in order:
  1. starts JLinkGDBServerCLExe for this probe and core with -noreset -noir
     -singlerun -LocalhostOnly, owned by this process, on --port;
  2. runs gdb-multiarch -batch: target remote, prints ONESHOT_ATTACHED, your
     -x/-ex commands in the given order, then detach (always, even after an
     error: each -ex runs on its own; an error inside an -x file skips only
     the rest of that file);
  3. retries the attach up to 3 times (the first remote connect after a
     server start sometimes fails), stops the server and scans its log.

The core is halted from attach to detach (about 1-3 s). On a dual-core
image a CR8-0 halt starves the CR8-1 output lease (50 ms): never attach to
CR8-0 while armed. RTT and the GDB server cannot share the probe: stop
nuttx-rtt-bridge.sh first.

Read-only check (skipped with --allow-mutation): every -ex and -x line must
be an inspection command (print/x/info/bt/frame/list/ptype/disassemble/
printf/output/echo/dump/display settings); assignments, ++/--, function
calls, set var/register, load/restore/call/jump/continue/step/monitor/
break/watch/source/shell/python are refused before the probe is touched.

Exit: 0 ok, 2 usage or refused command, 3 could not attach, 4 gdb did not
detach (timeout or crash; the server restores the run state on exit),
5 the J-Link log shows the core was reset or is held in reset (tell the
user; the image there is gone and must be reloaded), 6 attached and detached
but a gdb command failed (unknown symbol or member, unreadable memory; a -x
file stops at its first error), so part of the read is missing.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ALIASES = {"cr8_0": "R9A09G057H44_R8_0", "cr8_1": "R9A09G057H44_R8_1"}
# DBGEN also shows when the core was never released from reset (not running).
RESET_MARKERS = re.compile(r"Resetting via Reset pin|cold reset sequence|DBGEN is not asserted")
READ_ONLY = {
    "print", "p", "inspect", "output", "printf", "echo", "x", "info", "i",
    "bt", "backtrace", "where", "frame", "f", "up", "down", "list", "l",
    "disassemble", "ptype", "whatis", "dump", "thread", "if", "while",
    "else", "end", "show",
}
SAFE_SET = {"pagination", "print", "confirm", "width", "height", "logging",
            "style", "charset", "listsize", "max-value-size"}
REGISTER = re.compile(r"\$(r\d+|sp|lr|pc|cpsr|spsr|fpscr|[dsq]\d+|xpsr|msp|psp)\b", re.I)
ASSIGN = re.compile(r"(?<![=!<>])=(?!=)|\+\+|--")
CALL = re.compile(r"(?<![\w$.>:])([A-Za-z_]\w*)\s*\(")
NOT_CALLS = {"sizeof", "alignof", "_Alignof", "decltype"}


def mutation_reason(line):
    """Return why `line` could change the target, or None if it only reads."""
    body = line.strip()
    if not body or body.startswith("#"):
        return None
    word = re.split(r"[\s/]", body, 1)[0]
    if word == "set":
        rest = body[3:].strip()
        if rest.split(" ", 1)[0] in SAFE_SET:
            return None
        if rest.startswith("$") and not REGISTER.match(rest):
            return None  # host-side convenience variable
        return "set changes target state"
    if word not in READ_ONLY:
        return f"'{word}' is not a read-only inspection command"
    if word in ("echo", "dump"):
        return None
    expr = body.split(None, 1)[1] if " " in body else ""
    expr = re.sub(r'"(\\.|[^"\\])*"', '""', expr)  # ignore string literals
    if ASSIGN.search(expr):
        return "expression assigns to target memory or a register"
    calls = [c for c in CALL.findall(expr) if c not in NOT_CALLS]
    if calls:
        return f"expression calls target function {calls[0]}()"
    return None


def tool(env, name, fallback):
    return os.environ.get(env) or shutil.which(name) or fallback


def owns_listener(pid, port):
    want = f":{port:04X}"
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in Path(table).read_text().splitlines()[1:]:
                f = line.split()
                if f[1].upper().endswith(want) and f[3] == "0A":
                    inodes.add(f"socket:[{f[9]}]")
        except OSError:
            pass
    try:
        return any(os.readlink(fd) in inodes for fd in Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return False


def port_busy(port):
    want = f":{port:04X}"
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            if any(ln.split()[1].upper().endswith(want) and ln.split()[3] == "0A"
                   for ln in Path(table).read_text().splitlines()[1:]):
                return True
        except OSError:
            pass
    return False


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def start_server(a, device, log):
    cmd = [a.server, "-select", f"usb={a.serial}", "-device", device, "-if", "SWD",
           "-speed", a.speed, "-LocalhostOnly", "1", "-singlerun", "-timeout", "15000",
           "-powertarget", "0", "-noreset", "-noir", "-port", str(a.port), "-nogui"]
    srv = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    # Never test-connect a -singlerun port: the probe connection would end it.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if srv.poll() is not None:
            return None
        if owns_listener(srv.pid, a.port):
            return srv
        time.sleep(0.1)
    stop(srv)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("core", help="cr8_0 | cr8_1 | J-Link device name")
    ap.add_argument("elf", help="ELF that matches the image running on that core")
    ap.add_argument("-ex", dest="cmds", action="append", default=[],
                    type=lambda v: ("-ex", v), help="gdb command (repeatable, ordered)")
    ap.add_argument("-x", dest="cmds", action="append",
                    type=lambda v: ("-x", v), help="gdb command file (repeatable, ordered)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("GDB_PORT", 50000)))
    ap.add_argument("--speed", default=os.environ.get("JLINK_SPEED", "auto"))
    ap.add_argument("--timeout", type=float, default=60, help="gdb run limit, seconds")
    ap.add_argument("--attempts", type=int, default=3,
                    help="connection attempts; use 1 for fail-stop lab batches")
    ap.add_argument("--log", help="J-Link server log (default: a temp file, kept on failure)")
    ap.add_argument("--allow-mutation", action="store_true",
                    help="skip the read-only check (needs the user's explicit approval)")
    a = ap.parse_args()
    if not 1 <= a.attempts <= 3:
        ap.error("--attempts must be 1..3")

    a.serial = os.environ.get("JLINK_SERIAL")
    if not a.serial:
        ap.error("set JLINK_SERIAL (jlink-debug-preflight.py --print-serial)")
    if not Path(a.elf).is_file():
        ap.error(f"ELF not found: {a.elf}")
    if a.core.lower() == "cm33" or ("_M33" in a.core.upper() and not a.allow_mutation):
        ap.error("CM33 connect resets the RZ/V2H SoC; refused (see --help)")
    device = ALIASES.get(a.core, a.core)
    if not a.cmds:
        ap.error("give at least one -ex or -x")

    if not a.allow_mutation:
        for kind, value in a.cmds:
            lines = [value] if kind == "-ex" else Path(value).read_text().splitlines()
            for n, line in enumerate(lines, 1):
                why = mutation_reason(line)
                if why:
                    where = "-ex" if kind == "-ex" else f"{value}:{n}"
                    print(f"refused ({where}): {line.strip()!r}: {why}. "
                          "Rerun with --allow-mutation only after the user approves.",
                          file=sys.stderr)
                    sys.exit(2)

    a.server = tool("JLINK_GDB", "JLinkGDBServerCLExe", "/opt/SEGGER/JLink/JLinkGDBServerCLExe")
    gdb = tool("GDB", "gdb-multiarch", "gdb-multiarch")
    if port_busy(a.port):
        sys.exit(f"port {a.port} already listening: another GDB server owns it "
                 "(jlink-debug-preflight.py shows the owner)")

    log_path = Path(a.log) if a.log else Path(tempfile.mkstemp(prefix="jlink-oneshot-", suffix=".log")[1])
    gdb_args = [gdb, "-q", "-batch", "-nx", a.elf,
                "-ex", "set pagination off", "-ex", "set confirm off",
                "-ex", f"target remote :{a.port}",
                "-ex", 'printf "ONESHOT_ATTACHED pc=%#x\\n", $pc']
    for kind, value in a.cmds:
        gdb_args += [kind, value]
    gdb_args += ["-ex", "detach"]

    rc, out, errors = 3, "", []
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    with open(log_path, "ab") as log:
        for attempt in range(1, a.attempts + 1):
            srv = start_server(a, device, log)
            if srv is None:
                print(f"-- attempt {attempt}: GDB server did not start listening", file=sys.stderr)
                time.sleep(1)
                continue
            try:
                res = subprocess.run(gdb_args, capture_output=True, text=True, timeout=a.timeout)
                out = res.stdout + res.stderr
                errors = [ln for ln in res.stderr.splitlines()
                          if ln.strip() and not ln.lower().startswith("warning")]
            except subprocess.TimeoutExpired as e:
                # SIGKILL (run's default) sends no kill packet to the target.
                out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                out += f"\n!! gdb exceeded {a.timeout}s"
                rc = 4
            finally:
                stop(srv)
            if "ONESHOT_ATTACHED" not in out:
                print(f"-- attempt {attempt}: gdb did not attach", file=sys.stderr)
                rc = 3
                if RESET_MARKERS.search(log_path.read_text(errors="replace")):
                    break
                time.sleep(1)
                continue
            rc = 0 if "etaching from" in out or "[Inferior 1 (Remote target) detached]" in out else 4
            if rc == 0 and errors:
                rc = 6
            break

    print(out.rstrip())
    server_log = log_path.read_text(errors="replace")
    resets = [ln for ln in server_log.splitlines() if RESET_MARKERS.search(ln)]
    if resets:
        print("\n".join(resets), file=sys.stderr)
        print(f"!! J-Link log shows {a.core} was reset or is held in reset: report it to the "
              f"user; the image there must be reloaded. Server log: {log_path}", file=sys.stderr)
        sys.exit(5)
    if rc == 4:
        print(f"!! gdb did not detach cleanly; server log: {log_path}", file=sys.stderr)
    elif rc == 3:
        print(f"!! could not attach after {a.attempts} attempts; server log: {log_path}", file=sys.stderr)
    elif rc == 6:
        print("!! detached, but gdb reported errors; the read is incomplete:\n  "
              + "\n  ".join(errors), file=sys.stderr)
    if rc in (0, 6) and not a.log:
        log_path.unlink()
    sys.exit(rc)


if __name__ == "__main__":
    main()
