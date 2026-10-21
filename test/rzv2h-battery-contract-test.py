#!/usr/bin/env python3
"""Exercise production battery assembly/freshness and independent wire goldens."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class BatteryContract(unittest.TestCase):
    def test_production_receiver_and_wire_records(self):
        with tempfile.TemporaryDirectory(prefix='rzv2h-battery-') as directory:
            binary = Path(directory) / 'battery'
            subprocess.run([
                'g++', '-std=c++14', '-O1', '-g', '-Wall', '-Wextra', '-Wshadow', '-Werror',
                '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I', str(ROOT / 'src'),
                str(ROOT / 'test/rzv2h-battery-host-fixture.cpp'),
                str(ROOT / 'src/apps/battery.cpp'), str(ROOT / 'src/apps/protocol.cpp'),
                '-o', str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)
            for kind, payload, option in (
                (0x12, struct.pack('<HHIIIiHBBHHI', 3, 31, 1, 100, 16000, -1234, 800, 20, 4, 7, 0, 0), '--base'),
                (0x14, struct.pack('<HHIIhHHHIII', 3, 31, 1, 200, -1234, 3990, 4010, 0, 8000, 10000, 0), '--detail'),
            ):
                with self.subTest(kind=kind):
                    expected = bytearray(struct.pack('<I4B2BHIIQI', 0x525A5632, 3, 0, kind, 64,
                                                     1, 0, 0, 1, 7, 2**64-1, 0) + payload)
                    struct.pack_into('<I', expected, 28, zlib.crc32(expected))
                    self.assertEqual(bytes.fromhex(subprocess.check_output([str(binary), option], text=True)), expected)


if __name__ == '__main__':
    unittest.main()
