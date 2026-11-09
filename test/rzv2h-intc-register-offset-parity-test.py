#!/usr/bin/env python3
"""Check RZ/V2H INTC register offsets and selector values against rzv2h.svd.

Every RZV_INTC_*_OFFSET macro in hardware/rzv_intc.h must match the
R_INTC addressOffset of the register with the same name in the CMSIS-SVD
file.  Parameterized macros RZV_INTC_<NAME>_OFFSET(m) are checked for each
<NAME><m> register that the SVD lists.  The selector-driver checks keep the
"no source connected" encoding (0x3FF) used for slot reset and detach.
"""

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
HEADER = ARCH / "hardware/rzv_intc.h"
SVD = ROOT / "rzv2h.svd"

SCALAR_RE = re.compile(
    r"^#define\s+RZV_INTC_(\w+)_OFFSET\s+(0x[0-9A-Fa-f]+)\b", re.M)
PARAM_RE = re.compile(
    r"^#define\s+RZV_INTC_(\w+)_OFFSET\(m\)\s+"
    r"\(\s*(0x[0-9A-Fa-f]+)\s*\+\s*\(\(m\)\s*\*\s*(0x[0-9A-Fa-f]+)\)\s*\)",
    re.M)


def svd_intc_offsets():
    tree = ET.parse(SVD)
    for peripheral in tree.getroot().iter("peripheral"):
        if peripheral.findtext("name") != "R_INTC":
            continue
        offsets = {}
        for register in peripheral.iter("register"):
            offsets[register.findtext("name")] = int(
                register.findtext("addressOffset"), 0)
        return offsets
    raise AssertionError("R_INTC peripheral missing from rzv2h.svd")


def header_define(text, name):
    match = re.search(r"^#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)\b" % name,
                      text, re.M)
    if match is None:
        raise AssertionError(name + " is not defined")
    return int(match.group(1), 0)


class IntcRegisterOffsetParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header = HEADER.read_text()
        cls.svd = svd_intc_offsets()

    def test_scalar_offsets_match_svd(self):
        scalars = SCALAR_RE.findall(self.header)
        self.assertGreater(len(scalars), 100)
        mismatches = []
        for name, value in scalars:
            self.assertIn(name, self.svd, name + " is not an R_INTC register")
            if int(value, 16) != self.svd[name]:
                mismatches.append("%s: header 0x%X, svd 0x%X" %
                                  (name, int(value, 16), self.svd[name]))
        self.assertEqual(mismatches, [])

    def test_parameterized_offsets_match_svd(self):
        params = PARAM_RE.findall(self.header)
        self.assertGreater(len(params), 5)
        mismatches = []
        for name, base, stride in params:
            indexes = [m for m in range(64) if "%s%d" % (name, m) in self.svd]
            self.assertTrue(indexes, name + "(m) has no R_INTC instances")
            for m in indexes:
                value = int(base, 16) + m * int(stride, 16)
                expected = self.svd["%s%d" % (name, m)]
                if value != expected:
                    mismatches.append("%s(%d): header 0x%X, svd 0x%X" %
                                      (name, m, value, expected))
        self.assertEqual(mismatches, [])

    def test_selector_banks_are_pinned(self):
        self.assertEqual(self.svd["INTR8SEL0"], 0x140)
        self.assertEqual(self.svd["INTM33SEL0"], 0x200)
        self.assertEqual(header_define(self.header,
                                       "RZV_INTC_INTR8SEL0_OFFSET"), 0x140)
        self.assertEqual(header_define(self.header,
                                       "RZV_INTC_INTM33SEL0_OFFSET"), 0x200)
        count = header_define(self.header, "RZV_INTC_SEL_REG_COUNT")
        self.assertIn("INTM33SEL%d" % (count - 1), self.svd)
        self.assertNotIn("INTM33SEL%d" % count, self.svd)

    def test_selector_source_encoding(self):
        self.assertEqual(header_define(self.header, "RZV_INTC_IRQSEL_MAX"),
                         0x241)
        self.assertEqual(header_define(self.header, "RZV_INTC_IRQSEL_NONE"),
                         0x3FF)
        none = header_define(self.header, "RZV_INTC_IRQSEL_NONE")
        self.assertEqual(header_define(self.header, "RZV_INTC_SEL_ALL_NONE"),
                         none | none << 10 | none << 20)

    def test_selector_drivers_disconnect_with_no_source(self):
        for source, prefix in (("rzv_icu.c", "rzv_icu"),
                               ("rzv_icu_cm33.c", "rzv_icu_m33")):
            text = (ARCH / source).read_text()
            detach = re.search(r"int %s_detach\(.*?\n}\n" % prefix, text, re.S)
            self.assertIsNotNone(detach, source)
            self.assertIn("%s_set_event(slot, RZV_INTC_IRQSEL_NONE)" % prefix,
                          detach.group(0), source)
            self.assertNotRegex(detach.group(0),
                                r"%s_set_event\(slot,\s*0\)" % prefix, source)
            attach = re.search(r"int %s_attach\(.*?\n}\n" % prefix, text, re.S)
            self.assertIsNotNone(attach, source)
            self.assertIn("RZV_INTC_IRQSEL_MAX", attach.group(0), source)


if __name__ == "__main__":
    unittest.main()
