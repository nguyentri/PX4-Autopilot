#!/usr/bin/env python3
"""Compare RZ/V2H MHU, CRC and RTC header macros against rzv2h.svd.

The SVD (CMSIS R_*_Type layout) is the register authority.  The MHU pairing
table and IPC routes are also checked against the FSP r_mhu_b_ns pairing so
that each link's doorbell lands on the receiver's MSG IRQ and each ack lands
on the sender's RSP IRQ.
"""

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVD = ROOT/'rzv2h.svd'
RZV = ROOT/'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
MHU_H = RZV/'hardware/rzv_mhu.h'
CRC_H = RZV/'hardware/rzv_crc.h'
RTC_H = RZV/'hardware/rzv_rtc.h'
MHU_CORE_C = RZV/'rzv_mhu_core.c'
CHANNELS_H = RZV/'rzv_ipc_channels.h'
FSP_PAIR_H = ROOT/'refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/mcu/rzv2h/bsp_mhu_b.h'

DEFINE = re.compile(r'^\s*#\s*define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)u?\b', re.M)


def int_auto(text):
    return int(text, 0)


def defines(path):
    return {name: int_auto(value) for name, value in DEFINE.findall(path.read_text())}


def svd_peripherals():
    root = ET.parse(SVD).getroot()
    peripherals = {p.findtext('name'): p for p in root.iter('peripheral')}
    resolved = {}
    for name, node in peripherals.items():
        source = node
        parent = node.get('derivedFrom')
        if node.find('registers') is None and parent:
            source = peripherals[parent]
        registers = {r.findtext('name'): int_auto(r.findtext('addressOffset'))
                     for r in source.findall('registers/register')}
        resolved[name] = (int_auto(node.findtext('baseAddress')), registers)
    return resolved


class MhuParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svd = svd_peripherals()
        cls.macros = defines(MHU_H)

    def test_window_bases_and_strides(self):
        ns0, _ = self.svd['R_MHU_NS0']
        s0, _ = self.svd['R_MHU_S0']
        sw0, _ = self.svd['R_MHU_SWINT0']
        self.assertEqual(self.macros['RZV_MHU_NS_CR8_BASE'], ns0)
        self.assertEqual(self.macros['RZV_MHU_S_CR8_BASE'], s0)
        self.assertEqual(self.macros['RZV_MHU_SWINT_CR8_BASE'], sw0)
        self.assertEqual(self.macros['RZV_MHU_CH_STRIDE'],
                         self.svd['R_MHU_NS1'][0] - ns0)
        self.assertEqual(self.macros['RZV_MHU_CH_STRIDE'],
                         self.svd['R_MHU_S1'][0] - s0)
        self.assertEqual(self.macros['RZV_MHU_SWINT_STRIDE'],
                         self.svd['R_MHU_SWINT1'][0] - sw0)

    def test_every_svd_instance_follows_the_stride(self):
        for prefix, base, stride, count in (
                ('R_MHU_NS', 'RZV_MHU_NS_CR8_BASE', 'RZV_MHU_CH_STRIDE',
                 'RZV_MHU_MAX_CHANNELS'),
                ('R_MHU_S', 'RZV_MHU_S_CR8_BASE', 'RZV_MHU_CH_STRIDE',
                 'RZV_MHU_MAX_CHANNELS'),
                ('R_MHU_SWINT', 'RZV_MHU_SWINT_CR8_BASE',
                 'RZV_MHU_SWINT_STRIDE', 'RZV_MHU_SWINT_CHANNELS')):
            names = [n for n in self.svd if re.fullmatch(prefix + r'\d+', n)]
            self.assertEqual(len(names), self.macros[count], prefix)
            for name in names:
                index = int(name[len(prefix):])
                with self.subTest(name=name):
                    self.assertEqual(self.svd[name][0], self.macros[base] +
                                     index * self.macros[stride])

    def test_cm33_aliases_keep_the_cr8_offset_inside_the_window(self):
        for window in ('NS', 'SWINT'):
            cr8 = self.macros[f'RZV_MHU_{window}_CR8_BASE']
            cm33 = self.macros[f'RZV_MHU_{window}_CM33_BASE']
            self.assertEqual(cm33 - cr8, 0x40000000, window)
        self.assertEqual(self.macros['RZV_MHU_S_CM33_BASE'] -
                         self.macros['RZV_MHU_S_CR8_BASE'], 0x30000000)

    def test_register_offsets(self):
        _, ns = self.svd['R_MHU_NS0']
        for macro, register in (('MSG_STS', 'MSG_INT_STSn'),
                                ('MSG_SET', 'MSG_INT_SETn'),
                                ('MSG_CLR', 'MSG_INT_CLRn'),
                                ('RSP_STS', 'RSP_INT_STSn'),
                                ('RSP_SET', 'RSP_INT_SETn'),
                                ('RSP_CLR', 'RSP_INT_CLRn')):
            with self.subTest(register=register):
                self.assertEqual(self.macros[f'RZV_MHU_{macro}_OFF'],
                                 ns[register])
        _, sw = self.svd['R_MHU_SWINT0']
        for macro in ('STS', 'SET', 'CLR'):
            with self.subTest(register=macro):
                self.assertEqual(self.macros[f'RZV_MHU_SW_{macro}_OFF'],
                                 sw[f'SW_INT_{macro}n'])


class CrcRtcParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svd = svd_peripherals()

    def check(self, header, peripheral, prefix, indexed):
        macros = defines(header)
        base, registers = self.svd[peripheral]
        self.assertEqual(macros[f'{prefix}0_BASE'], base)
        checked = 0
        for name, offset in registers.items():
            match = re.fullmatch(r'([A-Z]+?)(\d)', name)
            if match and match.group(1) in indexed:
                start, step = indexed[match.group(1)]
                with self.subTest(register=name):
                    self.assertEqual(start + int(match.group(2)) * step,
                                     offset)
                checked += 1
                continue
            macro = f'{prefix}_{name}_OFFSET'
            if macro in macros:
                with self.subTest(register=name):
                    self.assertEqual(macros[macro], offset)
                checked += 1
        self.assertEqual(checked, len(registers), 'unchecked SVD registers')

    def indexed(self, header, prefix, names):
        text = header.read_text()
        result = {}
        for name in names:
            match = re.search(
                rf'#define\s+{prefix}_{name}_OFFSET\(m\)\s+\((0x[0-9a-fA-F]+)\s*'
                rf'\+\s*\(\(m\)\s*\*\s*(0x[0-9a-fA-F]+)\)\)', text)
            self.assertIsNotNone(match, name)
            result[name] = (int_auto(match.group(1)), int_auto(match.group(2)))
        return result

    def test_crc_offsets_match_svd(self):
        self.check(CRC_H, 'R_CRC', 'RZV_CRC',
                   self.indexed(CRC_H, 'RZV_CRC', ('CRCCR',)))

    def test_rtc_offsets_match_svd(self):
        self.check(RTC_H, 'R_RTC', 'RZV_RTC',
                   self.indexed(RTC_H, 'RZV_RTC', ('BCNT', 'RCR')))


def pair_table():
    rows = re.findall(r'\{\s*(\d+),\s*(\d+)\s*\},\s*/\* ch(\d+) \*/',
                      MHU_CORE_C.read_text())
    return {int(ch): (int(msg), int(rsp)) for msg, rsp, ch in rows}


class PairingAndRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pair = pair_table()
        cls.routes = defines(CHANNELS_H)

    def test_pair_table_is_complete(self):
        self.assertEqual(sorted(self.pair), list(range(42)))

    def assert_link(self, init_tx, init_rx, resp_tx, resp_rx):
        msg = lambda ch: self.pair[ch][0]
        rsp = lambda ch: self.pair[ch][1]
        self.assertEqual(msg(init_tx), resp_rx, 'initiator doorbell')
        self.assertEqual(rsp(resp_rx), init_tx, 'responder ack')
        self.assertEqual(msg(resp_tx), init_rx, 'responder doorbell')
        self.assertEqual(rsp(init_rx), resp_tx, 'initiator ack')

    def test_cr8_cr8_link(self):
        r = self.routes
        self.assert_link(r['RZV_IPC_CR8CR8_TX_CHAN'], r['RZV_IPC_CR8CR8_RX_CHAN'],
                         r['RZV_IPC_CR8CR8_RESP_TX_CHAN'],
                         r['RZV_IPC_CR8CR8_RESP_RX_CHAN'])

    def test_cr8_1_cm33_link(self):
        r = self.routes
        self.assert_link(r['RZV_IPC_CR8_1_CM33_TX_CHAN'],
                         r['RZV_IPC_CR8_1_CM33_RX_CHAN'],
                         r['RZV_IPC_CR8_1_CM33_CM33_TX_CHAN'],
                         r['RZV_IPC_CR8_1_CM33_CM33_RX_CHAN'])

    def test_cr8_cm33_link_matches_the_cr8_1_route(self):
        r = self.routes
        self.assertEqual(r['RZV_IPC_CR8CM33_TX_CHAN'],
                         r['RZV_IPC_CR8_1_CM33_TX_CHAN'])
        self.assertEqual(r['RZV_IPC_CR8CM33_RX_CHAN'],
                         r['RZV_IPC_CR8_1_CM33_RX_CHAN'])

    def test_rptun_rings_the_message_peer_of_its_own_block(self):
        r = self.routes
        local = r['RZV_IPC_CA55_LOCAL_CHAN']
        self.assertEqual(self.pair[local][0], r['RZV_IPC_CA55_TX_CHAN'])
        self.assertEqual(r['RZV_IPC_CA55_RX_CHAN'], local)

    def test_loopback_rings_its_own_block(self):
        r = self.routes
        self.assertEqual(r['RZV_IPC_LOOPBACK_TX_CHAN'],
                         r['RZV_IPC_LOOPBACK_RX_CHAN'])


@unittest.skipUnless(FSP_PAIR_H.exists(), 'FSP 4.2.0 reference not present')
class FspPairReference(unittest.TestCase):
    """Needs the local-only refs/ FSP tree, so the catalog runs it as a reference test."""

    def test_pair_table_matches_fsp(self):
        rows = re.findall(r'\{(\d+),\s*R_MHU_NS\d+,\s*(\d+),\s*R_MHU_NS\d+,\s*\},?'
                          r'\s*/\* MHU NS CH(\d+) \*/', FSP_PAIR_H.read_text())
        fsp = {int(ch): (int(msg), int(rsp)) for msg, rsp, ch in rows}
        self.assertEqual(len(fsp), 42)
        self.assertEqual(pair_table(), fsp)


if __name__ == '__main__':
    unittest.main()
