#!/usr/bin/env python3
"""Exercise real single-ray serialization through the private gateway validator."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PerceptionAdapter(unittest.TestCase):
    def test_qualified_ray_unknown_sectors_and_gateway_boundary(self):
        with tempfile.TemporaryDirectory(prefix='rzv2h-perception-') as directory:
            binary = Path(directory) / 'perception'
            subprocess.run([
                'g++', '-std=c++14', '-O1', '-g', '-Wall', '-Wextra', '-Wshadow', '-Werror',
                '-ffinite-math-only', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                '-I', str(ROOT / 'src'), str(ROOT / 'test/rzv2h-perception-adapter-host-fixture.cpp'),
                str(ROOT / 'src/apps/perception.cpp'), str(ROOT / 'src/apps/gateway.cpp'),
                str(ROOT / 'src/apps/protocol.cpp'), '-o', str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
