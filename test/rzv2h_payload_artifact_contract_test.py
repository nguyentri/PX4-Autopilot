#!/usr/bin/env python3
"""Post-build contracts for the RZ/V2H CR8-0 payload firmware."""

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
DEFAULT_BUILD_DIR = ROOT / "build/renesas_rdk-rzv2h_default"
BUILD_DIR = DEFAULT_BUILD_DIR
CONFIG_NAME = "renesas_rdk-rzv2h_default"
BOARD_LABEL = "default"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def config_values(source: str) -> Dict[str, str]:
    values = {}  # type: Dict[str, str]

    for line in source.splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(.+)", line.strip())

        if match:
            values[match.group(1)] = match.group(2)
            continue

        match = re.fullmatch(
            r"# (CONFIG_[A-Z0-9_]+) is not set", line.strip()
        )

        if match:
            values[match.group(1)] = "n"

    return values


def elf_symbols(elf: Path) -> Set[str]:
    nm = shutil.which("arm-none-eabi-nm")

    if nm is None:
        raise RuntimeError("arm-none-eabi-nm is required")

    output = subprocess.check_output([nm, "-g", str(elf)], text=True)
    return set(line.split()[-1] for line in output.splitlines() if line.split())


class PayloadArtifactContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.name = CONFIG_NAME
        cls.cache_path = BUILD_DIR / "CMakeCache.txt"
        cls.nuttx_config_path = BUILD_DIR / "NuttX/nuttx/.config"
        cls.board_config_path = BUILD_DIR / "px4_boardconfig.h"
        cls.builtins_path = BUILD_DIR / "NuttX/px4.bdat"
        cls.elf_path = BUILD_DIR / (cls.name + ".elf")
        cls.map_path = BUILD_DIR / (cls.name + ".map")
        cls.bin_path = BUILD_DIR / (cls.name + ".bin")
        cls.package_path = BUILD_DIR / (cls.name + ".px4")
        cls.rcs_path = BUILD_DIR / "etc/init.d/rcS"
        cls.defaults_path = BUILD_DIR / "etc/init.d/rc.board_defaults"

        cls.parts = [
            BUILD_DIR / (cls.name + suffix)
            for suffix in (
                "_header.bin",
                "_itcm.bin",
                "_sram.bin",
                "_sdram.bin",
            )
        ]

        for path in (
            cls.cache_path,
            cls.nuttx_config_path,
            cls.board_config_path,
            cls.builtins_path,
            cls.elf_path,
            cls.map_path,
            cls.bin_path,
            cls.package_path,
            cls.rcs_path,
            cls.defaults_path,
            *cls.parts,
        ):
            if not path.is_file():
                raise RuntimeError("missing payload build artifact: {0}".format(path))

        cls.cache = read(cls.cache_path)
        cls.nuttx = config_values(read(cls.nuttx_config_path))
        cls.board_config = read(cls.board_config_path)
        cls.builtins = set(
            re.findall(r'^\{ "([^"]+)"', read(cls.builtins_path), re.MULTILINE)
        )
        cls.symbols = elf_symbols(cls.elf_path)
        cls.link_map = read(cls.map_path)
        cls.rcs = read(cls.rcs_path)
        cls.defaults = read(cls.defaults_path)

    def test_build_resolved_payload_nsh_cr8_0_contract(self) -> None:
        self.assertIn(
            "PX4_BOARD_LABEL:STRING={0}".format(BOARD_LABEL),
            self.cache,
        )
        self.assertIn("NUTTX_CONFIG:INTERNAL=nsh", self.cache)
        self.assertEqual(self.nuttx.get("CONFIG_RZV2H_BUILD_CR8_0"), "y")
        self.assertIn("rdk-rzv2h_cr8_0.ld", self.link_map)

    def test_required_startup_commands_and_real_pipes_are_resolved(self) -> None:
        for command in ("bsondump", "mft"):
            with self.subTest(command=command):
                self.assertIn(command, self.builtins)
                self.assertIn(command + "_main", self.symbols)

        self.assertEqual(self.nuttx.get("CONFIG_PIPES"), "y")
        self.assertGreater(int(self.nuttx["CONFIG_DEV_PIPE_SIZE"]), 0)
        self.assertEqual(self.nuttx.get("CONFIG_DEV_FIFO_SIZE"), "0")
        self.assertIn("NuttX/nuttx/libs/libc/libc.a(lib_pipe.o)", self.link_map)
        self.assertIn("pipe", self.symbols)

    def test_absent_hardware_commands_are_capability_gated(self) -> None:
        for command in (
            "rgbled",
            "rgbled_ncp5623c",
            "rgbled_lp5562",
            "rgbled_is31fl3195",
            "px4io",
        ):
            with self.subTest(command=command):
                self.assertNotIn(command, self.builtins)

        self.assertIn("if [ $RGBLED_PROBE = yes ]", self.rcs)
        self.assertIn("if [ $PX4IO_CHECK = yes ]", self.rcs)
        self.assertIn("set RGBLED_PROBE no", self.defaults)
        self.assertIn("set PX4IO_CHECK no", self.defaults)

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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-dir",
        default=str(DEFAULT_BUILD_DIR),
        help="Configured RZ/V2H payload build directory",
    )
    parser.add_argument(
        "--config-name",
        default=CONFIG_NAME,
        help="PX4 artifact stem",
    )
    parser.add_argument(
        "--board-label",
        default=BOARD_LABEL,
        help="Expected PX4 board label",
    )
    return parser.parse_known_args()


if __name__ == "__main__":
    parsed, unittest_args = parse_args()
    BUILD_DIR = Path(parsed.build_dir).resolve()
    CONFIG_NAME = parsed.config_name
    BOARD_LABEL = parsed.board_label
    unittest.main(argv=[sys.argv[0]] + unittest_args)
