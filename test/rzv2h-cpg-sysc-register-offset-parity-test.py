#!/usr/bin/env python3
"""Check RZ/V2H CPG and SYSC register offsets against rzv2h.svd.

Every parameterized RZV_CPG_<NAME>_OFFSET(m) and RZV_SYSC_<NAME>_OFFSET(m)
macro is evaluated by the host C compiler (so the header expression itself
is checked, including families whose first instance is not index 0) and
compared with the R_CPG / R_SYSC addressOffset of each <NAME><m> (or
<NAME>_<m>) register that the CMSIS-SVD file lists.  The CR8 system reset must route the
watchdog error event through CPG_ERRORRST_SEL2, at R_CPG base + 0xAF4.
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SVD = ROOT / "rzv2h.svd"
MAX_INDEX = 64

FAMILIES = (
    # (header, macro prefix, SVD peripheral, SVD register-name prefix)
    ("rzv_cpg.h", "RZV_CPG_", "R_CPG", "CPG_"),
    ("rzv_sysc.h", "RZV_SYSC_", "R_SYSC", ""),
)


def svd_peripheral(name):
    for peripheral in ET.parse(SVD).getroot().iter("peripheral"):
        if peripheral.findtext("name") == name:
            base = int(peripheral.findtext("baseAddress"), 0)
            offsets = {r.findtext("name"): int(r.findtext("addressOffset"), 0)
                       for r in peripheral.iter("register")}
            return base, offsets
    raise AssertionError(name + " peripheral missing from rzv2h.svd")


def svd_name(svd, name, index):
    """Return the SVD register for family instance index, if it exists."""
    for candidate in ("%s%d" % (name, index), "%s_%d" % (name, index)):
        if candidate in svd:
            return candidate
    return None


def evaluate(header, expressions):
    """Compile header and return the integer value of each expression."""
    with tempfile.TemporaryDirectory(prefix="rzv2h-cpg-sysc-") as directory:
        path = Path(directory)
        (path / "nuttx").mkdir()
        (path / "nuttx" / "config.h").write_text("")
        lines = ["#include <stdio.h>", "#include <stdint.h>",
                 '#include "%s"' % (ARCH / "hardware" / header),
                 '#include "%s"' % (ARCH / "hardware" / "rzv_wdt.h"),
                 "int main(void) {"]
        for expression in expressions:
            lines.append('  printf("%%llu\\n", (unsigned long long)(%s));'
                         % expression)
        lines += ["  return 0;", "}"]
        (path / "check.c").write_text("\n".join(lines) + "\n")
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror",
                        "-I", str(path), "-I", str(ARCH),
                        str(path / "check.c"), "-o", str(path / "check")],
                       check=True)
        output = subprocess.run([str(path / "check")], check=True,
                                capture_output=True, text=True).stdout
    return [int(value) for value in output.split()]


class CpgSyscRegisterOffsetParity(unittest.TestCase):
    def test_parameterized_offsets_match_svd(self):
        for header, prefix, peripheral, svd_prefix in FAMILIES:
            with self.subTest(header=header):
                text = (ARCH / "hardware" / header).read_text()
                names = re.findall(r"^#define\s+%s(\w+)_OFFSET\(m\)"
                                   % prefix, text, re.M)
                self.assertGreater(len(names), 5, header)
                _, svd = svd_peripheral(peripheral)
                cases = []
                for name in names:
                    found = [(name, m, svd_name(svd, svd_prefix + name, m))
                             for m in range(MAX_INDEX)]
                    found = [case for case in found if case[2]]
                    self.assertTrue(found, "%s%s(m) has no %s instances"
                                    % (prefix, name, peripheral))
                    cases += found
                values = evaluate(header, ["%s%s_OFFSET(%d)" % (prefix, n, m)
                                           for n, m, _ in cases])
                mismatches = [
                    "%s%s_OFFSET(%d): header 0x%X, svd %s 0x%X"
                    % (prefix, n, m, value, register, svd[register])
                    for (n, m, register), value in zip(cases, values)
                    if value != svd[register]]
                self.assertEqual(mismatches, [])

    def test_families_starting_after_index_zero_are_pinned(self):
        cpg_base, cpg = svd_peripheral("R_CPG")
        sysc_base, sysc = svd_peripheral("R_SYSC")
        pinned = (
            ("RZV_CPG_ERRORRST_SEL_OFFSET(1)", cpg["CPG_ERRORRST_SEL1"]),
            ("RZV_CPG_ERROR_RST_OFFSET(2)", cpg["CPG_ERROR_RST2"]),
            ("RZV_CPG_LP_CTL_OFFSET(1)", cpg["CPG_LP_CTL1"]),
            ("RZV_CPG_LP_CST_CTL_OFFSET(2)", cpg["CPG_LP_CST_CTL2"]),
            ("RZV_CPG_LP_PWC_CTL_OFFSET(1)", cpg["CPG_LP_PWC_CTL1"]),
            ("RZV_CPG_LP_SRAM_STBY_CTL_OFFSET(1)",
             cpg["CPG_LP_SRAM_STBY_CTL1"]),
            ("RZV_CPG_PLLDSI_CLK_OFFSET(1)", cpg["CPG_PLLDSI_CLK1"]),
            ("RZV_CPG_PLLGPU_CLK_OFFSET(1)", cpg["CPG_PLLGPU_CLK1"]),
            ("RZV_CPG_PLLDRP_CLK_OFFSET(1)", cpg["CPG_PLLDRP_CLK1"]),
        )
        values = evaluate("rzv_cpg.h", [e for e, _ in pinned] +
                          ["RZV_CPG_BASE"])
        for (expression, expected), value in zip(pinned, values):
            self.assertEqual(value, expected, expression)
        self.assertEqual(values[-1], cpg_base)
        sysc_values = evaluate("rzv_sysc.h", [
            "RZV_SYSC_SYS_MCPU_CFG_OFFSET(2)",
            "RZV_SYSC_SYS_RCPU_CONFIG_OFFSET(1)", "RZV_SYSC_BASE"])
        self.assertEqual(sysc_values, [sysc["SYS_MCPU_CFG2"],
                                       sysc["SYS_RCPU_CONFIG1"], sysc_base])

    def test_cr8_system_reset_routes_through_errorrst_sel2(self):
        cpg_base, cpg = svd_peripheral("R_CPG")
        address, = evaluate("rzv_cpg.h", [
            "RZV_CPG_ERRORRST_SEL(RZV_CPG_ERRORRST_SEL2_M)"])
        self.assertEqual(address, cpg_base + cpg["CPG_ERRORRST_SEL2"])
        self.assertEqual(address, 0x10420010 + 0xAF4)
        source = (ARCH / "rzv_systemreset.c").read_text()
        body = source[source.index("void up_systemreset(void)"):]
        self.assertRegex(body, r"putreg32\(RZV_CPG_ERRORRST_SEL2_BIT\(channel\)"
                         r"\s*\|\s*RZV_CPG_ERRORRST_SEL2_WEN\(channel\),\s*"
                         r"RZV_CPG_ERRORRST_SEL\(RZV_CPG_ERRORRST_SEL2_M\)\)")
        # The watchdog event that ERRORRST_SEL2 routes is the error
        # notification output (RSTIRQS=0), as in FSP.
        self.assertIn("WDT_WDTRCR_RSTIRQS_ERROR_NOTIFY", body)
        self.assertNotIn("WDT_WDTRCR_RSTIRQS_RESET_OUTPUT", body)

    def test_watchdog_clock_selects_only_permitted_dividers(self):
        names = ["DIV1", "DIV16", "DIV32", "DIV64", "DIV128", "DIV256"]
        values = evaluate("rzv_cpg.h", ["WDT_WDTCR_CKS_" + n for n in names])
        self.assertEqual(values, [0x0, 0x2, 0x3, 0x4, 0xF, 0x5])
        source = (ARCH / "rzv_wdt.c").read_text()
        table = source[source.index("const uint8_t cks_val[]"):]
        table = table[:table.index("};")]
        self.assertEqual(re.findall(r"WDT_WDTCR_CKS_(DIV\d+)", table), names)
        self.assertNotRegex(table, r"0x[0-9a-fA-F]")


if __name__ == "__main__":
    unittest.main()
