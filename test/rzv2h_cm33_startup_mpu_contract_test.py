#!/usr/bin/env python3
"""Static contracts for the RZ/V2H CM33 stack and ARMv8-M MPU."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
CM33_LINKER = (
    NUTTX
    / "boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cm33.ld"
)
ARMV8M_MPU = NUTTX / "arch/arm/src/armv8-m/arm_mpu.c"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class Rzv2hCm33StartupMpuContractTest(unittest.TestCase):
    def test_cm33_bss_end_is_eabi_aligned_and_linker_guarded(self) -> None:
        linker = read(CM33_LINKER)
        bss = re.search(
            r"\.bss \(NOLOAD\).*?_ebss = ABSOLUTE\(\.\);\s*}",
            linker,
            re.DOTALL,
        )

        self.assertIsNotNone(bss)
        self.assertIn(". = ALIGN(8);", bss.group(0))
        self.assertRegex(
            linker,
            r"ASSERT\s*\(\s*\(?_ebss\s*(?:&\s*7|%\s*8)\)?\s*==\s*0",
        )

    def test_mpu_uses_inclusive_limit_and_rejects_invalid_spans(self) -> None:
        source = read(ARMV8M_MPU)
        function = re.search(
            r"void mpu_configure_region\(.*?\n}\n",
            source,
            re.DOTALL,
        )

        self.assertIsNotNone(function)
        body = function.group(0)
        self.assertRegex(body, r"base\s*\+\s*size\s*-\s*1")
        self.assertRegex(body, r"if\s*\(\s*size\s*==\s*0\s*\)")
        self.assertRegex(
            body,
            r"base\s*>\s*UINTPTR_MAX\s*-\s*\(\s*size\s*-\s*1\s*\)",
        )
        self.assertLess(body.index("if (size == 0)"), body.index("mpu_allocregion"))

    def test_inclusive_limits_match_the_rzv2h_cm33_regions(self) -> None:
        regions = {
            "mhu": (0x50480000, 0x10000, 0x5048FFFF),
            "shared-memory": (0x83820000, 0x8000, 0x83827FFF),
            "rtt": (0x080F8000, 0x4000, 0x080FBFFF),
        }

        for name, (base, size, expected_limit) in regions.items():
            with self.subTest(region=name):
                self.assertEqual(base + size - 1, expected_limit)


if __name__ == "__main__":
    unittest.main()
