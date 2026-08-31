#!/usr/bin/env python3
"""Source contract for the integrated RZ/V2H default PX4 board."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards/renesas/rdk-rzv2h/default.px4board"


class Rzv2hDefaultBoardContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BOARD.read_text(encoding="utf-8")

    def test_integrated_default_board_uses_sci4_as_console(self) -> None:
        expected = (
            "CONFIG_SERIAL=y",
            "CONFIG_STANDARD_SERIAL=y",
            "CONFIG_SCI4_SERIALDRIVER=y",
            "CONFIG_SCI4_SERIAL_CONSOLE=y",
            "CONFIG_SCI4_RXBUFSIZE=256",
            "CONFIG_SCI4_TXBUFSIZE=256",
            "CONFIG_SCI4_BAUD=115200",
            "CONFIG_SCI4_BITS=8",
            "CONFIG_SCI4_PARITY=0",
            "CONFIG_SCI4_2STOP=0",
            "CONFIG_RZV_SCI4=y",
            "CONFIG_DEV_CONSOLE=y",
            "CONFIG_SERIAL_CONSOLE=y",
        )

        for option in expected:
            with self.subTest(option=option):
                self.assertIn(option, self.source)

        self.assertIn('#CONFIG_BOARD_SERIAL_EXT2="/dev/ttyS4"', self.source)


if __name__ == "__main__":
    unittest.main()
