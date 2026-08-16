#!/usr/bin/env python3

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RZV = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
BOARD = ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src"


class RemainingPeripheralContractTest(unittest.TestCase):
    def test_poeg_event_names_have_one_definition(self):
        public = (RZV / "rzv_poeg.h").read_text()
        hardware = (RZV / "hardware/rzv_poeg.h").read_text()

        for name in ("POEG_EVENT_PORT_INPUT", "POEG_EVENT_SHORT_CIRCUIT"):
            self.assertEqual(len(re.findall(rf"^#define {name}\b", public,
                                            re.MULTILINE)), 1)
            self.assertNotRegex(hardware, rf"(?m)^#define {name}\b")

    def test_poeg_starts_exact_flat_hardware_channel_before_mmio(self):
        driver = (RZV / "rzv_poeg.c").read_text()
        clock = (RZV / "rzv_clock.c").read_text()

        start = driver.index("rzv_poeg_module_start")
        write = driver.index("putreg32(val, reg)")
        self.assertLess(start, write)
        self.assertIn("unit * RZV_POEG_MAX_CHANNELS + channel", driver)
        self.assertIn("RZV_CPG_CLKON(3)", clock)
        self.assertIn("RZV_CPG_BUS_6_MSTOP", clock)
        self.assertIn("RZV_CPG_RSTMON(2)", clock)
        self.assertIn("flat_channel < 3u", clock)

        clock_timeout = re.search(
            r"rzv_cpg_wait_bit\(RZV_CPG_CLKMON\(1\).*?"
            r"if \(ret < 0\)\s*\{\s*"
            r"flags = enter_critical_section\(\);\s*"
            r"rzv_cpg_putreg\(clock_bit << 16, RZV_CPG_CLKON\(3\)\);\s*"
            r"leave_critical_section\(flags\);\s*return ret;\s*\}",
            clock,
            re.DOTALL,
        )
        self.assertIsNotNone(clock_timeout)

    def test_serial_waits_are_bounded_and_setup_errors_propagate(self):
        serial = (RZV / "rzv_serial.c").read_text()

        self.assertIn("RZV_SERIAL_STATUS_TIMEOUT", serial)
        self.assertNotRegex(serial, r"while \(\(rzv_sci_getreg\(priv,")
        self.assertRegex(serial, r"ret = rzv_clock_enable\(priv->clk_id\);")
        self.assertRegex(serial, r"ret = rzv_module_unreset\(priv->clk_id\);")
        self.assertIn("Timed out waiting for transmit end", serial)
        self.assertIn("Timed out waiting for channel stop", serial)

    def test_board_i2c_implements_declared_per_bus_api(self):
        header = (BOARD / "rdk-rzv2h.h").read_text()
        implementation = (BOARD / "rzv2h_i2c.c").read_text()
        bringup = (BOARD / "rzv2h_bringup.c").read_text()

        signature = "struct i2c_master_s *board_i2c_initialize(int bus)"
        self.assertIn(signature, header)
        self.assertIn(signature, implementation)
        self.assertNotIn("int rzv2h_i2c_initialize(void)", implementation)
        self.assertIn("board_i2c_initialize(0)", bringup)
        self.assertIn("g_i2c[4]", implementation)
        self.assertIn("case 3:", implementation)
        self.assertIn("CONFIG_RZV_I2C3", implementation)
        self.assertRegex(implementation, r"if \(g_i2c\[bus\] != NULL\)")
        self.assertIn("return g_i2c[bus];", implementation)
        cache_guard = implementation.index("if (g_i2c[bus] != NULL)")
        lower_init = implementation.index("i2c = rzv_i2c_initialize(bus)")
        cache_store = implementation.index("g_i2c[bus] = i2c")
        self.assertLess(cache_guard, lower_init)
        self.assertLess(implementation.index("i2c_register(i2c, bus)"),
                        cache_store)


if __name__ == "__main__":
    unittest.main()
