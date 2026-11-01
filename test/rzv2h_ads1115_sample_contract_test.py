#!/usr/bin/env python3
"""Host contract checks for the RZ/V2H standalone ADS1115 SCI0 I2C sample."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APPS = ROOT / "platforms/nuttx/NuttX/apps"
DEFCONFIG = NUTTX / "boards/arm/rzv/rdk-rzv2h/configs/ads1115/defconfig"
BOARD_H = NUTTX / "boards/arm/rzv/rdk-rzv2h/include/board.h"
SCI_I2C_H = NUTTX / "boards/arm/rzv/rdk-rzv2h/src/rzv2h_sci_i2c.h"
APP_DIR = APPS / "examples/ads1115"
APP_MAIN = APP_DIR / "ads1115_main.c"
PX4_H = ROOT / "src/drivers/adc/ads1115/ADS1115.h"

# PX4 #define name -> sample #define name
REGISTER_MAP = {
    "ADDRESSPOINTER_REG_CONVERSATION": "ADS1115_REG_CONVERSION",
    "ADDRESSPOINTER_REG_CONFIG": "ADS1115_REG_CONFIG",
    "ADDRESSPOINTER_REG_LO_THRESH": "ADS1115_REG_LO_THRESH",
    "ADDRESSPOINTER_REG_HI_THRESH": "ADS1115_REG_HI_THRESH",
    "CONFIG_HIGH_OS_START_SINGLE": "ADS1115_CFGH_OS_START_SINGLE",
    "CONFIG_HIGH_MUX_P0NG": "ADS1115_CFGH_MUX_P0NG",
    "CONFIG_HIGH_MUX_P3NG": "ADS1115_CFGH_MUX_MASK",
    "CONFIG_HIGH_PGA_6144": "ADS1115_CFGH_PGA_6144",
    "CONFIG_HIGH_MODE_SS": "ADS1115_CFGH_MODE_SS",
    "CONFIG_LOW_DR_250SPS": "ADS1115_CFGL_DR_250SPS",
    "CONFIG_LOW_COMP_QU_DISABLE": "ADS1115_CFGL_COMP_QU_DISABLE",
}


def strip_c_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^(CONFIG_\w+)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def c_defines(path):
    return {
        name: int(value, 0)
        for name, value in re.findall(
            r"^#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b", path.read_text(),
            re.M)
    }


class Ads1115DefconfigContract(unittest.TestCase):
    def setUp(self):
        self.config = config_values(DEFCONFIG)

    def test_enables_sci0_i2c_and_sample(self):
        for symbol in ("CONFIG_I2C", "CONFIG_I2C_DRIVER", "CONFIG_RZV_SCI_I2C",
                       "CONFIG_RZV_SCI0_I2C", "CONFIG_EXAMPLES_ADS1115",
                       "CONFIG_RZV2H_BUILD_CR8_0", "CONFIG_SYSLOG_RTT"):
            self.assertEqual(self.config.get(symbol), "y", symbol)

    def test_sci0_not_claimed_by_uart_or_spi(self):
        for symbol in ("CONFIG_RZV_SCI0", "CONFIG_RZV_SCI0_SPI",
                       "CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT"):
            self.assertNotIn(symbol, self.config)

    def test_only_sci0_i2c_selected(self):
        sci_i2c = [k for k in self.config
                   if re.fullmatch(r"CONFIG_RZV_SCI\d_I2C", k)]
        self.assertEqual(sci_i2c, ["CONFIG_RZV_SCI0_I2C"])


class Ads1115AppContract(unittest.TestCase):
    def test_kconfig_depends_on_i2c_driver_and_defaults_to_bus_10(self):
        text = (APP_DIR / "Kconfig").read_text()
        block = re.search(r"config EXAMPLES_ADS1115\n(.*?)\n\n", text, re.S)
        self.assertIsNotNone(block)
        self.assertIn("depends on I2C_DRIVER", block.group(1))
        bus = re.search(r"config EXAMPLES_ADS1115_DEFAULT_BUS\n.*?default (\d+)",
                        text, re.S)
        sci = c_defines(SCI_I2C_H)
        self.assertEqual(int(bus.group(1)), sci["BOARD_SCI_I2C_BUS_BASE"] + 0)

    def test_registers_match_px4_driver(self):
        sample = c_defines(APP_MAIN)
        px4 = c_defines(PX4_H)
        for px4_name, sample_name in REGISTER_MAP.items():
            self.assertEqual(sample[sample_name], px4[px4_name], px4_name)

    def test_probe_defaults_match_px4_threshold_signature(self):
        # PX4 probe(): bytes LO[0..1], HI[0..1] read as LE uint32 0xFF7F0080
        sample = c_defines(APP_MAIN)
        lo = sample["ADS1115_LO_THRESH_RESET"]
        hi = sample["ADS1115_HI_THRESH_RESET"]
        as_bytes = bytes([lo >> 8, lo & 0xff, hi >> 8, hi & 0xff])
        self.assertEqual(int.from_bytes(as_bytes, "little"), 0xFF7F0080)

    def test_pga_scale_is_6144_mv_full_scale(self):
        sample = c_defines(APP_MAIN)
        # 32768 LSB * 187.5 uV = 6.144 V
        self.assertEqual(sample["ADS1115_UV_PER_LSB_X10"] * 32768 // 10,
                         6144000)

    def test_default_address_and_frequency_match_px4(self):
        sample = c_defines(APP_MAIN)
        px4_main = (ROOT / "src/drivers/adc/ads1115/ads1115_main.cpp").read_text()
        self.assertIn("cli.i2c_address = 0x%x;" % sample["ADS1115_ADDR_DEFAULT"],
                      px4_main)
        self.assertIn("cli.default_i2c_frequency = %d;"
                      % sample["ADS1115_FREQ_DEFAULT"], px4_main)

    def test_read_uses_repeated_start(self):
        code = strip_c_comments(APP_MAIN.read_text())
        self.assertRegex(code, r"msgs\[0\]\.flags\s*=\s*I2C_M_NOSTOP\s*;")
        self.assertIn("I2CIOC_TRANSFER", code)


class Ads1115BoardPinContract(unittest.TestCase):
    def pin(self, text, name):
        return re.search(r"#define %s\s*\\\s*\n\s*\((\w+)([^)]*)\)" % name,
                         text)

    def test_sci0_i2c_pins_are_p50_sda_p51_scl(self):
        text = BOARD_H.read_text()
        sda = self.pin(text, "BOARD_SCI0_I2C_SDA_GPIO")
        scl = self.pin(text, "BOARD_SCI0_I2C_SCL_GPIO")
        self.assertEqual(sda.group(1), "GPIO_TXD0_MOSI0_DA0_P5_0_M1")
        self.assertEqual(scl.group(1), "GPIO_RXD0_MISO0_SCL0_P5_1_M1")

    def test_sci0_pad_flags_match_sci7(self):
        text = BOARD_H.read_text()
        for line in ("SDA", "SCL"):
            sci0 = self.pin(text, "BOARD_SCI0_I2C_%s_GPIO" % line).group(2)
            sci7 = self.pin(text, "BOARD_SCI7_I2C_%s_GPIO" % line).group(2)
            norm = lambda s: re.sub(r"[\s\\]+", "", s)
            self.assertEqual(norm(sci0), norm(sci7), line)


if __name__ == "__main__":
    unittest.main()
