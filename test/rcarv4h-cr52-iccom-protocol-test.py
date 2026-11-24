#!/usr/bin/env python3
"""Compile the R-Car V4H CR52-0 ICCOM protocol engine on the host and run
it against a simulated MFIS register pair, CTA and CA76 peer."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RCAR = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rcar'
FIXTURE = Path(__file__).with_name('rcarv4h-cr52-iccom-host-fixture.c')


class IccomProtocolTest(unittest.TestCase):
    def test_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'iccom'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(RCAR), str(FIXTURE),
                            str(RCAR / 'rcar_iccom_proto.c'), '-o', str(exe)],
                           check=True, timeout=60)
            result = subprocess.run([str(exe)], timeout=30,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r'^PASS \d+ cases')

    def test_engine_has_no_nuttx_dependency(self):
        for name in ('rcar_iccom_proto.c', 'rcar_iccom_proto.h'):
            text = (RCAR / name).read_text()
            includes = re.findall(r'^#include\s+[<"]([^>"]+)', text, re.M)
            for inc in includes:
                self.assertFalse(inc.startswith(('nuttx/', 'arch/')),
                                 f'{name} includes {inc}')

    def test_mfis_addresses(self):
        # Channel-0 registers and CTA slots, absolute
        text = (RCAR / 'hardware/rcar_mfis.h').read_text()
        mm = (RCAR / 'hardware/rcar_memorymap.h').read_text()

        def define(src, name):
            m = re.search(rf'^#define {name}\s+(?:\(\w+ \+ )?(0x[0-9a-fA-F]+)',
                          src, re.M)
            self.assertIsNotNone(m, name)
            return int(m.group(1), 16)

        mfis = define(mm, 'RCAR_MFIS_BASE')
        cta = define(mm, 'RCAR_ICCOM_CTA_BASE')
        self.assertEqual(mfis + define(text, 'MFIS_ICCOM0_XCTRL_OFFSET'),
                         0xE6261400)
        self.assertEqual(mfis + define(text, 'MFIS_ICCOM0_XMSG_OFFSET'),
                         0xE6261440)
        self.assertEqual(mfis + define(text, 'MFIS_ICCOM0_YCTRL_OFFSET'),
                         0xE6269404)
        self.assertEqual(mfis + define(text, 'MFIS_ICCOM0_YMSG_OFFSET'),
                         0xE6269460)
        for name, addr in (('ICCOM0_CTA_RX_UPPER', 0x47FC7000),
                           ('ICCOM0_CTA_RX_BOTTOM', 0x47FC7800),
                           ('ICCOM0_CTA_TX_UPPER', 0x47FC8000),
                           ('ICCOM0_CTA_TX_BOTTOM', 0x47FC8800)):
            self.assertEqual(cta + define(text, name), addr, name)


if __name__ == '__main__':
    unittest.main()
