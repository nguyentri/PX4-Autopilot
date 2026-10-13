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

    def test_integrated_default_console_is_owned_by_nuttx_rtt(self) -> None:
        config = (BOARD.parent / "nuttx-config/nsh/defconfig").read_text(encoding="utf-8")
        for option in ("CONFIG_NO_SERIAL_CONSOLE=y", "CONFIG_SYSLOG_RTT=y",
                       "CONFIG_CONSOLE_SYSLOG=y", "CONFIG_SYSLOG_RTT_CONSOLE_INPUT=y"):
            with self.subTest(option=option):
                self.assertIn(option, config)
        self.assertNotIn("\nCONFIG_SCI4_SERIAL_CONSOLE=y", config)
        self.assertNotIn("\nCONFIG_SCI4_SERIAL_CONSOLE=y", self.source)
        self.assertIn("CONFIG_RZV_SCI4=y", config)
        self.assertIn('#CONFIG_BOARD_SERIAL_EXT2="/dev/ttyS4"', self.source)


if __name__ == "__main__":
    unittest.main()
