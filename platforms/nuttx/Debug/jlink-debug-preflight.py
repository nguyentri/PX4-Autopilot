#!/usr/bin/env python3
"""Host-only preflight for J-Link / GDB / RTT debugging. Never opens the probe.

Answers, in one run, what an agent otherwise discovers by trial and error:
  * which debug tools are installed and where;
  * which SEGGER J-Link probes and FTDI serial adapters are on USB, with the
    serial exactly as JLinkExe -USB / JLinkGDBServer -select usb= expect it;
  * which J-Link / GDB processes already own the probe, and which debug TCP
    ports (RTT 19021, GDB 50000/2331/2341) are listening;
  * every firmware ELF in the tree with its entry point, _SEGGER_RTT address
    and the core it is linked for (RZ/V2H CR8-0, CR8-1, CM33).

  jlink-debug-preflight.py                     # full report
  jlink-debug-preflight.py build/x/x.elf       # report plus these ELFs
  export JLINK_SERIAL=$(jlink-debug-preflight.py --print-serial)

--print-serial prints only the probe serial and exits 1 unless exactly one
J-Link is attached. The serial identifies hardware: keep it out of reports
(write <probe-sn>).
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USB = Path("/sys/bus/usb/devices")
SEGGER_DIR = Path("/opt/SEGGER/JLink")
TOOLS = {
    "JLinkExe": [SEGGER_DIR / "JLinkExe"],
    "JLinkGDBServerCLExe": [SEGGER_DIR / "JLinkGDBServerCLExe"],
    "gdb-multiarch": [],
    "arm-none-eabi-nm": [Path("/opt/arm-gnu-toolchain-13.2.Rel1/bin/arm-none-eabi-nm")],
}
PROBE_PROCS = {"JLinkExe", "JLinkGDBServer", "JLinkGDBServerCLExe", "JLinkRTTClient",
               "JLinkRTTLogger", "gdb-multiarch", "arm-none-eabi-gdb"}
PORTS = {19021: "RTT telnet (JLinkExe bridge or GDB server)", 50000: "GDB (rzv2h loaders, one-shot)",
         2331: "GDB (J-Link default, upload_jlink_gdb.sh)", 2341: "GDB (ad-hoc)"}
# Link-time entry ranges of the RZ/V2H images in this tree.
CORES = ((0x40800000, 0x41000000, "cr8_0"), (0x41800000, 0x42000000, "cr8_1"),
         (0x08000000, 0x08100000, "cm33"))


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    return next((str(p) for p in TOOLS.get(name, []) if p.is_file()), None)


def usb_devices(vendor):
    for dev in sorted(USB.glob("*")):
        try:
            if (dev / "idVendor").read_text().strip() != vendor:
                continue
        except OSError:
            continue
        read = lambda f: (dev / f).read_text().strip() if (dev / f).exists() else ""
        ttys = sorted({t.name for t in dev.glob("*/tty*") if t.name.startswith("tty")})
        yield dev.name, read("idProduct"), read("product"), read("serial"), ttys


def jlink_serials():
    # sysfs pads the serial to 12 digits; the J-Link tools want it unpadded.
    return [(name, prod, serial.lstrip("0") or serial)
            for name, _, prod, serial, _ in usb_devices("1366")]


def probe_command(cmdline):
    # Linux comm truncates both arm-none-eabi-gcc and arm-none-eabi-gdb to
    # arm-none-eabi-g. Inspect the actual executable token, never that prefix.
    executable = cmdline.split(b"\0", 1)[0].decode(errors="replace")
    return Path(executable).name in PROBE_PROCS


def owners():
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            comm = (proc / "comm").read_text().strip()
            cmdline = (proc / "cmdline").read_bytes()
            if probe_command(cmdline):
                cmd = cmdline.replace(b"\0", b" ").decode(errors="replace")
                yield int(proc.name), comm, cmd.strip()
        except OSError:
            continue


def listening(port):
    want = f":{port:04X}"
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in Path(table).read_text().splitlines()[1:]:
                f = line.split()
                if f[1].upper().endswith(want) and f[3] == "0A":
                    return True
        except OSError:
            continue
    return False


def elf_entry(path):
    with open(path, "rb") as fh:
        hdr = fh.read(0x1C)
    if len(hdr) < 0x1C or hdr[:4] != b"\x7fELF" or hdr[4] != 1:
        return None
    return struct.unpack_from("<I" if hdr[5] == 1 else ">I", hdr, 0x18)[0]


def rtt_addr(path, nm):
    if not nm:
        return "nm?"
    out = subprocess.run([nm, path], capture_output=True, text=True).stdout
    return next(("0x" + ln.split()[0] for ln in out.splitlines()
                 if ln.endswith(" _SEGGER_RTT")), "none")


def core_of(entry):
    return next((c for lo, hi, c in CORES if lo <= (entry & ~1) < hi), "?")


def elf_candidates(extra):
    paths = [Path(p) for p in extra]
    paths += sorted(ROOT.glob("build/*/*.elf"))
    nx = ROOT / "platforms/nuttx/NuttX/nuttx"
    paths += [p for p in [nx / "nuttx", *sorted(nx.glob("*.elf"))] if p.is_file()]
    seen, out = set(), []
    for p in paths:
        if p.resolve() not in seen:
            seen.add(p.resolve())
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print-serial", action="store_true",
                    help="print only the single attached J-Link serial")
    ap.add_argument("elfs", nargs="*", help="extra ELF files to describe")
    a = ap.parse_args()

    probes = jlink_serials()
    if a.print_serial:
        if len(probes) != 1:
            sys.exit(f"expected exactly one J-Link on USB, found {len(probes)}")
        print(probes[0][2])
        return

    print("== tools")
    for name in TOOLS:
        print(f"  {name:22} {tool(name) or 'MISSING'}")

    print("== USB")
    if not probes:
        print("  no SEGGER J-Link (vendor 1366). On WSL attach it from Windows: "
              "usbipd attach --wsl --busid <id>")
    for name, prod, serial in probes:
        print(f"  J-Link    usb {name:6} {prod:12} JLINK_SERIAL={serial}")
    for name, pid, prod, _, ttys in usb_devices("0403"):
        print(f"  FTDI {pid} usb {name:6} {prod:18} tty={','.join('/dev/' + t for t in ttys) or '-'}"
              "  (RZ/V2H SCI4 NSH console in nsh/nsh-scif images)")

    print("== probe owners (stop these before taking the probe; kill by PID)")
    found = list(owners())
    for pid, comm, cmd in found:
        print(f"  pid {pid:7} {comm:18} {cmd[:110]}")
    if not found:
        print("  none")
    state = Path(os.environ.get("STATE_DIR", f"{os.environ.get('TMPDIR', '/tmp')}/nuttx-rtt-bridge"))
    if (state / "bridge.pid").exists():
        print(f"  RTT bridge pid file present: run nuttx-rtt-bridge.sh status")

    print("== ports")
    for port, what in PORTS.items():
        print(f"  {port:5} {'LISTENING' if listening(port) else 'free':9} {what}")

    print("== ELFs (entry / _SEGGER_RTT / core / age)")
    nm = tool("arm-none-eabi-nm")
    now = time.time()
    for path in elf_candidates(a.elfs):
        try:
            entry = elf_entry(path)
        except OSError as e:
            print(f"  {path}: {e}")
            continue
        if entry is None:
            print(f"  {path}: not a 32-bit ELF")
            continue
        age_h = (now - path.stat().st_mtime) / 3600
        rel = path.resolve().relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path
        print(f"  {entry:#010x} rtt={rtt_addr(path, nm):11} {core_of(entry):5} "
              f"{age_h:7.1f}h  {rel}")
    print("Core is guessed from the link address; the loaded image is what the "
          "board runs, not necessarily the newest ELF.")


if __name__ == "__main__":
    main()
