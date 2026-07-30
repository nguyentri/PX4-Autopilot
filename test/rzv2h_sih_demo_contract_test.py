#!/usr/bin/env python3
"""Source contracts for the RZ/V2H flight-controller SIH demonstration."""

from pathlib import Path
import re
from typing import Dict
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards/renesas/rdk-rzv2h"
ROMFS = ROOT / "ROMFS/rdk-rzv2h-sih"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def config_values(source: str) -> Dict[str, str]:
    values = {}  # type: Dict[str, str]

    for line in source.splitlines():
        stripped = line.strip()
        match = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(.+)", stripped)

        if match:
            values[match.group(1)] = match.group(2)
            continue

        match = re.fullmatch(r"# (CONFIG_[A-Z0-9_]+) is not set", stripped)

        if match:
            values[match.group(1)] = "n"

    return values


class SIHBoardContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = config_values(read(BOARD / "sih.px4board"))
        cls.nuttx = config_values(read(BOARD / "nuttx-config/sih/defconfig"))
        cls.romfs_cmake = read(ROMFS / "CMakeLists.txt")
        cls.init_cmake = read(ROMFS / "init.d/CMakeLists.txt")
        cls.rcs = read(ROMFS / "init.d/rcS")
        cls.rc_sysinit = read(ROMFS / "init.d/rc.sysinit")

    def test_target_has_matching_nuttx_config_and_compact_romfs(self) -> None:
        self.assertTrue((BOARD / "nuttx-config/sih/defconfig").is_file())
        self.assertEqual(
            self.overlay.get("CONFIG_BOARD_ROMFSROOT"),
            '"rdk-rzv2h-sih"',
        )
        self.assertTrue((ROMFS / "init.d/CMakeLists.txt").is_file())
        self.assertTrue((ROMFS / "init.d/rcS").is_file())
        self.assertTrue((ROMFS / "init.d/rc.sysinit").is_file())
        self.assertIn("rc.sysinit", self.init_cmake)
        board_cmake = read(BOARD / "src/CMakeLists.txt")
        self.assertIn("add_custom_target(rzv2h_sih_demo_contract_test", board_cmake)
        self.assertIn("test/rzv2h_sih_demo_contract_test.py", board_cmake)
        self.assertIn(
            'if(PX4_BOARD_LABEL STREQUAL "sih" AND NOT NUTTX_CONFIG STREQUAL "sih")',
            board_cmake,
        )
        self.assertIn("add_custom_target(rzv2h_sih_artifact_contract_test", board_cmake)
        self.assertIn("${PX4_BINARY_DIR}/${PX4_CONFIG}.px4", board_cmake)
        self.assertIsNotNone(
            re.search(
                r"add_custom_target\(rzv2h_sih_artifact_contract_test ALL.*?"
                r"DEPENDS.*?\$\{PX4_BINARY_DIR\}/\$\{PX4_CONFIG\}\.px4.*?"
                r"rzv2h_sih_demo_contract_test",
                board_cmake,
                re.DOTALL,
            )
        )

    def test_overlay_closes_inherited_physical_surfaces(self) -> None:
        expected = {
            "CONFIG_BOARD_HAS_RZV_SERIAL_ICOUNT": "n",
            "CONFIG_COMMON_SERIAL_PORT_MAPPING": "n",
            "CONFIG_I2C": "n",
            "CONFIG_SPI": "n",
            "CONFIG_UART": "n",
            "CONFIG_DRIVERS_BAROMETER": "n",
            "CONFIG_DRIVERS_BAROMETER_BMP280": "n",
            "CONFIG_DRIVERS_DSHOT": "n",
            "CONFIG_DRIVERS_GPS": "n",
            "CONFIG_DRIVERS_IMU": "n",
            "CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250": "n",
            "CONFIG_DRIVERS_MAGNETOMETER": "n",
            "CONFIG_DRIVERS_PWM_OUT": "n",
            "CONFIG_DRIVERS_RC_INPUT": "n",
            "CONFIG_DRIVERS_DISTANCE_SENSOR_TFMINI": "n",
            "CONFIG_MODULES_COMMANDER": "n",
            "CONFIG_MODULES_EKF2": "n",
            "CONFIG_MODULES_MAVLINK": "n",
            "CONFIG_MODULES_MC_ATT_CONTROL": "n",
            "CONFIG_MODULES_MC_POS_CONTROL": "n",
            "CONFIG_MODULES_MC_RATE_CONTROL": "n",
        }

        for symbol, value in expected.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.overlay.get(symbol), value)

        for serial_role in (
            "CONFIG_BOARD_SERIAL_GPS1",
            "CONFIG_BOARD_SERIAL_TEL1",
            "CONFIG_BOARD_SERIAL_RC",
            "CONFIG_BOARD_SERIAL_EXT2",
        ):
            with self.subTest(serial_role=serial_role):
                self.assertEqual(self.overlay.get(serial_role), '""')

    def test_overlay_enables_only_the_bounded_sih_sensor_path(self) -> None:
        required = {
            "CONFIG_MODULES_SIMULATION_SIMULATOR_SIH": "y",
            "CONFIG_MODULES_SIMULATION_SENSOR_AGP_SIM": "n",
            "CONFIG_MODULES_SENSORS": "y",
            "CONFIG_MODULES_CONTROL_ALLOCATOR": "y",
            "CONFIG_SENSORS_VEHICLE_AIRSPEED": "n",
            "CONFIG_SENSORS_VEHICLE_AIR_DATA": "y",
            "CONFIG_SENSORS_VEHICLE_ANGULAR_VELOCITY": "y",
            "CONFIG_SENSORS_VEHICLE_ACCELERATION": "y",
            "CONFIG_SENSORS_VEHICLE_GPS_POSITION": "y",
            "CONFIG_SENSORS_VEHICLE_MAGNETOMETER": "y",
            "CONFIG_SENSORS_VEHICLE_OPTICAL_FLOW": "n",
        }

        for symbol, value in required.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.overlay.get(symbol), value)

    def test_nuttx_profile_keeps_hrt_but_excludes_physical_io(self) -> None:
        required = {
            "CONFIG_RZV2H_BUILD_CR8_0": "y",
            "CONFIG_RZV2H_EXAMPLE_SUPPORT": "n",
            "CONFIG_RZV_HRT": "y",
            "CONFIG_RDK_RZV2H_VOLATILE_PARAMFS": "y",
            "CONFIG_FS_ROMFS": "y",
            "CONFIG_FS_TMPFS": "y",
            "CONFIG_NSH_LINELEN": "128",
            "CONFIG_SYSLOG_RTT": "y",
            "CONFIG_STACK_COLORATION": "y",
        }

        for symbol, value in required.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.nuttx.get(symbol), value)

        forbidden = (
            "CONFIG_PWM",
            "CONFIG_RZV_GPT",
            "CONFIG_RZV_GPT6",
            "CONFIG_RZV_GPT7",
            "CONFIG_RZV_GPT9",
            "CONFIG_RZV_GPT10",
            "CONFIG_RZV_SPI",
            "CONFIG_RZV_SCI_I2C",
            "CONFIG_RZV_DMAC",
            "CONFIG_RZV_OPENAMP",
        )

        for symbol in forbidden:
            with self.subTest(symbol=symbol):
                self.assertNotEqual(self.nuttx.get(symbol), "y")

    def test_shell_console_routes_to_sci4_with_rtt_diagnostics(self) -> None:
        required = {
            "CONFIG_RZV_SCI4": "y",
            "CONFIG_SCI4_SERIAL_CONSOLE": "y",
            "CONFIG_RZV_SCI_FIFO_MODE": "y",
            "CONFIG_SYSLOG_RTT": "y",
        }

        for symbol, value in required.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.nuttx.get(symbol), value)

        # The shell must own SCI4; RTT stays output-only for logs, so the
        # RTT-console and console-to-syslog redirects must be absent.
        for absent in (
            "CONFIG_NO_SERIAL_CONSOLE",
            "CONFIG_SYSLOG_RTT_CONSOLE_INPUT",
            "CONFIG_CONSOLE_SYSLOG",
        ):
            with self.subTest(absent=absent):
                self.assertIsNone(self.nuttx.get(absent))

    def test_sci_uart_channels_are_chip_capability_gated(self) -> None:
        rzv_kconfig = read(
            ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig"
        )

        for channel in range(10):
            with self.subTest(channel=channel):
                self.assertIn(
                    "select RZV_HAVE_SCI{0}".format(channel),
                    rzv_kconfig,
                )
                self.assertIsNotNone(
                    re.search(
                        r"config RZV_SCI{0}\n"
                        r"(?:.*\n){{0,4}}"
                        r"\s+depends on RZV_HAVE_SCI{0}\n".format(channel),
                        rzv_kconfig,
                    )
                )

    def test_romfs_excludes_physical_board_hooks(self) -> None:
        self.assertIn(
            "set(config_romfs_include_board_init false PARENT_SCOPE)",
            self.romfs_cmake,
        )
        self.assertIn("add_subdirectory(init.d)", self.romfs_cmake)

        for board_hook in (
            "rc.board_defaults",
            "rc.board_defaults.cmds",
            "rc.board_sensors",
        ):
            with self.subTest(board_hook=board_hook):
                self.assertNotIn(board_hook, self.rcs)

    def test_startup_uses_only_available_fc_sih_commands(self) -> None:
        required_commands = (
            ". /etc/init.d/rc.filepaths",
            "param select $PARAM_FILE",
            "param set SYS_HITL 2 fail",
            "param set SIH_VEHICLE_TYPE 0 fail",
            "sensors start -h",
            "simulator_sih start",
            "sensor_baro_sim start",
            "sensor_mag_sim start",
            "sensor_gps_sim start",
            "pwm_out_sim start -m hil",
            "work_queue status",
        )

        for command in required_commands:
            with self.subTest(command=command):
                self.assertIn(command, self.rcs)

        forbidden_commands = (
            "sensor_agp_sim",
            "bmp280 start",
            "mpu9250 start",
            "gps start",
            "rc_input start",
            "tfmini start",
            "\npwm_out start",
            "\ndshot start",
            "control_allocator start",
            "commander start",
        )

        for command in forbidden_commands:
            with self.subTest(command=command):
                self.assertNotIn(command, self.rcs)

        self.assertIn("if [ $sih_params_valid = 1 ]", self.rcs)
        self.assertIn(
            "ERROR [init] mandatory SIH parameter setup failed; simulators not started",
            self.rcs,
        )

    def test_nsh_scripts_fit_the_configured_line_buffer(self) -> None:
        line_length = int(self.nuttx["CONFIG_NSH_LINELEN"])

        for script_name, script in (
            ("rc.sysinit", self.rc_sysinit),
            ("rcS", self.rcs),
        ):
            for line_number, line in enumerate(script.splitlines(), 1):
                with self.subTest(
                    script=script_name,
                    line_number=line_number,
                ):
                    self.assertLess(
                        len(line) + 1,
                        line_length,
                        "NSH fgets would split this script line",
                    )

    def test_board_init_keeps_physical_timer_setup_driver_gated(self) -> None:
        board_init = read(BOARD / "src/init.c")
        self.assertIsNotNone(
            re.search(
                r"#if defined\(CONFIG_DRIVERS_PWM_OUT\) \|\| "
                r"defined\(CONFIG_DRIVERS_DSHOT\).*?"
                r"rdk_rzv2h_timer_initialize\(\);.*?#endif",
                board_init,
                re.DOTALL,
            )
        )

    def test_sih_modules_declare_their_direct_library_dependencies(self) -> None:
        sensor_mag_cmake = read(
            ROOT / "src/modules/simulation/sensor_mag_sim/CMakeLists.txt"
        )
        simulator_sih_cmake = read(
            ROOT / "src/modules/simulation/simulator_sih/CMakeLists.txt"
        )
        self.assertIn("world_magnetic_model", sensor_mag_cmake)
        self.assertIn("lat_lon_alt", simulator_sih_cmake)


if __name__ == "__main__":
    unittest.main()
