#!/usr/bin/env python3
"""Compile the production v3 codec and compare its bytes with an independent encoder."""

from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class DemoProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="rzv2h-protocol-")
        cls.binary = Path(cls.scratch.name) / "protocol-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT / "src"), "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-protocol-host-fixture.cpp"),
            str(ROOT / "src/apps/protocol.cpp"), "-o", str(cls.binary),
        ], check=True)
        cls.lease_binary = Path(cls.scratch.name) / "output-lease-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT / "src"), "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-output-lease-host-fixture.cpp"),
            str(ROOT / "src/apps/protocol.cpp"),
            str(ROOT / "src/apps/actuator-lease.cpp"), "-o", str(cls.lease_binary),
        ], check=True)
        cls.snapshot_binary = Path(cls.scratch.name) / "output-snapshot-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I", str(ROOT / "src"), "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-output-snapshot-host-fixture.cpp"), "-o", str(cls.snapshot_binary),
        ], check=True)

        cls.worker_binary = Path(cls.scratch.name) / "output-worker-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT / "src"), "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-output-worker-host-fixture.cpp"),
            str(ROOT / "src/apps/protocol.cpp"), "-o", str(cls.worker_binary),
        ], check=True)

        cls.configuration_binary = Path(cls.scratch.name) / "output-configuration-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT / "src"),
            "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-output-configuration-host-fixture.cpp"),
            str(ROOT / "src/apps/protocol.cpp"),
            str(ROOT / "src/apps/actuator-lease.cpp"), "-o", str(cls.configuration_binary),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_boundaries_corruption_and_malformed_frames(self):
        subprocess.run([str(self.binary)], check=True)

    def test_causal_output_lease_and_inhibition(self):
        subprocess.run([str(self.lease_binary)], check=True)

    def test_snapshot_interleavings_and_source_progress(self):
        subprocess.run([str(self.snapshot_binary)], check=True)

    def test_producer_progress_and_independent_worker_fault_latch(self):
        subprocess.run([str(self.worker_binary)], check=True)

    def test_legacy_protocol_headers_remain_c_compatible(self):
        headers = (
            "boards/renesas/rdk-rzv2h/rzv2h_outputs/protocol.h",
            "boards/renesas/rdk-rzv2h-io-cr8_1/rzv2h_io/protocol.h",
            "boards/renesas/rdk-rzv2h-io-cm33/px4io_m33/protocol.h",
        )
        for index, header in enumerate(headers):
            with self.subTest(header=header):
                source = Path(self.scratch.name) / f"legacy-{index}.c"
                source.write_text('#include "' + header + '"\n' +
                                  '_Static_assert(IPC_PROTOCOL_VERSION == 2, "legacy version");\n' +
                                  'int main(void) { return 0; }\n')
                subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                                str(source), "-o", str(source.with_suffix(""))], check=True)

    def test_profile_binding_and_receiver_endpoint_guards(self):
        subprocess.run([str(self.configuration_binary)], check=True)

    def test_delayed_fault_bounds_parser_and_one_shot_concurrency(self):
        binary = Path(self.scratch.name) / "bench-fault-test"
        subprocess.run([
            "g++", "-std=c++14", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I", str(ROOT / "src"),
            "-I", str(ROOT / "platforms/common/include"),
            str(ROOT / "test/rzv2h-demo-bench-fault-host-fixture.cpp"), "-o", str(binary),
        ], check=True)
        subprocess.run([str(binary)], check=True)

    def test_wire_bytes_match_independent_little_endian_crc_encoder(self):
        timestamp = 0x1020304050607080
        header = struct.pack("<I4B2BHIIQI", 0x525A5632, 3, 0, 1, 64,
                             0, 0, 0, 0x01020304, 7, timestamp, 0)
        payload = struct.pack("<IIQ4HHHI", 9, 2, timestamp - 10, 1000, 1200, 0, 2000, 3, 400, 3)
        expected = bytearray(header + payload)
        struct.pack_into("<I", expected, 28, zlib.crc32(expected))
        actual = bytes.fromhex(subprocess.check_output([str(self.binary), "--golden"], text=True))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 64)


if __name__ == "__main__":
    unittest.main()
