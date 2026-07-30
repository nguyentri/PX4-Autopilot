#!/usr/bin/env python3
"""Post-build contracts for the RZ/V2H FC-SIH firmware artifacts."""

import argparse
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Dict, Set
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = ROOT / "build/renesas_rdk-rzv2h_sih"
BUILD_DIR = DEFAULT_BUILD_DIR


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def executable_script_lines(source: str):
    return [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


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


def board_defines(source: str) -> Set[str]:
    return set(
        match.group(1)
        for match in re.finditer(r"^#define (CONFIG_[A-Z0-9_]+)(?: .*)?$", source, re.MULTILINE)
    )


def elf_symbols(elf: Path) -> Set[str]:
    nm = shutil.which("arm-none-eabi-nm")

    if nm is None:
        raise RuntimeError("arm-none-eabi-nm is required for the SIH artifact audit")

    result = subprocess.run(
        [nm, "-g", str(elf)],
        check=True,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    return set(line.split()[-1] for line in result.stdout.splitlines() if line.split())


class SIHArtifactContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cache_path = BUILD_DIR / "CMakeCache.txt"
        cls.board_config_path = BUILD_DIR / "px4_boardconfig.h"
        cls.nuttx_config_path = BUILD_DIR / "NuttX/nuttx/.config"
        cls.elf_path = BUILD_DIR / "renesas_rdk-rzv2h_sih.elf"
        cls.map_path = BUILD_DIR / "renesas_rdk-rzv2h_sih.map"
        cls.bin_path = BUILD_DIR / "renesas_rdk-rzv2h_sih.bin"
        cls.package_path = BUILD_DIR / "renesas_rdk-rzv2h_sih.px4"
        cls.build_ninja_path = BUILD_DIR / "build.ninja"
        cls.builtins_path = BUILD_DIR / "NuttX/px4.bdat"
        cls.romfs_image_path = BUILD_DIR / "ROMFS/romfs.img"
        cls.romfs_listing_path = BUILD_DIR / "ROMFS/romfs.txt"
        cls.generated_rcs_path = BUILD_DIR / "etc/init.d/rcS"
        cls.source_rcs_path = ROOT / "ROMFS/rdk-rzv2h-sih/init.d/rcS"
        cls.generated_sysinit_path = BUILD_DIR / "etc/init.d/rc.sysinit"
        cls.source_sysinit_path = (
            ROOT / "ROMFS/rdk-rzv2h-sih/init.d/rc.sysinit"
        )
        cls.parts = [
            BUILD_DIR / ("renesas_rdk-rzv2h_sih" + suffix)
            for suffix in (
                "_header.bin",
                "_itcm.bin",
                "_sram.bin",
                "_sdram.bin",
            )
        ]

        for path in (
            cls.cache_path,
            cls.board_config_path,
            cls.nuttx_config_path,
            cls.elf_path,
            cls.map_path,
            cls.bin_path,
            cls.package_path,
            cls.build_ninja_path,
            cls.builtins_path,
            cls.romfs_image_path,
            cls.romfs_listing_path,
            cls.generated_rcs_path,
            cls.source_rcs_path,
            cls.generated_sysinit_path,
            cls.source_sysinit_path,
            *cls.parts,
        ):
            if not path.is_file():
                raise RuntimeError("missing SIH build artifact: {0}".format(path))

        cls.cache = read(cls.cache_path)
        cls.build_ninja = read(cls.build_ninja_path)
        cls.builtins = read(cls.builtins_path)
        cls.board_config = read(cls.board_config_path)
        cls.nuttx = config_values(read(cls.nuttx_config_path))
        cls.symbols = elf_symbols(cls.elf_path)
        cls.link_map = read(cls.map_path)
        cls.romfs_listing = read(cls.romfs_listing_path)
        cls.generated_rcs = read(cls.generated_rcs_path)
        cls.generated_sysinit = read(cls.generated_sysinit_path)

    def test_build_resolved_the_exact_sih_label_and_nuttx_profile(self) -> None:
        self.assertIn("PX4_BOARD_LABEL:STRING=sih", self.cache)
        self.assertIn("NUTTX_CONFIG:INTERNAL=sih", self.cache)
        self.assertNotIn("NUTTX_CONFIG:INTERNAL=nsh", self.cache)

    def test_resolved_px4_config_is_simulation_only(self) -> None:
        defines = board_defines(self.board_config)
        required = {
            "CONFIG_MODULES_CONTROL_ALLOCATOR",
            "CONFIG_MODULES_SENSORS",
            "CONFIG_MODULES_SIMULATION_PWM_OUT_SIM",
            "CONFIG_MODULES_SIMULATION_SENSOR_BARO_SIM",
            "CONFIG_MODULES_SIMULATION_SENSOR_GPS_SIM",
            "CONFIG_MODULES_SIMULATION_SENSOR_MAG_SIM",
            "CONFIG_MODULES_SIMULATION_SIMULATOR_SIH",
            "CONFIG_SYSTEMCMDS_SYSTEM_TIME",
            "CONFIG_SYSTEMCMDS_TOP",
            "CONFIG_SYSTEMCMDS_TOPIC_LISTENER",
            "CONFIG_SYSTEMCMDS_UORB",
            "CONFIG_SYSTEMCMDS_WORK_QUEUE",
        }
        forbidden = {
            "CONFIG_I2C",
            "CONFIG_SPI",
            "CONFIG_UART",
            "CONFIG_DRIVERS_BAROMETER",
            "CONFIG_DRIVERS_DSHOT",
            "CONFIG_DRIVERS_GPS",
            "CONFIG_DRIVERS_IMU",
            "CONFIG_DRIVERS_MAGNETOMETER",
            "CONFIG_DRIVERS_PWM_OUT",
            "CONFIG_DRIVERS_RC_INPUT",
            "CONFIG_MODULES_COMMANDER",
            "CONFIG_MODULES_DATAMAN",
            "CONFIG_MODULES_EKF2",
            "CONFIG_MODULES_MAVLINK",
            "CONFIG_MODULES_MC_ATT_CONTROL",
            "CONFIG_MODULES_MC_POS_CONTROL",
            "CONFIG_MODULES_MC_RATE_CONTROL",
        }
        self.assertFalse(required - defines)
        self.assertFalse(forbidden & defines)

    def test_resolved_nuttx_config_has_no_active_physical_surface(self) -> None:
        required = {
            "CONFIG_RZV2H_BUILD_CR8_0": "y",
            "CONFIG_RZV2H_EXAMPLE_SUPPORT": "n",
            "CONFIG_RZV_HRT": "y",
            "CONFIG_FS_PROCFS": "y",
            "CONFIG_FS_ROMFS": "y",
            "CONFIG_FS_TMPFS": "y",
            "CONFIG_SCHED_HPWORK": "y",
            "CONFIG_SCHED_LPWORK": "y",
            "CONFIG_SCHED_WORKQUEUE": "y",
            "CONFIG_STACK_COLORATION": "y",
            "CONFIG_SYSLOG_RTT": "y",
        }

        for symbol, value in required.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.nuttx.get(symbol), value)

        forbidden = {
            "CONFIG_I2C",
            "CONFIG_SPI",
            "CONFIG_UART",
            "CONFIG_PWM",
            "CONFIG_MTD",
            "CONFIG_MMCSD",
            "CONFIG_OPENAMP",
            "CONFIG_RPMSG",
            "CONFIG_FS_LITTLEFS",
            "CONFIG_FS_SMARTFS",
        }
        active_physical_prefix = re.compile(
            r"^CONFIG_RZV_(SCI|SCIF|RIIC|RSPI|SPI|I2C|GPT|DMAC|IPC|OPENAMP|XSPI)"
        )
        # SCI4 (P70/P71) is the one intentionally active serial peripheral: it
        # carries the interactive shell, mirroring the standalone nsh-rtt
        # routing. Its enabling symbols are exempt from the physical-surface
        # ban; every other SCI channel, SCIF, RIIC, RSPI, SPI, I2C, GPT, DMAC,
        # IPC, OpenAMP, and XSPI stays disabled.
        console_serial_allowlist = {
            "CONFIG_RZV_SCI4",
            "CONFIG_RZV_SCI_FIFO_MODE",
            "CONFIG_RZV_SCI_FIFO_RX_TRIGGER",
            "CONFIG_RZV_SCI_FIFO_TX_TRIGGER",
            "CONFIG_RZV_SCI_BITRATE_MODULATION",
        }

        for symbol, value in self.nuttx.items():
            if value != "y":
                continue

            if symbol in console_serial_allowlist:
                continue

            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, forbidden)
                self.assertIsNone(active_physical_prefix.match(symbol))

    def test_shell_console_runs_on_sci4_with_rtt_diagnostics(self) -> None:
        self.assertEqual(self.nuttx.get("CONFIG_RZV_SCI4"), "y")
        self.assertEqual(self.nuttx.get("CONFIG_SCI4_SERIAL_CONSOLE"), "y")
        self.assertEqual(self.nuttx.get("CONFIG_SYSLOG_RTT"), "y")
        self.assertNotEqual(self.nuttx.get("CONFIG_NO_SERIAL_CONSOLE"), "y")
        self.assertNotEqual(self.nuttx.get("CONFIG_SYSLOG_RTT_CONSOLE_INPUT"), "y")

    def test_elf_has_exact_simulator_allowlist_and_physical_denylist(self) -> None:
        required = {
            "control_allocator_main",
            "pwm_out_sim_main",
            "sensor_baro_sim_main",
            "sensor_gps_sim_main",
            "sensor_mag_sim_main",
            "sensors_main",
            "simulator_sih_main",
        }
        forbidden = {
            "bmp280_main",
            "dshot_main",
            "gps_main",
            "mpu9250_main",
            "pwm_out_main",
            "rc_input_main",
            "tfmini_main",
        }
        self.assertFalse(required - self.symbols)
        self.assertFalse(forbidden & self.symbols)
        self.assertIn(
            "src/lib/world_magnetic_model/libworld_magnetic_model.a",
            self.link_map,
        )
        self.assertIn("src/lib/lat_lon_alt/liblat_lon_alt.a", self.link_map)

    def test_romfs_is_generated_from_the_board_tree(self) -> None:
        image_size = self.romfs_image_path.stat().st_size
        self.assertNotEqual(image_size, 1024)
        self.assertIn("ROMFS/libromfs.a(nsh_romfsimg.c.obj)", self.link_map)

        romfs_symbol = re.search(
            r"^[0-9a-fA-F]+ ([0-9a-fA-F]+) [A-Za-z] romfs_img$",
            subprocess.check_output(
                ["arm-none-eabi-nm", "-S", str(self.elf_path)],
                universal_newlines=True,
            ),
            re.MULTILINE,
        )
        self.assertIsNotNone(romfs_symbol)
        self.assertEqual(int(romfs_symbol.group(1), 16), image_size)
        self.assertEqual(
            self.source_rcs_path.read_bytes(),
            self.generated_rcs_path.read_bytes(),
        )
        self.assertEqual(
            executable_script_lines(read(self.source_sysinit_path)),
            executable_script_lines(self.generated_sysinit),
        )
        self.assertIn("rc.sysinit", self.romfs_listing)

        for forbidden_entry in (
            "mkfatfs",
            "mmcsd",
            "rc.board_defaults",
            "rc.board_sensors",
        ):
            with self.subTest(forbidden_entry=forbidden_entry):
                self.assertNotIn(forbidden_entry, self.romfs_listing)
                self.assertNotIn(forbidden_entry, self.generated_rcs)

    def test_packed_startup_is_fail_closed_and_simulation_only(self) -> None:
        required = (
            ". /etc/init.d/rc.filepaths",
            "param select $PARAM_FILE",
            "param set SYS_HITL 2 fail",
            "param set SIH_VEHICLE_TYPE 0 fail",
            "if [ $sih_params_valid = 1 ]",
            "sensors start -h",
            "simulator_sih start",
            "sensor_baro_sim start",
            "sensor_mag_sim start",
            "sensor_gps_sim start",
            "pwm_out_sim start -m hil",
        )
        forbidden = (
            "control_allocator start",
            "pwm_out start",
            "dshot start",
            "bmp280 start",
            "mpu9250 start",
            "gps start",
            "rc_input start",
            "tfmini start",
        )

        for command in required:
            with self.subTest(command=command):
                self.assertIn(command, self.generated_rcs)

        for command in forbidden:
            with self.subTest(command=command):
                self.assertNotIn(command, self.generated_rcs)

    def test_packed_scripts_fit_the_resolved_nsh_line_buffer(self) -> None:
        line_length = int(self.nuttx["CONFIG_NSH_LINELEN"])

        for script_name, script in (
            ("rc.sysinit", self.generated_sysinit),
            ("rcS", self.generated_rcs),
        ):
            for line_number, line in enumerate(script.splitlines(), 1):
                with self.subTest(
                    script=script_name,
                    line_number=line_number,
                ):
                    self.assertLess(
                        len(line) + 1,
                        line_length,
                        "NSH fgets would split this packed script line",
                    )

    def test_split_image_and_package_payload_equal_the_binary(self) -> None:
        image = self.bin_path.read_bytes()
        split_image = b"".join(path.read_bytes() for path in self.parts)
        self.assertEqual(split_image, image)

        package = json.loads(read(self.package_path))
        payload = zlib.decompress(base64.b64decode(package["image"]))
        self.assertEqual(payload, image)
        self.assertEqual(package["image_size"], len(image))
        self.assertLessEqual(len(image), package["image_maxsize"])

    def test_elf_has_no_undefined_global_symbols(self) -> None:
        nm = shutil.which("arm-none-eabi-nm")
        output = subprocess.check_output([nm, "-u", str(self.elf_path)], text=True)
        self.assertEqual(output.strip(), "")

    def test_cr8_0_linker_entry_and_runtime_symbols_are_resolved(self) -> None:
        self.assertIn("rdk-rzv2h_cr8_0.ld", self.build_ninja)
        self.assertIn("-Wl,--entry=__start", self.build_ninja)

        readelf = shutil.which("arm-none-eabi-readelf")

        if readelf is None:
            raise RuntimeError(
                "arm-none-eabi-readelf is required for the SIH artifact audit"
            )

        header = subprocess.check_output(
            [readelf, "-h", str(self.elf_path)],
            text=True,
        )
        self.assertRegex(header, r"Entry point address:\s+0x40800000\b")

        required = {
            "__start",
            "board_app_initialize",
            "hrt_absolute_time",
            "nsh_main",
            "rzv_hrt_initialize",
            "uorb_main",
            "work_queue_main",
        }
        self.assertFalse(required - self.symbols)

    def test_packed_startup_commands_are_registered_builtins(self) -> None:
        registered = set(
            re.findall(r'^\{ "([^"]+)",', self.builtins, re.MULTILINE)
        )
        required = {
            "param",
            "pwm_out_sim",
            "sensor_baro_sim",
            "sensor_gps_sim",
            "sensor_mag_sim",
            "sensors",
            "simulator_sih",
            "work_queue",
        }
        diagnostics = {
            "dmesg",
            "listener",
            "perf",
            "system_time",
            "top",
            "uorb",
            "ver",
        }
        self.assertFalse((required | diagnostics) - registered)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-dir",
        default=str(DEFAULT_BUILD_DIR),
        help="Configured renesas_rdk-rzv2h_sih build directory",
    )
    return parser.parse_known_args()


if __name__ == "__main__":
    parsed, unittest_args = parse_args()
    BUILD_DIR = Path(parsed.build_dir).resolve()
    unittest.main(argv=[sys.argv[0]] + unittest_args)
