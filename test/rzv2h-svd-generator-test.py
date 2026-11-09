#!/usr/bin/env python3
"""Check generate-rzv2h-svd.py and the committed rzv2h.svd against the FSP headers.

* rzv2h.svd is what the generator writes from the FSP 4.2.0 headers (--check).
* Every register of every non-derived peripheral, at every dim index, has the
  offset and size that the C compiler gives the FSP R_*_Type member.  Checked
  with _Static_assert under the host C compiler and, when installed,
  arm-none-eabi-gcc (the CR8 target ABI).
* Every instance has the address of its FSP R_* instance pointer, and every bit
  field has the mask the compiler gives the FSP *_b bit-field member (host run:
  set the field to all ones, read the register view back).
* The committed SVD differs from the raw header layout only at the generator's
  ERRATA entries.
* Every <interrupt> value equals the FSP CR8 IRQn_Type constant of that name
  (_Static_assert), every non-negative IRQn constant is in the SVD once, and the
  <cpu> flags equal the CR8 core macros of R9A09G057H.h.

Skipped when the local-only refs/ FSP tree is missing.
"""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "generate-rzv2h-svd.py"
SVD = ROOT / "rzv2h.svd"
sys.path.insert(0, str(ROOT / "platforms/nuttx/Debug"))
import svd_register_tool  # noqa: E402


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_rzv2h_svd", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_generator()
INCLUDE = gen.DEFAULT_INCLUDE

QUALIFIER_STUBS = """
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
/* CMSIS qualifiers without const so the bit-field views can be written on the host. */
#define __IM  volatile
#define __OM  volatile
#define __IOM volatile
#define __I   volatile
#define __O   volatile
#define __IO  volatile
#include "R9A09G057H/cr/iodefine.h"
"""


def svd_layout(text):
    """Flatten an SVD text with svd_register_tool, the consumer the port's tools use."""
    with tempfile.NamedTemporaryFile("w", suffix=".svd", delete=False) as handle:
        handle.write(text)
    try:
        return svd_register_tool.load_svd(handle.name)
    finally:
        Path(handle.name).unlink()


def c_member_paths(container, prefix="", base=0):
    """Yield (C member path, offset, size in bytes) for every register at every dim index."""
    def expand(el):
        name = el.findtext("name")
        if not el.findtext("dim"):
            yield name, 0
            return
        for i in range(int(el.findtext("dim"), 0)):
            yield name.replace("[%s]", "[%d]" % i), i * int(el.findtext("dimIncrement"), 0)
    for reg in container.findall("register"):
        for name, extra in expand(reg):
            yield prefix + name, base + int(reg.findtext("addressOffset"), 0) + extra, int(reg.findtext("size")) // 8
    for cluster in container.findall("cluster"):
        for name, extra in expand(cluster):
            yield from c_member_paths(cluster, prefix + name + ".",
                                      base + int(cluster.findtext("addressOffset"), 0) + extra)


def first_instances(svd_text):
    root = ET.fromstring(svd_text)
    return {p.findtext("name") for p in root.iter("peripheral") if not p.get("derivedFrom")}


@unittest.skipUnless((INCLUDE / "R9A09G057H.h").is_file(), "local FSP 4.2.0 tree (refs/) unavailable")
class SvdGeneratorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw_text, _, cls.raw_stats, cls.fields = gen.generate(INCLUDE, apply_errata=False)
        cls.raw = svd_layout(cls.raw_text)
        cls.committed = svd_register_tool.load_svd(SVD)
        cls.owners = first_instances(cls.raw_text)

    def test_committed_svd_is_fresh(self):
        result = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_device_header_and_derived_peripherals(self):
        root = ET.parse(SVD).getroot()
        self.assertEqual(root.findtext("name"), "R9A09G057H")
        seen = set()
        for p in root.iter("peripheral"):
            parent = p.get("derivedFrom")
            if parent:
                self.assertIn(parent, seen, "%s derives from a later or unknown peripheral" % p.findtext("name"))
            seen.add(p.findtext("name"))
        self.assertIn("R_GBETH0", seen)
        self.assertEqual(len(seen), self.raw_stats["peripherals"] + self.raw_stats["derived"])

    def test_committed_svd_deviates_from_header_only_at_errata(self):
        errata = {(reg, fixed) for regs in gen.ERRATA.values() for reg, (_, fixed) in regs.items()}
        deviations = set()
        for name, peripheral in self.committed.items():
            raw = {r["name"]: r for r in self.raw[name]["regs"]}
            self.assertEqual(peripheral["base"], self.raw[name]["base"], name)
            for reg in peripheral["regs"]:
                other = raw[reg["name"]]
                self.assertEqual((reg["size"], reg["access"], reg["fields"]),
                                 (other["size"], other["access"], other["fields"]), name + "." + reg["name"])
                if reg["offset"] != other["offset"]:
                    self.assertIn((reg["name"], reg["offset"]), errata, name + "." + reg["name"])
                    deviations.add((reg["name"], reg["offset"]))
        self.assertEqual(deviations, errata)

    def c_layout_source(self):
        lines = [QUALIFIER_STUBS]
        for p in ET.fromstring(self.raw_text).iter("peripheral"):
            if p.get("derivedFrom"):
                continue
            name = p.findtext("name")
            for path, offset, size in c_member_paths(p.find("registers")):
                lines.append("_Static_assert(offsetof(__typeof__(*%s), %s) == 0x%X, \"%s.%s offset\");"
                             % (name, path, offset, name, path))
                lines.append("_Static_assert(sizeof(((__typeof__(*%s) *)0)->%s) == %d, \"%s.%s size\");"
                             % (name, path, size, name, path))
        return "\n".join(lines) + "\n"

    def compile(self, compiler, source, extra, workdir):
        src = Path(workdir) / "svd_layout.c"
        src.write_text(source)
        cmd = [compiler, "-std=gnu11", "-w", "-I", str(INCLUDE), str(src)] + extra
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
        errors = [line for line in result.stderr.splitlines() if "error" in line][:20]
        self.assertEqual(result.returncode, 0, "%s failed:\n%s" % (compiler, "\n".join(errors)))

    def test_offsets_and_sizes_match_c_layout(self):
        compilers = [c for c in (shutil.which("cc") or shutil.which("gcc"),
                                 shutil.which("arm-none-eabi-gcc")) if c]
        if not compilers:
            self.skipTest("no C compiler")
        source = self.c_layout_source()
        for compiler in compilers:
            with tempfile.TemporaryDirectory() as workdir:
                self.compile(compiler, source, ["-c", "-o", "svd_layout.o"], workdir)

    def test_bases_and_field_masks_match_c(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler:
            self.skipTest("no host C compiler")
        lines = [QUALIFIER_STUBS]
        lines += ["static __typeof__(*%s) o_%s;" % (p, p) for p in sorted({f["peripheral"] for f in self.fields})]
        lines += ["int main(void) {", "  unsigned failures = 0;"]
        # Instance pointers: some use a differently named *_BASE macro (R_POEGA -> R_POEG0A_BASE).
        lines += ["  if ((uintptr_t)%s != 0x%XUL) { printf(\"%s base\\n\"); failures++; }"
                  % (name, peripheral["base"], name) for name, peripheral in sorted(self.raw.items())]
        for f in self.fields:
            peripheral = f["peripheral"]
            prefix = "".join(p + "." for p in f["path"])
            mask = ((1 << f["bits"]) - 1) << f["bitpos"]
            label = "%s.%s%s.%s" % (peripheral, prefix, f["register"], f["field"])
            lines.append(
                "  memset((void *)&o_%(p)s, 0, sizeof o_%(p)s);"
                " o_%(p)s.%(prefix)s%(view)s.%(field)s = (1ULL << %(bits)d) - 1;"
                " if ((uint64_t)o_%(p)s.%(prefix)s%(reg)s != 0x%(mask)XULL) {"
                " printf(\"%(label)s: 0x%%llx\\n\", (unsigned long long)o_%(p)s.%(prefix)s%(reg)s); failures++; }"
                % {"p": peripheral, "prefix": prefix, "view": f["c_view"], "field": f["field"],
                   "bits": f["bits"], "reg": f["c_register"], "mask": mask, "label": label})
        lines += ["  printf(\"%u failures\\n\", failures);", "  return failures != 0;", "}"]
        self.assertGreater(len(self.fields), 10000)
        with tempfile.TemporaryDirectory() as workdir:
            self.compile(compiler, "\n".join(lines) + "\n", ["-O0", "-o", "svd_fields"], workdir)
            result = subprocess.run([str(Path(workdir) / "svd_fields")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])

    def test_interrupts_match_irqn_enum(self):
        irq_header = INCLUDE.parents[3] / gen.IRQ_HEADER
        interrupts = [(i.findtext("name"), int(i.findtext("value"))) for i in ET.parse(SVD).getroot().iter("interrupt")]
        names = [name for name, _ in interrupts]
        self.assertEqual(len(names), len(set(names)), "duplicate interrupt names")
        # Independent of the generator's parser: count the non-negative "<name>_IRQn = <n>" constants.
        enum = irq_header.read_text().split("typedef enum IRQn", 1)[1].split("} IRQn_Type", 1)[0]
        self.assertEqual(sorted(names), sorted(re.findall(r"\b(\w+)_IRQn\s*=\s*\d+", enum)))
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler:
            self.skipTest("no host C compiler")
        source = "#include \"bsp_irq_id.h\"\n" + "".join(
            "_Static_assert(%s_IRQn == %d, \"%s\");\n" % (name, value, name) for name, value in interrupts)
        with tempfile.TemporaryDirectory() as workdir:
            src = Path(workdir) / "svd_irq.c"
            src.write_text(source)
            result = subprocess.run([compiler, "-std=gnu11", "-c", "-o", "svd_irq.o", "-I", str(irq_header.parent), str(src)],
                                    capture_output=True, text=True, cwd=workdir)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_cpu_matches_cr8_core_macros(self):
        root = ET.parse(SVD).getroot()
        cpu = {el.tag: el.text for el in root.find("cpu")}
        block = (INCLUDE / "R9A09G057H.h").read_text().split("defined(BSP_SUPPORT_CORE_CR8)", 1)[1].split("#endif", 1)[0]
        macro = {k: int(v.rstrip("uUlL"), 0) for k, v in re.findall(r"#\s*define\s+(__\w+)\s+(\w+)", block)}
        flag = lambda name: "true" if macro[name] else "false"  # noqa: E731
        self.assertEqual(cpu, {
            "name": "other", "revision": gen.CPU_REVISION, "endian": "little",
            "mpuPresent": flag("__MPU_PRESENT"), "fpuPresent": flag("__FPU_PRESENT"), "fpuDP": flag("__FPU_DP"),
            "nvicPrioBits": str(macro["__NVIC_PRIO_BITS"]), "vendorSystickConfig": flag("__Vendor_SysTickConfig"),
            "deviceNumInterrupts": str(max(int(i.findtext("value")) for i in root.iter("interrupt")) + 1),
        })


if __name__ == "__main__":
    unittest.main()
