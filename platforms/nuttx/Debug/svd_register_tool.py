#!/usr/bin/env python3
"""CMSIS-SVD register lookup/decoder for any SVD-described MCU (stdlib only).

Turns register names into addresses + read commands (GDB / NSH / JLinkExe),
reverse-maps a raw address (e.g. DFAR) to PERIPH.REG, and decodes values or
whole GDB `x/` / NSH `mw` dumps into named bit fields.

Usage (default SVD: <repo>/rzv2h.svd, override with --svd or $SVD):
  svd_register_tool.py find  'SCI4.*CCR'          # regex over PERIPH.REG
  svd_register_tool.py info  R_SCI4               # list a peripheral's regs
  svd_register_tool.py addr  0x12801c1c           # reverse lookup
  svd_register_tool.py decode R_SCI4.CCR0 0x10    # field breakdown
  svd_register_tool.py cmd gdb R_SCI4.CCR0 R_SCI4.CESR   # emit read cmds
  svd_register_tool.py cmd nsh R_SCI4                    # mw/mh/mb lines
  svd_register_tool.py cmd jlink R_SCI4.CCR0             # mem32 lines
  <gdb or nsh output> | svd_register_tool.py decode-log  # decode a dump
"""
import argparse
import os
import re
import signal
import sys
import xml.etree.ElementTree as ET

# This file lives in <repo>/platforms/nuttx/Debug/.
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 3))
DEFAULT_SVD = os.environ.get("SVD", os.path.join(REPO, "rzv2h.svd"))
# Matches GDB "0x12801c08 <sym>:\t0x00000010" and NSH "  0x12801c08 = 0x00000010".
DUMP_RE = re.compile(r"(0x[0-9a-fA-F]+)(?:\s*<[^>]*>)?\s*[:=]\s*(0x[0-9a-fA-F]+)")


def num(text, default=0):
    if text is None:
        return default
    t = text.strip().lower().replace("#", "0b")
    return int(t, 0)


def txt(el, tag, default=None):
    c = el.find(tag)
    return c.text.strip() if c is not None and c.text else default


def dim_expand(el, name):
    """Yield (expanded_name, extra_offset) for a dim'd register/cluster."""
    dim = txt(el, "dim")
    if not dim:
        yield name, 0
        return
    count, inc = num(dim), num(txt(el, "dimIncrement", "0"))
    idx = txt(el, "dimIndex")
    if idx and "-" in idx and "," not in idx:
        a, b = idx.split("-")
        labels = [str(i) for i in range(int(a), int(b) + 1)] if a.isdigit() else \
            [chr(c) for c in range(ord(a), ord(b) + 1)]
    elif idx:
        labels = [s.strip() for s in idx.split(",")]
    else:
        labels = [str(i) for i in range(count)]
    for i, label in enumerate(labels[:count]):
        yield name.replace("[%s]", label).replace("%s", label), i * inc


def walk_registers(container, base_off, prefix, out, default_size):
    for reg in container.findall("register"):
        for name, extra in dim_expand(reg, txt(reg, "name")):
            fields = []
            for f in reg.findall("fields/field"):
                if txt(f, "bitRange"):
                    hi, lo = [int(x) for x in txt(f, "bitRange").strip("[]").split(":")]
                    off, width = lo, hi - lo + 1
                elif txt(f, "lsb") is not None:
                    off = num(txt(f, "lsb"))
                    width = num(txt(f, "msb")) - off + 1
                else:
                    off, width = num(txt(f, "bitOffset")), num(txt(f, "bitWidth", "1"))
                enums = {num(txt(e, "value")): txt(e, "name")
                         for e in f.findall("enumeratedValues/enumeratedValue")
                         if txt(e, "value") is not None}
                fields.append((txt(f, "name"), off, width, txt(f, "access", ""), enums))
            out.append({
                "name": prefix + name,
                "offset": base_off + num(txt(reg, "addressOffset")) + extra,
                "size": num(txt(reg, "size"), default_size),
                "access": txt(reg, "access", ""),
                "desc": " ".join((txt(reg, "description", "") or "").split()),
                "fields": sorted(fields, key=lambda x: -x[1]),
            })
    for cl in container.findall("cluster"):
        for cname, extra in dim_expand(cl, txt(cl, "name")):
            walk_registers(cl, base_off + num(txt(cl, "addressOffset")) + extra,
                           prefix + cname + ".", out, default_size)


def load_svd(path):
    root = ET.parse(path).getroot()
    dsize = num(txt(root, "size"), 32)
    raw = {txt(p, "name"): p for p in root.iter("peripheral")}
    periphs = {}
    for name, p in raw.items():
        src = raw.get(p.get("derivedFrom"), p) if p.get("derivedFrom") else p
        regs = []
        if src.find("registers") is not None:
            walk_registers(src.find("registers"), 0, "", regs, dsize)
        base = num(txt(p, "baseAddress"))
        for r in regs:
            r["addr"] = base + r["offset"]
            r["periph"] = name
        periphs[name] = {"base": base, "regs": regs,
                         "desc": txt(p, "description", "") or txt(src, "description", "")}
    return periphs


def all_regs(periphs):
    for p in periphs.values():
        yield from p["regs"]


def resolve(periphs, spec):
    """'R_SCI4' -> all regs; 'R_SCI4.CCR0' -> one; 'SCI4.CCR0' tolerated."""
    pname, _, rname = spec.partition(".")
    if pname not in periphs and "R_" + pname in periphs:
        pname = "R_" + pname
    if pname not in periphs:
        sys.exit(f"unknown peripheral: {pname} (try: find '{pname}')")
    regs = periphs[pname]["regs"]
    if rname:
        regs = [r for r in regs if r["name"].upper() == rname.upper()]
        if not regs:
            sys.exit(f"unknown register: {spec} (try: info {pname})")
    return regs


def fmt_reg(r):
    return (f"0x{r['addr']:08X}  {r['periph']}.{r['name']:<16} {r['size']:>2}b "
            f"{r['access']:<10} {r['desc'][:70]}")


def decode(r, value):
    print(f"{r['periph']}.{r['name']} @0x{r['addr']:08X} = 0x{value:0{r['size'] // 4}X}")
    for name, off, width, _acc, enums in r["fields"]:
        v = (value >> off) & ((1 << width) - 1)
        bits = f"[{off + width - 1}:{off}]" if width > 1 else f"[{off}]"
        enum = f"  ({enums[v]})" if v in enums else ""
        print(f"  {bits:>8} {name:<14} = {v:#x}{enum}")


def lookup_addr(periphs, addr):
    hits = [r for r in all_regs(periphs) if r["addr"] <= addr < r["addr"] + r["size"] // 8]
    return sorted(hits, key=lambda r: (r["addr"] != addr, r["periph"]))


def emit_cmd(kind, r):
    a, s = r["addr"], r["size"]
    label = f"{r['periph']}.{r['name']}"
    if kind == "gdb":
        unit = {8: "b", 16: "h", 32: "w"}.get(s, "w")
        return f'printf "{label}\\n"\nx/1{unit}x 0x{a:08x}'
    if kind == "nsh":
        return f"{ {8: 'mb', 16: 'mh'}.get(s, 'mw')} 0x{a:08x}"
    return f"{ {8: 'mem8', 16: 'mem16'}.get(s, 'mem32')} 0x{a:08X} 1"


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet `| head`
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--svd", default=DEFAULT_SVD)
    sub = ap.add_subparsers(dest="op", required=True)
    sub.add_parser("find").add_argument("pattern")
    sub.add_parser("info").add_argument("spec")
    sub.add_parser("addr").add_argument("address")
    d = sub.add_parser("decode")
    d.add_argument("spec")
    d.add_argument("value")
    c = sub.add_parser("cmd")
    c.add_argument("kind", choices=["gdb", "nsh", "jlink"])
    c.add_argument("specs", nargs="+")
    sub.add_parser("decode-log")
    a = ap.parse_args()
    periphs = load_svd(a.svd)

    if a.op == "find":
        rx = re.compile(a.pattern, re.I)
        for r in all_regs(periphs):
            if rx.search(f"{r['periph']}.{r['name']}"):
                print(fmt_reg(r))
    elif a.op == "info":
        for r in resolve(periphs, a.spec):
            print(fmt_reg(r))
    elif a.op == "addr":
        hits = lookup_addr(periphs, num(a.address))
        print("\n".join(fmt_reg(r) for r in hits) or "no SVD register at that address")
    elif a.op == "decode":
        for r in resolve(periphs, a.spec):
            decode(r, num(a.value))
    elif a.op == "cmd":
        for spec in a.specs:
            for r in resolve(periphs, spec):
                print(emit_cmd(a.kind, r))
    elif a.op == "decode-log":
        for line in sys.stdin:
            for addr_s, val_s in DUMP_RE.findall(line):
                hits = lookup_addr(periphs, num(addr_s))
                if hits and hits[0]["addr"] == num(addr_s):
                    decode(hits[0], num(val_s))
                else:
                    print(f"0x{num(addr_s):08X} = {val_s}  (no exact SVD register)")


if __name__ == "__main__":
    main()
