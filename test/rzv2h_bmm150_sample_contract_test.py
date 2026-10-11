#!/usr/bin/env python3
"""Host contract checks for the RZ/V2H standalone BMM150 SCI7 I2C sample."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APPS = ROOT / "platforms/nuttx/NuttX/apps"
DEFCONFIG = NUTTX / "boards/arm/rzv/rdk-rzv2h/configs/bmm150/defconfig"
BOARD_H = NUTTX / "boards/arm/rzv/rdk-rzv2h/include/board.h"
APP_DIR = APPS / "examples/bmm150"
APP_MAIN = APP_DIR / "bmm150_main.c"
PX4_REGS = ROOT / "src/drivers/magnetometer/bosch/bmm150/Bosch_BMM150_registers.hpp"

# PX4 register enum name -> sample #define name
REGISTER_MAP = {
    "CHIP_ID": "BMM150_REG_CHIP_ID",
    "DATAX_LSB": "BMM150_REG_DATAX_LSB",
    "DATAY_LSB": "BMM150_REG_DATAY_LSB",
    "DATAZ_LSB": "BMM150_REG_DATAZ_LSB",
    "POWER_CONTROL": "BMM150_REG_POWER_CONTROL",
    "OP_MODE": "BMM150_REG_OP_MODE",
    "REPXY": "BMM150_REG_REPXY",
    "REPZ": "BMM150_REG_REPZ",
    "DIG_X1": "BMM150_REG_DIG_X1",
    "DIG_Z4_LSB": "BMM150_REG_DIG_Z4_LSB",
    "DIG_Z2_LSB": "BMM150_REG_DIG_Z2_LSB",
}

# PX4 bit enum name -> sample #define name
BIT_MAP = {
    "SoftReset": "BMM150_PWR_SOFT_RESET",
    "PowerControl": "BMM150_PWR_POWER_ON",
    "ODR_20HZ_SET": "BMM150_OPMODE_ODR20_SET",
    "ODR_20HZ_CLEAR": "BMM150_OPMODE_ODR20_CLR",
    "Opmode_Sleep": "BMM150_OPMODE_SLEEP",
    "Self_Test": "BMM150_OPMODE_SELF_TEST",
    "Overflow": "BMM150_STATUS_OVERFLOW",
    "XY_HA_SET": "BMM150_REPXY_SET",
    "XY_HA_CLEAR": "BMM150_REPXY_CLR",
    "Z_HA_SET": "BMM150_REPZ_SET",
    "Z_HA_CLEAR": "BMM150_REPZ_CLR",
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
        name: int(value, 16)
        for name, value in re.findall(
            r"^#define\s+(\w+)\s+0x([0-9a-fA-F]+)\b", path.read_text(), re.M)
    }


def px4_registers(path):
    text = path.read_text()
    regs = {
        name: int(value, 16)
        for name, value in re.findall(r"^\s*(\w+)\s*=\s*0x([0-9a-fA-F]+)\s*,",
                                      text, re.M)
    }
    chip = re.search(r"chip_identification_number\s*=\s*0x([0-9a-fA-F]+)", text)
    regs["chip_identification_number"] = int(chip.group(1), 16)
    return regs


def px4_bits(path):
    bits = {}
    for name, expr in re.findall(r"^\s*(\w+)\s*=\s*((?:Bit\d\s*\|?\s*)+),",
                                 path.read_text(), re.M):
        bits[name] = sum(1 << int(b) for b in re.findall(r"Bit(\d)", expr))
    return bits


def px4_overflow(path, name):
    return int(re.search(name + r"\s*=\s*(-\d+)", path.read_text()).group(1))


class Bmm150DefconfigContract(unittest.TestCase):
    def setUp(self):
        self.config = config_values(DEFCONFIG)

    def test_enables_sci7_i2c_and_sample(self):
        for symbol in ("CONFIG_I2C", "CONFIG_I2C_DRIVER", "CONFIG_RZV_SCI_I2C",
                       "CONFIG_RZV_SCI7_I2C", "CONFIG_EXAMPLES_BMM150"):
            self.assertEqual(self.config.get(symbol), "y", symbol)

    def test_sci7_uart_mode_not_selected(self):
        self.assertNotEqual(self.config.get("CONFIG_RZV_SCI7"), "y")

    def test_spi_sensor_samples_not_selected(self):
        for symbol in ("CONFIG_EXAMPLES_GY912", "CONFIG_SENSORS_ICM20948"):
            self.assertNotIn(symbol, self.config)


class Bmm150AppContract(unittest.TestCase):
    def test_kconfig_depends_on_i2c_driver(self):
        text = (APP_DIR / "Kconfig").read_text()
        block = re.search(r"config EXAMPLES_BMM150\n(.*?)\n\n", text, re.S)
        self.assertIsNotNone(block)
        self.assertIn("depends on I2C_DRIVER", block.group(1))

    def test_registers_match_px4_driver(self):
        sample = c_defines(APP_MAIN)
        px4 = px4_registers(PX4_REGS)
        for px4_name, sample_name in REGISTER_MAP.items():
            self.assertEqual(sample[sample_name], px4[px4_name], px4_name)
        self.assertEqual(sample["BMM150_CHIP_ID_VALUE"],
                         px4["chip_identification_number"])

    def test_bit_masks_match_px4_driver(self):
        sample = c_defines(APP_MAIN)
        px4 = px4_bits(PX4_REGS)
        for px4_name, sample_name in BIT_MAP.items():
            self.assertEqual(sample[sample_name], px4[px4_name], px4_name)

    def test_overflow_sentinels_match_px4_driver(self):
        text = APP_MAIN.read_text()
        for px4_name, sample_name in (("OVERFLOW_XYAXES", "BMM150_OVERFLOW_XY"),
                                      ("OVERFLOW_ZAXIS", "BMM150_OVERFLOW_Z")):
            value = re.search(r"#define\s+%s\s+\((-\d+)\)" % sample_name, text)
            self.assertEqual(int(value.group(1)),
                             px4_overflow(PX4_REGS, px4_name), px4_name)

    def test_read_uses_repeated_start(self):
        code = strip_c_comments(APP_MAIN.read_text())
        self.assertRegex(code, r"msgs\[0\]\.flags\s*=\s*I2C_M_NOSTOP\s*;")
        self.assertIn("I2CIOC_TRANSFER", code)


class Bmm150BoardPinContract(unittest.TestCase):
    def test_sci7_i2c_pins_are_p76_p77(self):
        text = BOARD_H.read_text()
        sda = re.search(r"#define BOARD_SCI7_I2C_SDA_GPIO\s*\\\s*\n\s*\((\w+)", text)
        scl = re.search(r"#define BOARD_SCI7_I2C_SCL_GPIO\s*\\\s*\n\s*\((\w+)", text)
        self.assertEqual(sda.group(1), "GPIO_TXD7_MOSI7_SDA7_P7_6_M1")
        self.assertEqual(scl.group(1), "GPIO_RXD7_MISO7_SCL7_P7_7_M1")


if __name__ == "__main__":
    unittest.main()
