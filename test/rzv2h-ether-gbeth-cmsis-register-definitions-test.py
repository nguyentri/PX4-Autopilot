#!/usr/bin/env python3
"""Check RZ/V2H GbEther register offsets and bit fields against FSP CMSIS.

The NuttX GbEther driver defines its own MAC/MTL/DMA register map in
arch/arm/src/rzv/hardware/rzv_ether.h.  The authority for that map is the
FSP 4.2 CMSIS gbeth_iodefine.h (R_GBETH_Type).  This test parses the CMSIS
structure (offsets and bit-field positions) and checks every register offset
and every register bit, shift and mask macro of the driver header against it.

rzv2h.svd is generated from the same FSP 4.2.0 headers (CR8 copy), so the
CMSIS header stays the direct authority here.  The test is skipped when the
local refs/ tree is not available.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = (ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/"
          "rzv_ether.h")
DRIVER = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ether.c"
PHY = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ether_phy.c"
CMSIS = (ROOT / "refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/cmsis/Device/RENESAS/"
         "Include/R9A09G057H/cm/iodefines/gbeth_iodefine.h")

SIZES = {"uint32_t": 4, "uint16_t": 2, "uint8_t": 1}


class CmsisLayout:
    """Brace-aware parser of the CMSIS typedef structs used by R_GBETH_Type."""

    def __init__(self, text):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"#.*", "", text)
        self.toks = re.findall(r"[A-Za-z_]\w*|\d+|[{}\[\];:]", text)
        self.types = {}
        i = 0
        while i < len(self.toks):
            if self.toks[i] == "typedef" and self.toks[i + 1] == "struct":
                node, i = self._block(i + 3, "struct")
                self.types[self.toks[i]] = node
                i += 2
            else:
                i += 1

    def _block(self, i, kind):
        toks = self.toks
        members = []
        while toks[i] != "}":
            if toks[i] in ("union", "struct"):
                sub, i = self._block(i + 2, toks[i])
                name = None
                if toks[i] != ";":
                    name = toks[i]
                    i += 1
                i += 1
                members.append(("agg", sub, name))
                continue
            j = i
            while toks[j] != ";":
                j += 1
            decl = [t for t in toks[i:j] if t not in ("__IOM", "__IM", "__OM")]
            i = j + 1
            if ":" in decl:
                k = decl.index(":")
                members.append(("bit", decl[k - 1] if k >= 2 else None,
                                int(decl[k + 1])))
            elif "[" in decl:
                k = decl.index("[")
                members.append(("arr", decl[0], decl[k - 1], int(decl[k + 1])))
            else:
                members.append(("scalar", decl[0], decl[1]))
        return (kind, members), i + 1

    def _size(self, node):
        kind, members = node
        if all(m[0] == "bit" for m in members):
            return 4
        sizes = [self._msize(m) for m in members]
        return max(sizes) if kind == "union" else sum(sizes)

    def _msize(self, m):
        if m[0] == "agg":
            return self._size(m[1])
        size = SIZES.get(m[1]) or self._size(self.types[m[1]])
        return size * m[3] if m[0] == "arr" else size

    def registers(self):
        """Return {name: (offset, {field: (bit, width)})} for R_GBETH_Type."""
        out = {}
        self._walk(self.types["R_GBETH_Type"], 0, "", out)
        return out

    def _walk(self, node, base, prefix, out):
        kind, members = node
        off = base
        for m in members:
            if m[0] == "scalar" and m[1] in SIZES:
                out.setdefault(prefix + m[2], (off, {}))
            elif m[0] == "agg":
                sub = m[1]
                if all(x[0] == "bit" for x in sub[1]):
                    name = m[2][:-2] if m[2].endswith("_b") else m[2]
                    fields = out.setdefault(prefix + name, (off, {}))[1]
                    bit = 0
                    for x in sub[1]:
                        if x[1]:
                            fields[x[1]] = (bit, x[2])
                        bit += x[2]
                else:
                    self._walk(sub, off, prefix, out)
            elif m[1] in self.types:
                count = m[3] if m[0] == "arr" else 1
                size = self._size(self.types[m[1]])
                for k in range(count):
                    self._walk(self.types[m[1]], off + k * size,
                               "%s%s[%d]." % (prefix, m[2], k), out)
            if kind == "struct":
                off += self._msize(m)


def header_macros(text):
    """Evaluate the object-like integer macros of the driver header."""
    text = re.sub(r"\\\n", " ", text)
    raw = {}
    for name, body in re.findall(r"^#\s*define\s+(\w+)(?!\()[ \t]+([^\n]*)$",
                                 text, flags=re.M):
        body = re.sub(r"/\*.*?\*/", "", body).strip()
        if body:
            raw[name] = re.sub(r"\b(0x[0-9a-fA-F]+|\d+)[uUlL]+\b", r"\1", body)

    values = {}

    def resolve(name, depth=0):
        if name in values:
            return values[name]
        if depth > 16 or name not in raw:
            raise KeyError(name)
        expr = re.sub(r"\b[A-Za-z_]\w*\b",
                      lambda m: str(resolve(m.group(0), depth + 1)), raw[name])
        if not re.fullmatch(r"[\s0-9a-fA-FxX()<>|&~+\-*]+", expr):
            raise KeyError(name)
        values[name] = eval(expr, {"__builtins__": {}})  # noqa: S307
        return values[name]

    for name in raw:
        try:
            resolve(name)
        except (KeyError, SyntaxError):
            pass
    return values


# Driver register offset macro -> CMSIS register name.
OFFSETS = {
    "RZV_ETH_MAC_CONF": "MACCR",
    "RZV_ETH_MAC_EXT_CONF": "MACECR",
    "RZV_ETH_MAC_PKT_FILT": "MACPFR",
    "RZV_ETH_MAC_WD_TO": "MACWTR",
    "RZV_ETH_MAC_HASH_HI": "MACHTR0",
    "RZV_ETH_MAC_HASH_LO": "MACHTR1",
    "RZV_ETH_MAC_MII_ADDR": "MACMAR",
    "RZV_ETH_MAC_MII_DATA": "MACMDR",
    "RZV_ETH_MAC_TX_FLOW_CTRL": "MACQTFCR",
    "RZV_ETH_MAC_RX_FLOW_CTRL": "MACRFCR",
    "RZV_ETH_MAC_FLOW_CTRL": "MACRFCR",
    "RZV_ETH_MAC_RXQ_CTRL0": "MACRC0",
    "RZV_ETH_MAC_RXQ_CTRL1": "MACRC1",
    "RZV_ETH_MAC_RXQ_CTRL2": "MACRC2",
    "RZV_ETH_MAC_INT_STAT": "MACISR",
    "RZV_ETH_MAC_INT_EN": "MACIER",
    "RZV_ETH_MAC_ADDR0_HI": "MAC_ADDRESS[0].MACAHR",
    "RZV_ETH_MAC_ADDR0_LO": "MAC_ADDRESS[0].MACALR",
    "RZV_ETH_MTL_OPERATION_MODE": "MTLOMR",
    "RZV_ETH_MTL_RXQ_DMA_MAP0": "MTLRDMR",
    "RZV_ETH_MTL_TXQ0_OP_MODE": "MTL_Q[0].MTLTOMR",
    "RZV_ETH_MTL_RXQ0_OP_MODE": "MTL_Q[0].MTLROMR",
    "RZV_ETH_MTL_RXQ0_CTRL": "MTL_Q[0].MTLRCR",
    "RZV_ETH_DMA_MODE": "DMR",
    "RZV_ETH_DMA_SYSBUS_MODE": "DSMR",
    "RZV_ETH_DMA_INT_STATUS": "DISR",
    "RZV_ETH_DMA_DEBUG_STATUS0": "DDS0",
    "RZV_ETH_DMA_CH0_CTRL": "DMA_CH[0].DCCR",
    "RZV_ETH_DMA_CH0_TX_CTRL": "DMA_CH[0].DCTCR",
    "RZV_ETH_DMA_CH0_RX_CTRL": "DMA_CH[0].DCRCR",
    "RZV_ETH_DMA_CH0_TXDESC_LIST": "DMA_CH[0].DCTLAR",
    "RZV_ETH_DMA_CH0_RXDESC_LIST": "DMA_CH[0].DCRLAR",
    "RZV_ETH_DMA_CH0_TXDESC_TAIL": "DMA_CH[0].DCTTPR",
    "RZV_ETH_DMA_CH0_RXDESC_TAIL": "DMA_CH[0].DCRTPR",
    "RZV_ETH_DMA_CH0_TXDESC_RING": "DMA_CH[0].DCTRLR",
    "RZV_ETH_DMA_CH0_RX_CTRL2": "DMA_CH[0].DCRC2R",
    "RZV_ETH_DMA_CH0_INT_EN": "DMA_CH[0].DCIER",
    "RZV_ETH_DMA_CH0_RX_INT_WD": "DMA_CH[0].DCRIWT",
    "RZV_ETH_DMA_CH0_SLOT_CTRL": "DMA_CH[0].DCSFCS",
    "RZV_ETH_DMA_CH0_CUR_TXDESC": "DMA_CH[0].DCCATDR",
    "RZV_ETH_DMA_CH0_CUR_RXDESC": "DMA_CH[0].DCCARDR",
    "RZV_ETH_DMA_CH0_CUR_TXBUF": "DMA_CH[0].DCCATBR",
    "RZV_ETH_DMA_CH0_CUR_RXBUF": "DMA_CH[0].DCCARBR",
    "RZV_ETH_DMA_CH0_STATUS": "DMA_CH[0].DCSR",
}

# Driver bit-macro prefix -> (CMSIS register, driver field -> CMSIS field).
FIELDS = {
    "MAC_CONF_": ("MACCR", {}),
    "MAC_PKT_FILT_": ("MACPFR", {}),
    "MAC_MII_ADDR_": ("MACMAR", {"GR": "RDA"}),
    "MAC_RXQ_CTRL0_": ("MACRC0", {}),
    "MAC_RXQ_CTRL1_": ("MACRC1", {}),
    "MTL_OP_MODE_": ("MTLOMR", {}),
    "MTL_TXQ_OP_": ("MTL_Q[0].MTLTOMR", {}),
    "MTL_RXQ_OP_": ("MTL_Q[0].MTLROMR", {}),
    "MTL_RXQ_DMA_MAP_": ("MTLRDMR", {}),
    "MTL_RXQ_CTRL_": ("MTL_Q[0].MTLRCR", {}),
    "DMA_MODE_": ("DMR", {}),
    "DMA_SYSBUS_MODE_": ("DSMR", {}),
    "DMA_DEBUG_STATUS0_": ("DDS0", {}),
    "DMA_CH0_STATUS_": ("DMA_CH[0].DCSR", {}),
    "DMA_CH0_INT_EN_": ("DMA_CH[0].DCIER", {"AISE": "AIE", "NISE": "NIE"}),
    "DMA_CH0_CTRL_": ("DMA_CH[0].DCCR", {"PBLX8": "PBLx8"}),
    "DMA_CH0_TX_CTRL_": ("DMA_CH[0].DCTCR", {"TXPBL": "TxPBL", "OSP": "OSF"}),
    "DMA_CH0_RX_CTRL_": ("DMA_CH[0].DCRCR", {"RXPBL": "RxPBL"}),
}

# Composite driver values that are not a single CMSIS field.
COMPOSITES = {"MAC_CONF_FSP_BASELINE"}

# Short-hand macros that must equal another checked macro.
EQUIVALENTS = {
    "MAC_MII_ADDR_GW": "MAC_MII_ADDR_GOC_WRITE",
    "MAC_MII_ADDR_GR": "MAC_MII_ADDR_GOC_READ",
}


def merged_fields(fields):
    """Join CMSIS split fields (GOC_0/GOC_1, RBSZ_4_0/RBSZ_13_5)."""
    out = dict(fields)
    groups = {}
    for name, (bit, width) in fields.items():
        m = re.fullmatch(r"(\w+?)_(\d+)(?:_\d+)?", name)
        if m:
            groups.setdefault(m.group(1), []).append((bit, width))
    for base, parts in groups.items():
        lo = min(b for b, _ in parts)
        hi = max(b + w for b, w in parts)
        if sum(w for _, w in parts) == hi - lo and len(parts) > 1:
            out.setdefault(base, (lo, hi - lo))
    return out


@unittest.skipUnless(CMSIS.exists(), "refs/ FSP 4.2 CMSIS not available")
class GbethCmsisRegisterDefinitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regs = CmsisLayout(CMSIS.read_text()).registers()
        cls.macros = header_macros(HEADER.read_text())

    def test_register_offsets_match_cmsis(self):
        for macro, reg in OFFSETS.items():
            with self.subTest(macro=macro):
                self.assertIn(macro, self.macros)
                self.assertIn(reg, self.regs)
                self.assertEqual(self.macros[macro], self.regs[reg][0],
                                 "%s != CMSIS %s @0x%04x" %
                                 (macro, reg, self.regs[reg][0]))

    def test_every_register_offset_macro_is_checked(self):
        offsets = {n for n in self.macros if n.startswith("RZV_ETH_")}
        self.assertEqual(offsets - set(OFFSETS), set())

    def test_bit_shift_and_mask_macros_match_cmsis_fields(self):
        checked = 0
        for name, value in sorted(self.macros.items()):
            prefix = next((p for p in FIELDS if name.startswith(p)), None)
            if prefix is None or name in COMPOSITES or name in EQUIVALENTS:
                continue
            reg, alias = FIELDS[prefix]
            fields = merged_fields(self.regs[reg][1])
            suffix = name[len(prefix):]
            with self.subTest(macro=name):
                kind = "bit"
                field = suffix
                for tail in ("_SHIFT", "_MASK"):
                    if suffix.endswith(tail):
                        kind, field = tail, suffix[:-len(tail)]
                field = alias.get(field, field)
                if field not in fields:
                    # Encoded value of a multi-bit field, e.g. TXQEN_EN.
                    owner = max((f for f in fields
                                 if suffix.startswith(f + "_") or
                                 suffix.startswith(
                                     next((a for a, c in alias.items()
                                           if c == f), f) + "_")),
                                key=len, default=None)
                    self.assertIsNotNone(owner, "%s has no CMSIS field in %s"
                                         % (name, reg))
                    bit, width = fields[owner]
                    self.assertEqual(value & ~(((1 << width) - 1) << bit), 0,
                                     "%s outside CMSIS %s.%s" %
                                     (name, reg, owner))
                    checked += 1
                    continue
                bit, width = fields[field]
                if kind == "_SHIFT":
                    self.assertEqual(value, bit, "%s vs %s.%s@%d" %
                                     (name, reg, field, bit))
                elif kind == "_MASK":
                    self.assertEqual(value, ((1 << width) - 1) << bit,
                                     "%s vs %s.%s@%d:%d" %
                                     (name, reg, field, bit, width))
                else:
                    self.assertEqual((value, width), (1 << bit, 1),
                                     "%s vs %s.%s@%d:%d" %
                                     (name, reg, field, bit, width))
                checked += 1
        self.assertGreater(checked, 100)

    def test_short_hand_macros_match_their_long_form(self):
        for short, full in EQUIVALENTS.items():
            with self.subTest(macro=short):
                self.assertEqual(self.macros[short], self.macros[full])

    def test_composite_baseline_uses_known_mac_conf_bits(self):
        baseline = self.macros["MAC_CONF_FSP_BASELINE"]
        fields = self.regs["MACCR"][1]
        expect = sum(1 << fields[f][0] for f in ("JE", "JD", "BE", "WD"))
        self.assertEqual(baseline, expect)

    def test_dma_interrupt_enable_matches_status_bits(self):
        ier = self.regs["DMA_CH[0].DCIER"][1]
        sr = self.regs["DMA_CH[0].DCSR"][1]
        for status, enable in (("TI", "TIE"), ("TBU", "TBUE"), ("RI", "RIE"),
                               ("RBU", "RBUE"), ("FBE", "FBEE"),
                               ("CDE", "CDEE"), ("AIS", "AIE"),
                               ("NIS", "NIE")):
            with self.subTest(status=status):
                self.assertEqual(sr[status][0], ier[enable][0])

    def test_rx_buffer_size_field_is_14_bits_from_bit_1(self):
        fields = merged_fields(self.regs["DMA_CH[0].DCRCR"][1])
        self.assertEqual(fields["RBSZ"], (1, 14))
        self.assertEqual(self.macros["DMA_CH0_RX_CTRL_RBSZ_MASK"],
                         0x3fff << 1)


class GbethDriverSourceContract(unittest.TestCase):
    """Source-level behaviour the CMSIS-correct register map relies on."""

    @classmethod
    def setUpClass(cls):
        cls.driver = DRIVER.read_text()
        cls.phy = PHY.read_text()

    def body(self, signature):
        # Skip prototypes: the definition is followed by "{" before any ";".
        match = re.search(re.escape(signature) + r"[^;{]*\)\s*\{",
                          self.driver)
        self.assertIsNotNone(match, signature)
        brace = match.end() - 1
        depth = 0
        for i in range(brace, len(self.driver)):
            depth += {"{": 1, "}": -1}.get(self.driver[i], 0)
            if depth == 0:
                return self.driver[brace:i + 1]
        raise AssertionError(signature)

    def test_fatal_bus_errors_are_enabled_and_recovered(self):
        self.assertRegex(self.driver, r"RZV_ETHER_DMA_INT_EN[^\n]*\\\n"
                                      r"(?:[^\n]*\\\n)*[^\n]*FBEE")
        work = self.body("static void rzv_work(")
        self.assertIn("RZV_ETHER_DMA_FATAL", work)
        self.assertIn("txtimeout_work", work)
        recover = self.body("static void rzv_txtimeout_work(")
        self.assertIn("rzv_mac_dma_stop(priv)", recover)
        self.assertIn("rzv_dma_setup(priv)", recover)
        self.assertIn("netdev_ifdown(&priv->dev)", recover)
        self.assertNotIn("rzv_ifup(", recover)

    def test_dma_stop_order_is_tx_then_mac_then_rx(self):
        stop = self.body("static void rzv_mac_dma_stop(")
        tx = stop.index("DMA_CH0_TX_CTRL_ST")
        tps = stop.index("DMA_DEBUG_STATUS0_TPS0_MASK")
        mac = stop.index("MAC_CONF_TE")
        rx = stop.index("DMA_CH0_RX_CTRL_SR")
        rps = stop.index("DMA_DEBUG_STATUS0_RPS0_MASK")
        self.assertLess(tx, tps)
        self.assertLess(tps, mac)
        self.assertLess(mac, rx)
        self.assertLess(rx, rps)
        self.assertIn("RZV_ETHER_DMA_STOP_POLLS", stop)

    def test_rx_tail_points_one_past_the_ring(self):
        self.assertGreaterEqual(self.driver.count(
            "&priv->rxdesc[CONFIG_RZV_ETHER_RXDESC]"), 2)

    def test_rx_length_and_buffer_guards(self):
        receive = self.body("static void rzv_receive(")
        self.assertIn("RZV_ETHER_MIN_FRAME", receive)
        self.assertIn("RZV_ETHER_BUFSIZE", receive)
        self.assertIn("% RZV_ETHER_DMA_ALIGN == 0", self.driver)

    def test_ksz9131_tx_dll_follows_fsp_sequence(self):
        start = self.phy.index("static int rzv_phy_ksz9131_txdll(")
        dll = self.phy[start:self.phy.index("\n}\n", start)]
        self.assertIn("PHY_KSZ9131_ID_MASK", dll)
        clear = dll.index("~PHY_KSZ9131_TXDLL_BYPASS")
        pulse = dll.index("| PHY_KSZ9131_TXDLL_RESET")
        release = dll.index("~PHY_KSZ9131_TXDLL_RESET")
        self.assertLess(clear, pulse)
        self.assertLess(pulse, release)


if __name__ == "__main__":
    unittest.main()
