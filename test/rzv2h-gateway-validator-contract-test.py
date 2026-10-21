#!/usr/bin/env python3
"""Compile production private-ingress validation; no transport or timing qualification."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


class GatewayContract(unittest.TestCase):
    def test_real_validator_boundaries_and_faults(self):
        with tempfile.TemporaryDirectory(prefix='rzv2h-gateway-') as temporary:
            binary = Path(temporary)/'gateway'
            subprocess.run([
                'g++', '-std=c++14', '-O1', '-g', '-Wall', '-Wextra', '-Wshadow', '-Werror',
                '-ffinite-math-only', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                '-I', str(ROOT/'src'), str(ROOT/'test/rzv2h-gateway-validator-host-fixture.cpp'),
                str(ROOT/'src/apps/gateway.cpp'), str(ROOT/'src/apps/protocol.cpp'),
                '-o', str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)
            expected = bytearray(97)
            struct.pack_into('<I4BHHIQ', expected, 0, 0x31475a52, 1, 0, 1, 96, 97, 0, 1, 1)
            for offset, value in ((32, 1), (40, 500000), (80, 9)):
                struct.pack_into('<Q', expected, offset, value)
            for offset, value in ((48, 100), (52, 101), (56, 303), (60, 1), (88, 1)):
                struct.pack_into('<I', expected, offset, value)
            struct.pack_into('<4I', expected, 64, 1, 2, 3, 4)
            expected[96] = 1
            struct.pack_into('<I', expected, 28, zlib.crc32(expected))
            self.assertEqual(bytes.fromhex(subprocess.check_output([str(binary), '--golden'], text=True)), expected)


if __name__ == '__main__':
    unittest.main()
