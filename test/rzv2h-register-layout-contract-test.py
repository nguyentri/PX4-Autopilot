#!/usr/bin/env python3
"""Compile every repaired register offset and access width against CMSIS."""

import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("layout", ROOT / "Tools/rzv2h-register-layout.py")
LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT)
HW = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware"
TYPES = [("i3c", "i3c_b", "R_I3C_B0_Type"), ("ssi", "ssi", "R_SSI0_Type"),
         ("tzc", "tzc", "R_TZC400_Type"), ("xspi", "xspi", "R_XSPI0_Type")]


class RegisterLayouts(unittest.TestCase):
    def test_offsets_widths_and_nested_access_views(self):
        for core, sample in (("cr", "cr8_0"), ("cr", "cr8_1"), ("cm", "cm33")):
            ref = ROOT / (f"refs/rzv2h_evk/adc_e/adc_e_rzv2h_evk_{sample}_ep/"
                          "e2studio/rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/"
                          f"R9A09G057H/{core}/iodefines")
            if not ref.is_dir():
                self.skipTest(f"local CMSIS authority unavailable: {ref}")
            with tempfile.TemporaryDirectory(prefix="rzv2h-register-check-") as d:
                tmp = Path(d)
                (tmp / "nuttx").mkdir()
                (tmp / "nuttx/config.h").write_text(
                    "#define CONFIG_RZV2H_BUILD_CM33 1\n" if core == "cm" else "")
                for native, vendor, type_name in TYPES:
                    authority = ref / f"{vendor}_iodefine.h"
                    rows = LAYOUT.register_layout(authority, type_name)
                    code = ('#include <stdint.h>\n#include <stddef.h>\n'
                            '#define __IM volatile const\n#define __OM volatile\n'
                            '#define __IOM volatile\n'
                            f'#include "{authority}"\n#include "{HW / ("rzv_" + native + ".h")}"\n')
                    for row in rows:
                        member = row["member"]
                        name = re.sub(r"[.\[\]]", "_", member).strip("_").replace("__", "_").upper()
                        prefix = f"RZV_{native.upper()}_{name}"
                        code += f'_Static_assert({prefix}_OFFSET == offsetof({type_name}, {member}), "{member}");\n'
                        code += f'_Static_assert({prefix}_WIDTH == sizeof((({type_name} *)0)->{member}), "{member} width");\n'
                    (tmp / "check.c").write_text(code)
                    with self.subTest(core=sample, peripheral=native):
                        result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                                 "-fsyntax-only", "-I", str(tmp), str(tmp / "check.c")],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
