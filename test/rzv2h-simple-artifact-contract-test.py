#!/usr/bin/env python3
"""Audit resolved simple firmware, installed ROMFS and packaged image."""

import argparse
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import zlib

from rzv2h_payload_artifact_contract_test import config_values
from rzv2h_sih_artifact_contract_test import board_defines, executable_script_lines

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build/renesas_rdk-rzv2h_simple"
BOARD_LABEL = "simple"
NAME = "renesas_rdk-rzv2h_simple"


class SimpleArtifactContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = {name: BUILD_DIR / relative for name, relative in {
            "cache": "CMakeCache.txt", "nuttx": "NuttX/nuttx/.config",
            "board": "px4_boardconfig.h", "builtins": "NuttX/px4.bdat",
            "graph": "build.ninja", "map": NAME + ".map",
            "listing": "ROMFS/romfs.txt", "romfs": "ROMFS/romfs.img",
            "elf": NAME + ".elf", "bin": NAME + ".bin", "package": NAME + ".px4",
        }.items()}
        for path in cls.paths.values():
            if not path.is_file():
                raise RuntimeError("missing simple artifact: " + str(path))
        cls.text = {name: path.read_text(encoding="utf-8") for name, path in cls.paths.items()
                    if name not in ("elf", "bin", "romfs")}
        cls.nuttx = config_values(cls.text["nuttx"])
        cls.defines = board_defines(cls.text["board"])
        cls.builtins = set(re.findall(r'^\{ "([^"]+)"', cls.text["builtins"], re.M))
        cls.scripts = {}
        for name in ("rcS", "rc.sysinit", "rc.board_defaults", "rc.board_sensors"):
            path = BUILD_DIR / "etc/init.d" / name
            if not path.is_file():
                raise RuntimeError("missing generated simple script: " + str(path))
            cls.scripts[name] = path.read_text(encoding="utf-8")
        nm = shutil.which("arm-none-eabi-nm")
        if nm is None:
            raise RuntimeError("arm-none-eabi-nm is required")
        cls.nm = nm
        cls.symbols = subprocess.check_output([nm, "-C", str(cls.paths["elf"])], text=True)

    def test_exact_label_kernel_profile_and_romfs(self):
        self.assertEqual(BOARD_LABEL, "simple", "this audit only accepts the isolated simple profile")
        self.assertIn("PX4_BOARD_LABEL:STRING=simple", self.text["cache"])
        self.assertIn("NUTTX_CONFIG:INTERNAL=simple", self.text["cache"])
        self.assertIn("rdk-rzv2h-simple", self.text["graph"])
        self.assertIn("rdk-rzv2h_cr8_0.ld", self.text["map"])
        self.assertIn("src/lib/drivers/device/libdrivers__device.a", self.text["map"])
        self.assertIn("libdrivers__device.a(SPI.cpp.obj)", self.text["map"])
        self.assertRegex(self.text["graph"], r"(?m)^build src/lib/drivers/device/CMakeFiles/drivers__device.dir/nuttx/SPI.cpp.obj:")
        self.assertNotRegex(self.text["graph"], r"(?m)^build src/lib/drivers/device/CMakeFiles/drivers__device.dir/nuttx/I2C.cpp.obj:")
        for name, content in self.scripts.items():
            original = (ROOT / "ROMFS/rdk-rzv2h-simple/init.d" / name).read_text()
            self.assertEqual(executable_script_lines(content), executable_script_lines(original), name)
            self.assertIn(name, self.text["listing"])

    def test_resolved_kernel_has_rtt_spi_irq_and_four_timers_only(self):
        for name in ("RZV2H_BUILD_CR8_0", "ARCH_FPU", "BOARDCTL_RESET", "RZV_HRT", "PWM",
                     "SPI", "SPI_EXCHANGE", "RZV_SPI0", "RZV_GPIO_IRQ", "RZV_GPT6", "RZV_GPT7",
                     "RZV_GPT9", "RZV_GPT10", "FS_ROMFS", "FS_TMPFS", "SCHED_HPWORK", "SCHED_LPWORK",
                     "SYSLOG_RTT", "SYSLOG_RTT_CONSOLE_INPUT", "SEGGER_RTT", "DEV_CONSOLE", "CONSOLE_SYSLOG"):
            self.assertEqual(self.nuttx.get("CONFIG_" + name), "y", name)
        forbidden = ("I2C", "UART", "RZV_SCI_I2C", "RZV_DMAC", "RZV_OPENAMP", "RZV_IPC_RAW",
                     "RZV_IPC_IPCC", "RZV_SPI1", "SPI_DRIVER", "ARCH_BUTTONS", "RZV2H_ICM20948_TEST",
                     "EXAMPLES_GY912", "EXAMPLES_PWM", "RZV2H_SPI_LOOPBACK_EXAMPLE",
                     "RZV2H_SPI_INTERNAL_LOOPBACK_SAMPLE", "RZV2H_EXAMPLE_SUPPORT", "RZV_PWM",
                     "RZV2H_PWM_ONESHOT_EXAMPLE", "RDK_RZV2H_XSPI_PARAMFS", "MMCSD")
        for name in forbidden:
            self.assertNotEqual(self.nuttx.get("CONFIG_" + name), "y", name)
        for name, value in self.nuttx.items():
            if re.fullmatch(r"CONFIG_RZV_SCI\d+", name) or name.endswith("_SERIAL_CONSOLE"):
                self.assertNotEqual(value, "y", name)

    def test_resolved_px4_consumers_exclude_flight_and_payload(self):
        required = {"CONFIG_" + name for name in ("DRIVERS_IMU_INVENSENSE_ICM20948", "DRIVERS_PWM_OUT",
                    "MODULES_CONTROL_ALLOCATOR", "SYSTEMCMDS_ACTUATOR_TEST", "SYSTEMCMDS_TOPIC_LISTENER",
                    "SYSTEMCMDS_PARAM", "SYSTEMCMDS_WORK_QUEUE", "SYSTEMCMDS_UORB")}
        self.assertFalse(required - self.defines, required - self.defines)
        modules = {name for name in self.defines if name.startswith("CONFIG_MODULES_")}
        self.assertEqual(modules, {"CONFIG_MODULES_CONTROL_ALLOCATOR"})
        drivers = {name for name in self.defines if name.startswith("CONFIG_DRIVERS_")}
        self.assertEqual(drivers, {"CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948", "CONFIG_DRIVERS_PWM_OUT"})
        roles = re.findall(r'^#define CONFIG_BOARD_SERIAL_\w+ (.+)$', self.text["board"], re.M)
        self.assertTrue(roles)
        self.assertTrue(all(role == '\"\"' for role in roles), roles)
        forbidden = {"CONFIG_" + name for name in ("DRIVERS_IMU_INVENSENSE_MPU9250", "DRIVERS_BAROMETER",
                     "DRIVERS_DSHOT", "DRIVERS_GPS", "DRIVERS_RC_INPUT", "DRIVERS_DISTANCE_SENSOR_TFMINI",
                     "MODULES_COMMANDER", "MODULES_SENSORS", "MODULES_EKF2", "MODULES_MAVLINK",
                     "MODULES_DATAMAN", "MODULES_LOGGER", "MODULES_MANUAL_CONTROL", "MODULES_MC_RATE_CONTROL",
                     "MODULES_MC_ATT_CONTROL", "MODULES_MC_POS_CONTROL", "MODULES_NAVIGATOR",
                     "BOARD_RDK_RZV2H_PX4IO_BRIDGE")}
        self.assertFalse(forbidden & self.defines, forbidden & self.defines)
        self.assertFalse({"commander", "sensors", "ekf2", "mavlink", "dataman", "logger", "mpu9250",
                          "bmp280", "gps", "rc_input", "dshot", "px4io_cr8_0", "serial_status", "tfmini"} & self.builtins)
        self.assertTrue({"icm20948", "pwm_out", "actuator_test", "listener", "param", "work_queue",
                         "control_allocator", "uorb", "ver"} <= self.builtins)

    def test_linked_hal_sensor_callbacks_and_core_prerequisites(self):
        for symbol in ("icm20948_main", "pwm_out_main", "actuator_test_main", "listener_main",
                       "board_spi_initialize", "rzv_spi_select", "px4_spi_buses", "rzv_gpio_irq_initialize",
                       "rzv_gpiosetevent", "hrt_init", "board_app_initialize", "board_on_reset",
                       "ICM20948::DataReadyInterruptCallback", "ICM20948::FIFORead", "px4::WorkQueue", "_SEGGER_RTT"):
            self.assertIn(symbol, self.symbols, symbol)
        for implementation in ("device::SPI::SPI\\(", "device::SPI::init\\(\\)", "device::SPI::transfer\\("):
            self.assertRegex(self.symbols, r"(?m)^\S+ T " + implementation)
        self.assertRegex(self.symbols, r"(?m)^\S+ T rzv_spi_select$")
        self.assertEqual(subprocess.check_output([self.nm, "-u", str(self.paths["elf"])], text=True).strip(), "")

    def test_installed_startup_has_independent_requests_and_no_auto_outputs(self):
        executable = "\n".join(line for content in self.scripts.values() for line in content.splitlines()
                               if not line.lstrip().startswith("#"))
        self.assertIn("if pwm_out start", self.scripts["rcS"])
        self.assertIn("if icm20948 -s -b 0 -R 0 start", self.scripts["rc.board_sensors"])
        self.assertNotRegex(executable, r"\b(?:control_allocator|commander|sensors|px4io|mpu9250|bmp280)\s+start")
        self.assertNotRegex(executable, r"actuator_test\s+(?:set|iterate)|\s-M(?:\s|$)|\bready\b")
        defaults = self.scripts["rc.board_defaults"]
        for timer in range(4):
            self.assertIn(f"param set-default PWM_MAIN_TIM{timer} 400", defaults)
        for channel in range(1, 5):
            for suffix, value in (("FUNC", 100 + channel), ("MIN", 1100), ("MAX", 1900), ("DIS", 1000), ("FAIL", 1000)):
                self.assertIn(f"param set-default PWM_MAIN_{suffix}{channel} {value}", defaults)

    def test_split_binary_and_package_are_the_same_image(self):
        image = self.paths["bin"].read_bytes()
        split = b"".join((BUILD_DIR / (NAME + suffix)).read_bytes() for suffix in
                         ("_header.bin", "_itcm.bin", "_sram.bin", "_sdram.bin"))
        self.assertEqual(split, image)
        package = json.loads(self.text["package"])
        self.assertEqual(zlib.decompress(base64.b64decode(package["image"])), image)
        self.assertEqual(package["image_size"], len(image))
        self.assertLessEqual(len(image), package["image_maxsize"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", default=str(BUILD_DIR))
    parser.add_argument("--board-label", default=BOARD_LABEL)
    args, unittest_args = parser.parse_known_args()
    BUILD_DIR = Path(args.build_dir).resolve()
    BOARD_LABEL = args.board_label
    unittest.main(argv=[sys.argv[0]] + unittest_args)
