#!/usr/bin/env python3
"""Check the ADC route against the RZ/V2H INTR8SEL scan-end selector."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"


class AdcIrqSelector(unittest.TestCase):
    def test_scan_end_uses_irq_selector_namespace(self):
        driver = Path(os.environ.get("RZV_ADC_SOURCE", ARCH / "rzv_adc.c")).read_text()
        config = re.search(r"g_adc0_config\s*=\s*\{(.*?)\};", driver, re.S).group(1)
        selector = re.search(r"\.(?:irq_sel|elc_event)\s*=\s*([^,]+)", config).group(1)
        header = (ARCH / "hardware/rzv_intc.h").read_text()
        header = re.sub(r"^\s*#\s*include[^\n]*$", "", header, flags=re.M)
        # The primary CR8/CM33 FSP IRQSEL tables specify ADIREQ_N as 575;
        # the ELC scan-end event 256 belongs to a different selector domain.
        code = "#include <assert.h>\n" + header
        code += "\n#define RZV_ELC_ADC0_ADA_ADELCREQ 256\n"
        code += f"int main(void) {{ assert(({selector}) == 575); return 0; }}\n"
        with tempfile.TemporaryDirectory(prefix="rzv2h-adc-irqsel-") as directory:
            path = Path(directory)
            (path / "case.c").write_text(code)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path / "case.c"), "-o", str(path / "case")], check=True)
            subprocess.run([str(path / "case")], check=True)


if __name__ == "__main__":
    unittest.main()
