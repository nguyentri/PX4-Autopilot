#!/usr/bin/env python3
"""Audit the resolved reference drone (CR8-0 default) firmware and execute its serial startup."""
import argparse
import importlib.util
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("payload_artifacts", ROOT / "test/rzv2h_payload_artifact_contract_test.py")
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


class DroneArtifacts(payload.PayloadArtifactContracts):
    def test_build_resolved_payload_nsh_cr8_0_contract(self):
        self.assertIn("PX4_BOARD_LABEL:STRING=default", self.cache)
        self.assertIn("NUTTX_CONFIG:INTERNAL=nsh", self.cache)
        self.assertIn("#define CONFIG_BOARD_PARAM_FILE_ATOMIC 1", self.board_config)
        self.assertEqual(self.nuttx.get("CONFIG_RZV2H_BUILD_CR8_0"), "y")
        self.assertIn("rdk-rzv2h_cr8_0.ld", self.link_map)
        self.assertEqual(self.nuttx.get("CONFIG_RZV2H_DRONE_SENSOR_EXTENSION"), "y")
        for flag in ("CONFIG_RZV_SPI0_DMA", "CONFIG_RZV2H_SPI0_HARDWARE_SSL",
                     "CONFIG_RZV2H_ICM20948_TEST", "CONFIG_RZV_IPC_RAW",
                     "CONFIG_RZV_IPC_IPCC", "CONFIG_RDK_RZV2H_XSPI_PARAMFS"):
            self.assertNotEqual(self.nuttx.get(flag), "y", flag)
        # OpenAMP carries only the CA55 XRCE-DDS link (rpmsg-service-1).
        for flag in ("CONFIG_RZV_OPENAMP", "CONFIG_RZV_RPMSG_UXRCE"):
            self.assertEqual(self.nuttx.get(flag), "y", flag)
        self.assertIn("uxrce_dds_client", self.builtins)
        for symbol in ("rzv_rpmsg_uxrce_register", "rzv_openamp_resource_table_init"):
            self.assertIn(symbol, self.symbols)
        self.assertEqual(self.nuttx.get("CONFIG_RDK_RZV2H_VOLATILE_PARAMFS"), "y")

    def test_selected_sensor_commands_are_linked_and_legacy_commands_absent(self):
        for command in ("icm45686", "bmm150", "bmp388", "ina228", "tfmini",
                        "gps", "mavlink", "rc_input", "pwm_out", "dshot", "commander", "sensors", "ekf2"):
            self.assertIn(command, self.builtins)
            self.assertIn(command + "_main", self.symbols)
        for command in ("mpu9250", "icm20948", "bmp280", "simulator_sih", "px4io_bridge"):
            self.assertNotIn(command, self.builtins)
        for symbol in ("px4_spi_buses", "px4_i2c_buses", "board_spi_configure_device_ids",
                       "rdk_rzv2h_configure_sensor_cs", "rzv_spi_select"):
            self.assertIn(symbol, self.symbols)
        self.assertIn("spi.cpp.obj", self.link_map)
        self.assertIn("i2c.cpp.obj", self.link_map)

    def test_linked_spi_table_has_three_unique_polled_devices(self):
        nm = shutil.which("arm-none-eabi-nm")
        dump = shutil.which("arm-none-eabi-objdump")
        if nm is None or dump is None:
            raise RuntimeError("ARM binutils required")
        symbols = subprocess.check_output([nm, "-S", "-g", str(self.elf_path)], text=True)
        match = re.search(r"^([0-9a-f]+) ([0-9a-f]+) \w px4_spi_buses$", symbols, re.M)
        self.assertIsNotNone(match)
        start, size = [int(value, 16) for value in match.groups()]
        output = subprocess.check_output([dump, "-s", "--start-address=" + str(start),
                                          "--stop-address=" + str(start + size), str(self.elf_path)], text=True)
        data = bytearray()
        for line in output.splitlines():
            fields = line.split()
            if fields and re.fullmatch(r"[0-9a-f]{8}", fields[0]):
                for field in fields[1:5]:
                    if re.fullmatch(r"(?:[0-9a-f]{2}){1,4}", field):
                        data.extend(bytes.fromhex(field))
                    else:
                        break
        self.assertEqual(len(data), size)
        pins = []
        # ELF is ARM32: the production public device struct is 16 bytes,
        # with uint32 CS, DRDY and device ID followed by uint16 driver type.
        for index in range(3):
            cs, drdy, devid, dtype = struct.unpack_from("<IIIH", data, index * 16)
            self.assertEqual(drdy, 0)
            self.assertEqual(devid, 0x10000034 + (index << 8))
            self.assertEqual(dtype, 0x34)
            self.assertNotEqual(cs, 0)
            pins.append(cs)
        self.assertEqual(len(set(pins)), 3)

    def test_profile_hooks_override_sensors_and_retain_safe_shared_defaults(self):
        generated = payload.BUILD_DIR / "etc/init.d"
        for name in ("rc.board_sensors", "rc.board_defaults.cmds"):
            # ROMFS strips comments/blank lines, so compare executable lines.
            source = (ROOT / "boards/renesas/rdk-rzv2h/init" / name).read_text()
            commands = [line.strip() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            self.assertEqual([line.strip() for line in (generated / name).read_text().splitlines() if line.strip()], commands)
        self.assertIn(". $RZV_DEFAULTS", self.defaults)
        self.assertIn("set RGBLED_PROBE no", self.defaults)
        self.assertIn("set PX4IO_CHECK no", self.defaults)
        self.assertIn("param set-default BAT1_SOURCE 0", (generated / "rc.board_defaults.cmds").read_text())

    def test_tfmini_metadata_and_generated_startup_resolve_ext2(self):
        tree = ET.parse(payload.BUILD_DIR / "parameters.xml")
        parameter = tree.find(".//parameter[@name='SENS_TFMINI_CFG']")
        self.assertIsNotNone(parameter)
        self.assertIsNotNone(parameter.find("values/value[@code='401']"))
        host = r'''
set() { local key="$1"; shift; printf -v "$key" '%s' "$*"; }
param() { [ "$1" = compare ] && [ "$2" = SENS_TFMINI_CFG ] && [ "$3" = 401 ]; }
tfmini() { echo "TFMINI $*"; }
'''
        result = subprocess.run(["bash", "-c", host + '\nR="$1/"\n. "${R}etc/init.d/rc.serial"',
                                 "host", str(payload.BUILD_DIR)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "TFMINI start -d /dev/ttyS4")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", default=str(ROOT / "build/renesas_rdk-rzv2h_default"))
    args, remaining = parser.parse_known_args()
    payload.BUILD_DIR = Path(args.build_dir).resolve()
    payload.CONFIG_NAME = "renesas_rdk-rzv2h_default"
    payload.BOARD_LABEL = "default"
    unittest.main(argv=[sys.argv[0]] + remaining)
