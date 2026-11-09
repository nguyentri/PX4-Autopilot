#!/usr/bin/env python3
"""Check the NuttX RZ/V2H hardware headers against rzv2h.svd.

Every integer macro of arch/arm/src/rzv/hardware/rzv_*.h is evaluated by the host
C compiler (the header is included as the drivers include it, so macro arithmetic
and casts are the real ones).  Each value is then compared with the SVD:

* *_BASE equal to a CR8 peripheral base of the SVD.  CM33 bases (0x4/0x5xxxxxxx)
  are compared with the FSP cm/ R_*_BASE macros when the local refs/ tree exists.
* *_OFFSET equal to the offset of the register of that name (stride macros are
  evaluated at index 0 and matched with the index-0 register).
* *_SHIFT, *_MASK and single-bit macros equal to the position, mask or bit of the
  register field of that name.

Names that do not resolve to an SVD register or field are not checked; a coverage
floor guards against the checker silently matching nothing.  Deviations that are
understood are listed in KNOWN with the reason; a KNOWN entry that no longer
deviates fails the test so the list stays current.
"""

import collections
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
HARDWARE = NUTTX / "arch/arm/src/rzv/hardware"
SVD = ROOT / "rzv2h.svd"
FSP_CM = ROOT / "refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/cm"
sys.path.insert(0, str(ROOT / "platforms/nuttx/Debug"))
import svd_register_tool  # noqa: E402

DEFINES = ["-DCONFIG_ARCH_CHIP_R9A09G057", "-DCONFIG_RZV2H_GROUP"]

# Header stem -> SVD groupName (the FSP iodefine stem).  Headers without an SVD
# peripheral (SDHI, ELC, pin map) are still preprocessed and evaluated.
GROUP = {
    "adc": "ADC_E", "canfd": "CANFD", "cmtw": "CMTW", "cpg": "CPG", "crc": "CRC", "dmac": "DMAC_B",
    "ether": "GBETH", "global_timer": "GLOBAL_TIMER", "gpio": "GPIO", "gpt": "GPT", "gtm": "GTM",
    "i2c": "RIIC", "i3c": "I3C_B", "icu": "INTC", "intc_gic": "INTC_GIC", "intc": "INTC", "mhu": "MHU",
    "pdm": "PDM", "poeg": "POEG", "private_timer": "PRIVATE_TIMER", "rtc": "RTC", "sci_spi": "SCI_B",
    "sci": "SCI_B", "scifa": "SCIFA", "scu": "SCU", "spi": "SPI_B", "spibsc": "SPIBSC", "ssi": "SSI",
    "sysc": "SYSC", "tsu": "TSU_B", "tzc": "TZC", "wdt": "WDT", "xspi": "XSPI",
}

KNOWN = {
    # The CFDC2 member offsets are relative to RZV_CANFD_CFDC2_CH_BASE(ch) (0x1400 + 0x20 * ch).
    "RZV_CANFD_CFDC2_DCFG_OFFSET": "relative to RZV_CANFD_CFDC2_CH_BASE(ch)",
    "RZV_CANFD_CFDC2_FDCFG_OFFSET": "relative to RZV_CANFD_CFDC2_CH_BASE(ch)",
    "RZV_CANFD_CFDC2_FDCTR_OFFSET": "relative to RZV_CANFD_CFDC2_CH_BASE(ch)",
    "RZV_CANFD_CFDC2_FDSTS_OFFSET": "relative to RZV_CANFD_CFDC2_CH_BASE(ch)",
    "RZV_CANFD_CFDC2_FDCRC_OFFSET": "relative to RZV_CANFD_CFDC2_CH_BASE(ch)",
    "RZV_CANFD_CH1_BASE": "channel 1 of the 0x10 CFDCnNCFG channel stride, inside R_CANFD",
}

MACRO = re.compile(r"^#define (\w+)(\(([\w, ]*)\))? (.*)$")


def compile_flags(stub):
    return DEFINES + ["-I", str(stub), "-I", str(NUTTX / "arch/arm/src/rzv"), "-I", str(NUTTX / "include")]


def header_macros(compiler, header, stub):
    """Return {name: params or None} for the macros the header itself defines."""
    result = subprocess.run([compiler, "-E", "-dM"] + compile_flags(stub) + [str(header)],
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError("%s does not preprocess:\n%s" % (header.name, result.stderr[-2000:]))
    own = set(re.findall(r"^\s*#\s*define\s+(\w+)", header.read_text(), re.M))
    macros = {}
    for line in result.stdout.splitlines():
        m = MACRO.match(line)
        if m and m.group(1) in own and m.group(4).strip():
            macros[m.group(1)] = [a.strip() for a in m.group(3).split(",")] if m.group(2) else None
    return macros


def evaluate(compiler, header, stub, macros):
    """Return {expression: value} for the macros that are integer constant expressions.

    Object-like macros are evaluated as is; function-like *_OFFSET macros at index 0.
    Expressions the compiler rejects (pointers, token pasting, non-constants) are dropped.
    """
    exprs = []
    for name, params in macros.items():
        if params is None:
            exprs.append(name)
        elif name.endswith("_OFFSET") and params and params != ["..."]:
            exprs.append("%s(%s)" % (name, ",".join("0" * len(params))))
    head = ["#include <stdint.h>", "#include <stdbool.h>", "#include <stdio.h>", '#include "%s"' % header,
            "int main(void) {"]
    with tempfile.TemporaryDirectory() as workdir:
        for _ in range(40):
            body = ['printf("%%s %%lld\\n", "%s", (long long)(%s));' % (e, e) for e in exprs]
            Path(workdir, "m.c").write_text("\n".join(head + body + ["return 0; }"]) + "\n")
            result = subprocess.run([compiler, "-w", "-fmax-errors=0"] + compile_flags(stub) + ["-o", "m", "m.c"],
                                    capture_output=True, text=True, cwd=workdir)
            if result.returncode == 0:
                break
            bad = {int(n) - len(head) - 1 for n in re.findall(r"^m\.c:(\d+):\d+:", result.stderr, re.M)}
            if not bad:
                raise AssertionError("%s: %s" % (header.name, result.stderr[-2000:]))
            exprs = [e for i, e in enumerate(exprs) if i not in bad]
        else:
            raise AssertionError("%s: evaluation did not converge" % header.name)
        out = subprocess.run([str(Path(workdir, "m"))], capture_output=True, text=True, check=True).stdout
    return {k: int(v) & 0xFFFFFFFF for k, v in (line.rsplit(" ", 1) for line in out.splitlines())}


def svd_groups(svd):
    """Return {groupName: [peripheral]} with derived peripherals under their parent's group."""
    import xml.etree.ElementTree as ET
    root = ET.parse(SVD).getroot()
    elements = {p.findtext("name"): p for p in root.iter("peripheral")}
    groups = collections.defaultdict(list)
    for name, p in elements.items():
        source = elements[p.get("derivedFrom")] if p.get("derivedFrom") else p
        groups[source.findtext("groupName")].append(name)
    return groups


def norm(name):
    return name.replace(".", "_").replace("[", "").replace("]", "").upper()


def register_index(svd, peripherals):
    """Map normalized register names (full path and cluster leaf) to their SVD registers."""
    index = collections.defaultdict(list)
    for p in peripherals:
        for reg in svd[p]["regs"]:
            index[norm(reg["name"])].append(reg)
            leaf = norm(reg["name"].split(".")[-1])
            if leaf != norm(reg["name"]):
                index[leaf].append(reg)
    return index


def fsp_cm33_bases():
    bases = set()
    for header in FSP_CM.rglob("*.h") if FSP_CM.is_dir() else []:
        bases.update(int(v, 16) for v in re.findall(r"#define R_\w+_BASE\s+0x([0-9A-Fa-f]+)", header.read_text()))
    return bases


def compare(name, value, index, cr8_bases, cm33_bases, stats):
    """Return a mismatch description, or None when the macro matches or is not checked."""
    base = name.split("(")[0]
    tokens = base.split("_")
    if tokens[0] == "RZV":
        tokens = tokens[1:]
    if base.endswith("_BASE") and "(" not in name:
        if value in cr8_bases:
            stats["base"] += 1
        elif value >> 28 in (4, 5) and cm33_bases:
            if value not in cm33_bases:
                return "CM33 base 0x%X is not an FSP cm R_*_BASE" % value
            stats["base"] += 1
        elif value >> 28 == 1 and index:  # headers without an SVD peripheral (SDHI) are not checked
            return "base 0x%X is not an SVD peripheral base" % value
        return None
    if base.endswith("_OFFSET"):
        tokens = tokens[:-1]
        candidates = [tokens[k:] for k in range(len(tokens))]
        if "(" in name and tokens:
            candidates += [t[:-1] + [t[-1] + "0"] for t in candidates if t]
        for key in ("_".join(c) for c in candidates):
            if key in index:
                offsets = sorted({r["offset"] for r in index[key]})
                if value in offsets:
                    stats["offset"] += 1
                    return None
                return "offset 0x%X, SVD %s at %s" % (value, key, ", ".join("0x%X" % o for o in offsets[:4]))
        return None
    if "(" in name:
        return None
    kind = "shift" if base.endswith("_SHIFT") else "mask" if base.endswith("_MASK") else "bit"
    if kind == "bit" and (value == 0 or value & (value - 1)):
        return None
    body = tokens[:-1] if kind != "bit" else tokens
    for split in range(1, len(body)):
        field = "_".join(body[split:])
        for start in range(split):
            key = "_".join(body[start:split])
            fields = [f for r in index.get(key, []) for f in r["fields"] if norm(f[0]) == field]
            if not fields:
                continue
            for _, pos, width, _, _ in fields:
                want = {"shift": pos, "mask": ((1 << width) - 1) << pos}.get(kind)
                if want == value or (kind == "bit" and pos <= value.bit_length() - 1 < pos + width):
                    stats["field"] += 1
                    return None
            return "%s 0x%X, SVD %s.%s at bit %d width %d" % (kind, value, key, field, fields[0][1], fields[0][2])
    return None


@unittest.skipUnless(shutil.which("cc") or shutil.which("gcc"), "no host C compiler")
class NuttxHardwareSvdParityTest(unittest.TestCase):

    def test_headers_match_svd(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        svd = svd_register_tool.load_svd(SVD)
        groups = svd_groups(svd)
        cr8_bases = {p["base"] for p in svd.values()}
        cm33_bases = fsp_cm33_bases()
        stats = collections.Counter()
        mismatches, known_seen = [], set()
        headers = sorted(HARDWARE.glob("rzv_*.h"))
        self.assertGreater(len(headers), 30)
        with tempfile.TemporaryDirectory() as stub:
            Path(stub, "nuttx").mkdir()
            Path(stub, "nuttx", "config.h").write_text("/* host stub for the parity check */\n")
            for header in headers:
                stem = header.stem[len("rzv_"):]
                index = register_index(svd, groups.get(GROUP.get(stem), []))
                values = evaluate(compiler, header, stub, header_macros(compiler, header, stub))
                stats["evaluated"] += len(values)
                for name, value in sorted(values.items()):
                    problem = compare(name, value, index, cr8_bases, cm33_bases, stats)
                    macro = name.split("(")[0]
                    if problem and macro in KNOWN:
                        known_seen.add(macro)
                    elif problem:
                        mismatches.append("%s: %s: %s" % (header.name, name, problem))
        self.assertEqual(mismatches, [], "\n".join(mismatches))
        self.assertEqual(sorted(set(KNOWN) - known_seen), [], "KNOWN entries that no longer deviate")
        # Coverage floor: a silent resolver regression would otherwise pass with nothing checked.
        self.assertGreater(stats["offset"], 1500, stats)
        self.assertGreater(stats["field"], 4000, stats)
        self.assertGreater(stats["base"], 200, stats)
        print("checked %(base)d bases, %(offset)d offsets, %(field)d fields of %(evaluated)d macros" % stats)


if __name__ == "__main__":
    unittest.main()
