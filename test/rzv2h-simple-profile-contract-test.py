#!/usr/bin/env python3
"""Compile real descriptors/IRQ guard and check isolated simple startup."""

from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

from rzv2h_payload_artifact_contract_test import config_values

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = runpy.run_path(str(ROOT / "test/rzv2h-simple-test-support.py"))
read = SUPPORT["read"]
body = SUPPORT["body"]
PROFILE = "boards/renesas/rdk-rzv2h/"
ROMFS = "ROMFS/rdk-rzv2h-simple/"


class CompiledDescriptorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-simple-descriptor-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        SUPPORT["host_headers"](cls.directory)

    def test_real_simple_default_and_dshot_tables(self):
        for label, driver in (("simple", "ICM20948"), ("default", "MPU9250"), ("dshot", "MPU9250")):
            with self.subTest(label=label):
                defines = ["CONFIG_DRIVERS_IMU_INVENSENSE_" + driver]
                if label == "dshot":
                    defines.append("CONFIG_DRIVERS_DSHOT")
                binary, result = SUPPORT["compile_descriptor"](self.directory, label, defines)
                self.assertEqual(result.returncode, 0, result.stderr)
                subprocess.run([str(binary)], check=True)

    def test_both_physical_imu_choices_are_rejected(self):
        _, result = SUPPORT["compile_descriptor"](self.directory, "both", [
            "CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948", "CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SPI0/P93 supports one IMU", result.stderr)

    def test_table_without_a_sensor_choice_is_rejected(self):
        _, result = SUPPORT["compile_descriptor"](self.directory, "neither", [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("The sensor SPI table requires an enabled IMU driver", result.stderr)

    def test_actual_guard_preserves_live_irq_owner_on_repeated_initialization(self):
        binary = SUPPORT["compile_irq"](self.directory)
        subprocess.run([str(binary)], check=True)


class SimpleSourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = config_values(read(PROFILE + "simple.px4board"))
        cls.nuttx = config_values(read(PROFILE + "nuttx-config/simple/defconfig"))
        cls.rcs = read(ROMFS + "init.d/rcS")
        cls.defaults = read(ROMFS + "init.d/rc.board_defaults")
        cls.sensors = read(ROMFS + "init.d/rc.board_sensors")
        cls.board_cmake = read(PROFILE + "src/CMakeLists.txt")

    def test_simple_overlay_selects_only_icm_pwm_and_diagnostics(self):
        self.assertEqual(self.board["CONFIG_BOARD_ROMFSROOT"], '"rdk-rzv2h-simple"')
        self.assertEqual(self.board.get("CONFIG_SPI"), "y", "PX4 wrapper CONFIG_SPI must be explicit")
        self.assertEqual(self.board.get("CONFIG_I2C"), "n", "PX4 I2C wrapper must remain absent")
        for name in ("DRIVERS_IMU", "DRIVERS_IMU_INVENSENSE_ICM20948", "DRIVERS_PWM_OUT",
                     "MODULES_CONTROL_ALLOCATOR", "SYSTEMCMDS_ACTUATOR_TEST", "SYSTEMCMDS_TOPIC_LISTENER"):
            self.assertEqual(self.board.get("CONFIG_" + name), "y", name)
        for name in ("DRIVERS_IMU_INVENSENSE_MPU9250", "DRIVERS_BAROMETER", "DRIVERS_DSHOT",
                     "DRIVERS_RC_INPUT", "DRIVERS_GPS", "MODULES_COMMANDER", "MODULES_SENSORS",
                     "MODULES_MAVLINK", "MODULES_EKF2", "BOARD_RDK_RZV2H_PX4IO_BRIDGE"):
            self.assertEqual(self.board.get("CONFIG_" + name), "n", name)

    def test_discovered_targets_match_readme_and_retire_core_only(self):
        targets = subprocess.check_output(
            ["bash", str(ROOT / "build.sh"), "--list"], cwd=ROOT, text=True
        ).splitlines()
        self.assertIn("renesas_rdk-rzv2h_simple", targets)
        self.assertNotIn("renesas_rdk-rzv2h_core_only", targets)
        documented = re.search(
            r"### Build Targets\s+[\s\S]*?```text\s+([\s\S]*?)```", read("README.md")
        )
        self.assertIsNotNone(documented)
        self.assertEqual(targets, documented.group(1).strip().splitlines())
        self.assertTrue((ROOT / PROFILE / "nuttx-config/core_only/defconfig").is_file())
        self.assertTrue((ROOT / "ROMFS/rdk-rzv2h-core-only").is_dir())

    def test_kernel_retains_rtt_timers_and_one_sensor_owner(self):
        for name in ("RZV2H_BUILD_CR8_0", "ARCH_FPU", "RZV_HRT", "PWM", "RZV_GPT6", "RZV_GPT7",
                     "RZV_GPT9", "RZV_GPT10", "SPI", "SPI_EXCHANGE", "RZV_SPI0", "RZV_GPIO_IRQ",
                     "SYSLOG_RTT", "SYSLOG_RTT_CONSOLE_INPUT", "NO_SERIAL_CONSOLE"):
            self.assertEqual(self.nuttx.get("CONFIG_" + name), "y", name)
        for name in ("ARCH_BUTTONS", "RZV2H_SPI_INTERNAL_LOOPBACK_SAMPLE", "RZV2H_SPI_LOOPBACK_EXAMPLE",
                     "RZV2H_ICM20948_TEST", "EXAMPLES_GY912", "EXAMPLES_PWM", "SPI_DRIVER",
                     "RZV_SPI1", "I2C", "RZV_OPENAMP", "RZV_IPC_RAW", "RZV_IPC_IPCC", "RZV_DMAC"):
            self.assertNotEqual(self.nuttx.get("CONFIG_" + name), "y", name)

    def test_romfs_explicit_hooks_exclude_generic_payload(self):
        self.assertIn("set(config_romfs_include_board_init false PARENT_SCOPE)", read(ROMFS + "CMakeLists.txt"))
        cmake = read(ROMFS + "init.d/CMakeLists.txt")
        for script in ("rcS", "rc.sysinit", "rc.board_defaults", "rc.board_sensors"):
            self.assertIn(script, cmake)
        self.assertIn(". /etc/init.d/rc.filepaths", self.rcs)
        self.assertLess(self.rcs.index("param select $PARAM_FILE"), self.rcs.index("rc.board_defaults"))
        self.assertIn(". /etc/init.d/rc.board_sensors", self.rcs)

    def test_start_requests_are_independent_and_never_claim_ready(self):
        self.assertIn("if pwm_out start", self.rcs)
        self.assertIn("ERROR [init] pwm_out start failed", self.rcs)
        self.assertLess(self.rcs.index("fi"), self.rcs.index(". /etc/init.d/rc.board_sensors"))
        self.assertIn("if icm20948 -s -b 0 -R 0 start", self.sensors)
        self.assertIn("ERROR [init] icm20948 SPI0 start failed", self.sensors)
        executable = "\n".join(line for line in (self.rcs + self.sensors).splitlines()
                               if not line.lstrip().startswith("#"))
        self.assertNotRegex(executable.lower(), r"\bready\b")
        self.assertNotRegex(executable, r"\b(?:commander|sensors|control_allocator|mpu9250|bmp280|px4io)\s+start")
        self.assertNotRegex(executable, r"actuator_test\s+(?:set|iterate)|\s-M(?:\s|$)")

    def test_four_channel_parameters_and_no_boot_actuator_test(self):
        for timer in range(4):
            self.assertIn(f"param set-default PWM_MAIN_TIM{timer} 400", self.defaults)
        for channel in range(1, 5):
            for suffix, value in (("FUNC", 100 + channel), ("MIN", 1100), ("MAX", 1900), ("DIS", 1000), ("FAIL", 1000)):
                self.assertIn(f"param set-default PWM_MAIN_{suffix}{channel} {value}", self.defaults)

    def test_label_and_cmake_linkage_guards_are_installed(self):
        self.assertRegex(self.board_cmake, r'PX4_BOARD_LABEL STREQUAL "simple" AND NOT NUTTX_CONFIG STREQUAL "simple"')
        self.assertRegex(self.board_cmake, r'CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250\s+OR\s+CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948')
        self.assertIn("rzv2h-simple-profile-contract-test.py", self.board_cmake)
        module = read("src/drivers/imu/invensense/icm20948/CMakeLists.txt")
        self.assertRegex(module, r"\bDEPENDS\b[\s\S]*\bdrivers__device\b")

    def test_gpio_irq_guard_precedes_all_pin_and_spi_setup(self):
        source = read(PROFILE + "src/init.c")
        initialize = body(source, "board_app_initialize")
        call = initialize.index("rdk_rzv2h_gpio_irq_initialize_once()")
        self.assertLess(initialize.index("px4_platform_init()"), call)
        self.assertLess(call, initialize.index("rdk_rzv2h_gpio_initialize()"))
        self.assertLess(call, initialize.index("board_spi_initialize()"))
        self.assertIn("CONFIG_RZV_GPIO_IRQ", source)
        pins = body(source, "rdk_rzv2h_gpio_initialize")
        self.assertIn("px4_arch_configgpio(BOARD_ICM20948_DRDY_GPIO | RZV_GPIO_PULLUP)", pins)


if __name__ == "__main__":
    unittest.main()
