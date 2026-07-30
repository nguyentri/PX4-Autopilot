#!/usr/bin/env python3
"""Source/config regressions for the isolated RZ/V2H SCI-SPI sample."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    for match in reversed(list(re.finditer(rf"\b{name}\s*\(", source))):
        start = source.find("{", match.end())
        semicolon = source.find(";", match.end())
        if start >= 0 and (semicolon < 0 or start < semicolon):
            break
    else:
        raise AssertionError(f"function {name} not found")

    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]

    raise AssertionError(f"function {name} has no closing brace")


class SciSpiSampleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.board = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rzv2h_sci_spi.c"
        )
        cls.defconfig = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/configs/sci-spi-loopback/defconfig"
        )

    def test_cmddata_is_a_noop_for_generic_character_transfers(self) -> None:
        body = function_body(self.board, "rzv_sci_spi_cmddata")
        self.assertIn("UNUSED(dev)", body)
        self.assertIn("UNUSED(devid)", body)
        self.assertIn("UNUSED(cmd)", body)
        self.assertIn("return OK", body)
        self.assertNotIn("return -ENODEV", body)

    def test_sample_selects_one_bus_spitool_consumer(self) -> None:
        self.assertIn("CONFIG_SYSTEM_SPITOOL=y", self.defconfig)
        self.assertIn("CONFIG_SPITOOL_MAXBUS=0", self.defconfig)
        self.assertIn("CONFIG_SPITOOL_DEFFREQ=1000000", self.defconfig)

    def test_sample_contains_exact_loopback_wiring_and_oracle(self) -> None:
        self.assertIn("P5_0 (MOSI)", self.defconfig)
        self.assertIn("P5_1 (MISO)", self.defconfig)
        self.assertIn(
            "spi exch -b 0 -f 1000000 -m 0 -w 8 -x 4 a55ac33c",
            self.defconfig,
        )
        self.assertIn('exactly "A5 5A C3 3C"', self.defconfig)


if __name__ == "__main__":
    unittest.main()
