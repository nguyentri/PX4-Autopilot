#!/usr/bin/env python3
"""Generate rzv2h.svd (CMSIS-SVD) from the Renesas FSP CMSIS device headers.

The register map comes from the Cortex-R8 view of the R9A09G057H device in the
FSP 4.2.0 CMSIS tree (refs/rz-fsp-4.2.0/.../Include):

  R9A09G057H.h               device umbrella; selects R9A09G057H/cr/iodefine.h
                             for BSP_SUPPORT_CORE_CR8
  R9A09G057H/cr/iodefine.h   list of per-peripheral iodefine headers (order of
                             the peripherals in the SVD)
  .../cr/iodefines/*.h       R_*_Type structs, *_BASE addresses and instances
  R9A09G057H/iobitmask.h     list of *_iobitmask.h headers; their _Pos/_Msk
                             macros are used only to cross-check bit fields

Every R_*_Type struct is laid out with the C rules that GCC applies to these
headers (natural alignment, bit fields packed in their declared unit), so the
SVD offsets equal offsetof() on the target.  Mapping to SVD:

  union { X; struct {..} X_b; }    register X with the X_b bit fields
  uint32_t X[n]                    register X[%s], dim n
  R_Y_Type X[n] / struct {..} X    cluster X[%s] (or X) holding Y's registers
  anonymous struct/union           members inlined at their offsets
  RESERVED* members, unnamed pads  skipped
  first instance of a type         full peripheral; other instances use
                                   derivedFrom

The <cpu> element takes the CR8 core constants of R9A09G057H.h (MPU, FPU,
priority bits) and CPU_REVISION.  Interrupts come from the CR8 IRQn_Type enum
of the FSP BSP (bsp/mcu/rzv2h/cr/bsp_irq_id.h, next to the cmsis/ tree): every
GIC SPI (value >= 0) becomes an <interrupt> of the peripheral that raises it
(IRQ_RULES, else the longest R_<prefix> instance name).  The Source/ files
(startup, system init) carry no register or interrupt data.

Usage:
  ./generate-rzv2h-svd.py                 write rzv2h.svd at the repo root
  ./generate-rzv2h-svd.py --check         exit 1 if rzv2h.svd is stale
  ./generate-rzv2h-svd.py -o out.svd -v   custom output, list every warning
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_INCLUDE = ROOT / "refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/cmsis/Device/RENESAS/Include"
DEFAULT_OUTPUT = ROOT / "rzv2h.svd"
DEVICE = "R9A09G057H"
DEVICE_DESCRIPTION = "Renesas RZ/V2H(P) (R9A09G057H), Cortex-R8 register view"

INT_SIZES = {"uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8,
             "int8_t": 1, "int16_t": 2, "int32_t": 4, "int64_t": 8}
ACCESS = {"__IM": "read-only", "__I": "read-only", "__OM": "write-only",
          "__O": "write-only", "__IOM": "read-write", "__IO": "read-write"}
IGNORED_QUALIFIERS = {"const", "volatile"}

TOKEN_RE = re.compile(r"""
    (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<pp>^[ \t]*\#[^\n]*)
  | (?P<ident>[A-Za-z_]\w*)
  | (?P<num>0[xX][0-9A-Fa-f]+|\d+)
  | (?P<punct>[{}\[\];:()*,])
  | (?P<ws>\s+)
  | (?P<bad>.)
""", re.S | re.M | re.X)

# Register offsets where the FSP 4.2.0 header disagrees with the hardware manual.  The
# R9A09G057H headers of the FSP 3.0.0 EVK examples, the hardware manual, the previous
# rzv2h.svd and arch/arm/src/rzv/hardware/rzv_i3c.h all place the I3C device address
# table at DATBASn = 0x224 + 4 * n and EXDATBAS at 0x310; FSP 4.2.0 inserts 4-byte
# reserved gaps (8-byte stride) and moves EXDATBAS to 0x2A0.
# FSP 4.2.0 (and 3.0.0) gpio_iodefine.h puts IEN2B_L and IEN2B_H in one union right after
# IEN12_H, so both land at 0x1878 and H overlaps L.  Every other per-port GPIO family
# (P, PM, PMC, PFC, PIN, IOLH, SR, PUPD, FILxxx, ISEL, NOD, SMT) places port 2B at the
# same index, family base + 0x138 for the 8-byte L/H families, and
# arch/arm/src/rzv/hardware/rzv_gpio.h uses 0x1938/0x193C.
#   {typedef: {register: (offset in the FSP 4.2.0 header, emitted offset)}}
# An entry is applied only while the header still has the listed offset; a header that
# already has the emitted offset (FSP 3.0.0) is a no-op warning, and any other header
# offset is an error so the erratum gets re-evaluated.  --no-errata disables it.
ERRATA = {
    "R_I3C_B0_Type": {
        **{"DATBAS%d" % n: (0x224 + 8 * n, 0x224 + 4 * n) for n in range(1, 8)},
        "EXDATBAS": (0x2A0, 0x310),
    },
    "R_GPIO_Type": {
        "IEN2B_L": (0x1878, 0x1938),
        "IEN2B_H": (0x1878, 0x193C),
    },
}

# R9A09G057H.h has no __CR8_REV.  MIDR read on the RDK board's CR8-0 (J-Link GDB server
# "monitor cp15 0, 0, 0, 0") is 0x410FC183: Arm Cortex-R8, part 0xC18, variant 0, revision 3.
CPU_REVISION = "r0p3"
CPU_DEFINES = ("__MPU_PRESENT", "__FPU_PRESENT", "__FPU_DP", "__NVIC_PRIO_BITS", "__Vendor_SysTickConfig")

IRQ_HEADER = "mcu/rzv2h/cr/bsp_irq_id.h"    # relative to the FSP bsp/ directory that holds cmsis/
IRQ_RE = re.compile(r"^[ \t]*(\w+)_IRQn\s*=\s*(\d+)\s*,?[ \t]*(?:/\*\s*(.*?)\s*\*/)?", re.M)
IRQ_COMMENT_RE = re.compile(r"IRQ(?:\s*No)?\s*[.:]?\s*(\d+)\s*,\s*(.*)")
# IRQn stem -> peripheral, for stems whose prefix is not an R_* instance name.  Tried in
# order before the longest-prefix match; a stem that matches nothing is an error.
IRQ_RULES = (
    (r"NMI$|GPIO_IRQ\d+$|ICU_|SEL\d+$", r"R_INTC"),      # NMI, IRQ pins, ICU software and IRQSEL slots
    (r"CR8_|GIC_", r"R_INTC_GIC"),                       # core PMU/ECC/CTI/DCC events and GIC faults
    (r"SPI(\d+)_", r"R_SPI_B\1"),
    (r"ADC(\d+)_", r"R_ADC_E\1"),
    (r"XSPI_", r"R_XSPI0"),
    (r"MHU_(?:MSG|RSP)(\d+)_(N?S)$", r"R_MHU_\2\1"),
    (r"MHU_SW_MHU_INT(\d+)$", r"R_MHU_SWINT\1"),
)

BASE_RE = re.compile(r"#\s*define\s+(\w+)_BASE\s+\(?\s*(0[xX][0-9A-Fa-f]+)")
INSTANCE_RE = re.compile(r"#\s*define\s+(\w+)\s+\(\(\s*(\w+)\s*\*\s*\)\s*(\w+)_BASE\s*\)")
BITMASK_RE = re.compile(r"#\s*define\s+(\w+)_(Pos|Msk)\s+\((0[xX][0-9A-Fa-f]+|\d+)U?L?\)")


class HeaderError(Exception):
    """Unsupported or malformed construct in an FSP header."""


class Aggregate:
    """A struct or union body; size/align are filled in by layout()."""

    def __init__(self, kind, members):
        self.kind = kind
        self.members = members
        self.size = None
        self.align = None

    def is_bitfield_struct(self):
        return self.kind == "struct" and self.members and all(m.bits is not None for m in self.members)


class Member:
    """One declaration inside an aggregate."""

    def __init__(self, name, ctype, agg, dims, bits, access, line):
        self.name = name        # None for anonymous aggregates and unnamed bit fields
        self.ctype = ctype      # integer or typedef name; None for inline aggregates
        self.agg = agg          # inline struct/union body
        self.dims = dims        # array dimensions
        self.bits = bits        # bit-field width
        self.access = access    # SVD access from __IM/__OM/__IOM, or None
        self.line = line
        self.doc = None         # trailing /*!< ... */ text
        self.offset = 0         # byte offset inside the parent aggregate
        self.bitpos = 0         # bit offset inside the parent (bit fields)
        self.elem_size = 0      # size of one array element


class Typedef:
    def __init__(self, name, agg, brief, size_doc, path):
        self.name, self.agg, self.brief, self.size_doc, self.path = name, agg, brief, size_doc, path


def clean_doc(text):
    """Strip comment markers and continuation stars from a doc comment."""
    text = re.sub(r"^/\*+!?<?|\*/$", "", text)
    text = re.sub(r"\n\s*\*", " ", text)
    return " ".join(text.split())


class HeaderParser:
    """Parse the typedef/struct/union subset used by the FSP iodefine headers."""

    def __init__(self, path):
        self.path = path
        self.text = path.read_text()
        self.tokens = []
        self.pp_lines = []
        line = 1
        for m in TOKEN_RE.finditer(self.text):
            kind, value = m.lastgroup, m.group()
            if kind == "pp":
                self.pp_lines.append(value)
            elif kind == "bad":
                raise HeaderError("%s:%d: unexpected character %r" % (path, line, value))
            elif kind == "comment":
                if value.startswith("/*!<"):
                    self.tokens.append(("doc", value, line))
                elif "@brief" in value:
                    self.tokens.append(("brief", value, line))
            elif kind != "ws":
                self.tokens.append((kind, value, line))
            line += value.count("\n")
        self.pos = 0

    def error(self, message):
        line = self.tokens[min(self.pos, len(self.tokens) - 1)][2] if self.tokens else 0
        return HeaderError("%s:%d: %s" % (self.path, line, message))

    def peek(self, kind=None):
        if self.pos >= len(self.tokens):
            return None
        tok = self.tokens[self.pos]
        return tok if kind is None or tok[0] == kind else None

    def peek_required(self):
        tok = self.peek()
        if tok is None:
            raise self.error("unexpected end of file")
        return tok

    def take(self, value=None):
        while self.peek("doc"):
            self.pos += 1   # doc comments in odd places (e.g. "typedef struct /*!< .. */ {") carry no layout
        tok = self.peek()
        if tok is None or (value is not None and tok[1] != value):
            raise self.error("expected %r, found %r" % (value, tok[1] if tok else "EOF"))
        self.pos += 1
        return tok

    def take_number(self):
        tok = self.take()
        if tok[0] != "num":
            raise self.error("expected a number, found %r" % tok[1])
        return int(tok[1], 0)

    def take_doc(self):
        docs = []
        while self.peek("doc"):
            docs.append(clean_doc(self.tokens[self.pos][1]))
            self.pos += 1
        return " ".join(docs) or None

    def take_dims(self):
        dims = []
        while self.peek() and self.peek()[1] == "[":
            self.take("[")
            dims.append(self.take_number())
            self.take("]")
        if len(dims) > 1:
            raise self.error("multi-dimensional arrays are not supported")
        return dims

    def parse_aggregate(self, kind):
        self.take("{")
        members = []
        while self.take_doc() is not None or self.peek_required()[1] != "}":
            if self.peek_required()[1] != "}":
                members.append(self.parse_member())
        self.take("}")
        return Aggregate(kind, members)

    def parse_member(self):
        self.take_doc()
        line = self.peek_required()[2]
        if self.peek_required()[1] in ("struct", "union"):
            agg = self.parse_aggregate(self.take()[1])
            name = self.take()[1] if self.peek("ident") else None
            member = Member(name, None, agg, self.take_dims(), None, None, line)
        else:
            access = None
            while self.peek("ident") and (self.peek()[1] in ACCESS or self.peek()[1] in IGNORED_QUALIFIERS):
                qualifier = self.take()[1]
                access = ACCESS.get(qualifier, access)
            ctype = self.take()[1]
            name = self.take()[1] if self.peek("ident") else None
            dims = self.take_dims()
            bits = None
            if self.peek() and self.peek()[1] == ":":
                self.take(":")
                bits = self.take_number()
            member = Member(name, ctype, None, dims, bits, access, line)
        self.take(";")
        member.doc = self.take_doc()
        return member

    def parse(self):
        """Return (typedefs in order, instances [(name, type, base)], meta)."""
        typedefs, brief = [], None
        while self.peek():
            tok = self.peek()
            if tok[0] == "brief":
                brief = clean_doc(self.take()[1]).replace("@brief", "").strip()
            elif tok[0] == "doc":
                self.take()
            elif tok[1] == "typedef":
                self.take()
                kind = self.take()[1]
                if kind not in ("struct", "union"):
                    raise self.error("unsupported typedef %r" % kind)
                agg = self.parse_aggregate(kind)
                name = self.take()[1]
                self.take(";")
                size_doc = self.take_doc()
                typedefs.append(Typedef(name, agg, brief, size_doc, self.path))
                brief = None
            else:
                raise self.error("unexpected token %r" % tok[1])

        bases = {}
        instances = []
        for line in self.pp_lines:
            m = BASE_RE.match(line.strip())
            if m:
                bases[m.group(1)] = int(m.group(2), 16)
                continue
            m = INSTANCE_RE.match(line.strip())
            if m:
                instances.append([m.group(1), m.group(2), m.group(3)])
        for inst in instances:
            if inst[2] not in bases:
                raise HeaderError("%s: %s has no %s_BASE" % (self.path, inst[0], inst[2]))
            inst[2] = bases[inst[2]]

        meta = {}
        for key in ("Version", "Description"):
            m = re.search(r"\*\s*%s\s*:\s*(.+)" % key, self.text)
            meta[key] = m.group(1).strip() if m else None
        return typedefs, [tuple(i) for i in instances], meta


def roundup(value, align):
    return (value + align - 1) // align * align


class Layout:
    """Compute C struct layout (GCC/AAPCS rules for the constructs in use)."""

    def __init__(self, typedefs):
        self.typedefs = typedefs

    def element(self, member):
        if member.agg is not None:
            self.layout(member.agg)
            return member.agg.size, member.agg.align
        if member.ctype in INT_SIZES:
            size = INT_SIZES[member.ctype]
            return size, size
        if member.ctype in self.typedefs:
            agg = self.typedefs[member.ctype].agg
            self.layout(agg)
            return agg.size, agg.align
        raise HeaderError("line %d: unknown type %r" % (member.line, member.ctype))

    def layout(self, agg):
        if agg.size is not None:
            return
        bitpos, size, align = 0, 0, 1
        for m in agg.members:
            elem_size, elem_align = self.element(m)
            m.elem_size = elem_size
            count = m.dims[0] if m.dims else 1
            align = max(align, elem_align)
            if m.bits is not None:
                if m.agg is not None or m.dims:
                    raise HeaderError("line %d: bit field on an aggregate or array" % m.line)
                unit = elem_size * 8
                if agg.kind == "union":
                    m.offset, m.bitpos = 0, 0
                    size = max(size, elem_size)
                    continue
                if m.bits == 0:
                    bitpos = roundup(bitpos, unit)
                    continue
                if bitpos // unit != (bitpos + m.bits - 1) // unit:
                    bitpos = roundup(bitpos, unit)
                m.bitpos = bitpos
                m.offset = bitpos // unit * elem_size
                bitpos += m.bits
            elif agg.kind == "union":
                m.offset = 0
                size = max(size, elem_size * count)
            else:
                m.offset = roundup(roundup(bitpos, 8) // 8, elem_align)
                bitpos = (m.offset + elem_size * count) * 8
        if agg.kind == "struct":
            size = roundup(bitpos, 8) // 8
        agg.size = roundup(size, align)
        agg.align = align


class Emitter:
    """Turn laid-out aggregates into SVD register/cluster elements."""

    def __init__(self, typedefs, warnings, errata):
        self.typedefs = typedefs
        self.errata = errata    # {(typedef, register): (header offset, emitted offset)}
        self.errata_used = set()   # errata whose register was found
        self.errata_applied = 0    # errata that changed an offset
        self.warnings = warnings
        self.peripheral = None  # instance being emitted (first instance of its type)
        # Emitted bit fields: path is the C member path ("GRP[0]", "CH[0]") of the enclosing
        # clusters; c_register / c_view name the register and its bit-field view in C, element 0.
        self.fields = []
        self.scope_start = [0]  # absolute offset of each enclosing SVD scope (peripheral, clusters)

    def warn(self, typedef, member, message):
        self.warnings.append("%s:%d: %s" % (typedef.path.name, member.line, message))

    def check_offset_doc(self, typedef, member, offset):
        m = re.match(r"\(@\s*(0[xX][0-9A-Fa-f]+)\)\s*(.*)", member.doc or "")
        if not m:
            return member.doc or None
        # Most headers document offsets relative to their typedef; canfd sub-typedefs document the
        # absolute offset inside R_CANFD (first array element).  Accept either.
        if int(m.group(1), 16) not in (offset, self.scope_start[-1] + offset):
            self.warn(typedef, member, "%s laid out at 0x%X, comment says %s"
                      % (member.name, offset, m.group(1)))
        return m.group(2) or None

    def register(self, typedef, path, name, offset, size_bytes, dims, access, views, doc_member):
        reg = ET.Element("register")
        if dims:
            ET.SubElement(reg, "dim").text = str(dims[0])
            ET.SubElement(reg, "dimIncrement").text = "0x%X" % size_bytes
            name += "[%s]"
        ET.SubElement(reg, "name").text = name
        description = self.check_offset_doc(typedef, doc_member, offset) if doc_member else None
        if description:
            ET.SubElement(reg, "description").text = description
        ET.SubElement(reg, "addressOffset").text = "0x%X" % offset
        ET.SubElement(reg, "size").text = str(size_bytes * 8)
        ET.SubElement(reg, "access").text = access or "read-write"
        if views:
            fields = ET.SubElement(reg, "fields")
            seen = set()
            for view, f in ((view, f) for view in views for f in view.agg.members):
                if f.name is None:
                    continue
                if f.name in seen:
                    raise HeaderError("%s:%d: field %s.%s defined twice" % (typedef.path.name, f.line, name, f.name))
                seen.add(f.name)
                field = ET.SubElement(fields, "field")
                ET.SubElement(field, "name").text = f.name
                fdoc = f.doc
                m = re.match(r"\[(\d+)\.\.(\d+)\]\s*(.*)", fdoc or "")
                if m:
                    msb, lsb = int(m.group(1)), int(m.group(2))
                    if (lsb, msb) != (f.bitpos, f.bitpos + f.bits - 1):
                        self.warn(typedef, f, "%s.%s laid out at [%d..%d], comment says [%d..%d]"
                                  % (name, f.name, f.bitpos + f.bits - 1, f.bitpos, msb, lsb))
                    fdoc = m.group(3)
                if fdoc:
                    ET.SubElement(field, "description").text = fdoc
                ET.SubElement(field, "bitOffset").text = str(f.bitpos)
                ET.SubElement(field, "bitWidth").text = str(f.bits)
                ET.SubElement(field, "access").text = f.access or access or "read-write"
                self.fields.append({
                    "peripheral": self.peripheral, "path": path, "field": f.name,
                    "register": name.replace("[%s]", ""), "c_register": name.replace("[%s]", "[0]"),
                    "c_view": view.name + ("[0]" if view.dims else ""),
                    "bitpos": f.bitpos, "bits": f.bits, "source": "%s:%d" % (typedef.path.name, f.line)})
            if not len(fields):
                reg.remove(fields)
        return reg

    def cluster(self, typedef, path, name, offset, dims, agg, description, doc_member):
        cl = ET.Element("cluster")
        if dims:
            ET.SubElement(cl, "dim").text = str(dims[0])
            ET.SubElement(cl, "dimIncrement").text = "0x%X" % agg.size
            name += "[%s]"
        ET.SubElement(cl, "name").text = name
        doc = self.check_offset_doc(typedef, doc_member, offset) if doc_member.doc else None
        ET.SubElement(cl, "description").text = doc or description or ("%s register group" % name.replace("[%s]", ""))
        ET.SubElement(cl, "addressOffset").text = "0x%X" % offset
        inner_typedef = self.typedefs.get(doc_member.ctype, typedef)
        self.scope_start.append(self.scope_start[-1] + offset)
        self.members(inner_typedef, agg, 0, cl, path + [name.replace("[%s]", "[0]")])
        self.scope_start.pop()
        return cl

    def members(self, typedef, agg, base, parent, path):
        """Append the SVD elements for agg (placed at base) to parent."""
        # Bit-field views of register X: X_b, or X_<view>_b when the hardware has separate
        # read/write layouts (cr8 private_timer PTISR_FLAG_b / PTISR_CLR_b).
        bitstructs = [m for m in agg.members if m.agg is not None and m.name and m.agg.is_bitfield_struct()]
        used = set()
        for m in agg.members:
            offset = base + m.offset
            if m.agg is not None and m.name and m.agg.is_bitfield_struct():
                continue
            if m.bits is not None:
                if m.name:
                    raise HeaderError("%s:%d: bit field %s outside a register bit-field struct"
                                      % (typedef.path.name, m.line, m.name))
                continue
            if m.name is None and m.agg is None:
                continue
            if m.name and m.name.startswith("RESERVED"):
                continue
            if m.agg is not None and m.name is None:
                self.members(typedef, m.agg, offset, parent, path)
            elif m.agg is not None:
                parent.append(self.cluster(typedef, path, m.name, offset, m.dims, m.agg, None, m))
            elif m.ctype in INT_SIZES:
                views = [b for b in bitstructs if b.offset == m.offset and
                         (b.name == m.name + "_b" or (b.name.startswith(m.name + "_") and b.name.endswith("_b")))]
                for view in views:
                    used.add(view.name)
                    if view.dims != m.dims:
                        # FSP quirk (canfd CFDTMIEC[12] vs CFDTMIEC_b[4]): the fields describe every element
                        self.warn(typedef, view, "%s%s vs %s%s; fields applied to every element"
                                  % (m.name, m.dims, view.name, view.dims))
                reg = self.register(typedef, path, m.name, offset, m.elem_size, m.dims, m.access, views, m)
                key = (typedef.name, m.name)
                if key in self.errata:
                    header_offset, fixed_offset = self.errata[key]
                    if offset == fixed_offset:
                        self.warn(typedef, m, "%s.%s already at 0x%X; erratum not needed for this header"
                                  % (typedef.name, m.name, offset))
                    elif offset != header_offset:
                        raise HeaderError("%s:%d: %s.%s is at 0x%X, erratum expects 0x%X; re-check ERRATA"
                                          % (typedef.path.name, m.line, typedef.name, m.name, offset,
                                             header_offset))
                    else:
                        reg.find("addressOffset").text = "0x%X" % fixed_offset
                        self.errata_applied += 1
                    self.errata_used.add(key)
                parent.append(reg)
            else:
                inner = self.typedefs[m.ctype]
                parent.append(self.cluster(typedef, path, m.name, offset, m.dims, inner.agg,
                                           inner.brief and re.sub(r"^.*\((.*)\)\s*$", r"\1", inner.brief), m))
        for m in bitstructs:
            if m.name in used:
                continue
            target = m.name[:-2] if m.name.endswith("_b") else m.name
            accesses = {f.access for f in m.agg.members if f.name}
            access = accesses.pop() if len(accesses) == 1 else "read-write"
            self.warn(typedef, m, "%s has no scalar view; register %s synthesized" % (m.name, target))
            parent.append(self.register(typedef, path, target, base + m.offset, m.agg.size, m.dims,
                                        access, [m], None))


def check_unique_names(parent, where, errors):
    names = [el.findtext("name") for el in parent if el.tag in ("register", "cluster")]
    for name in sorted({n for n in names if names.count(n) > 1}):
        errors.append("%s: duplicate SVD name %s" % (where, name))
    for el in parent:
        if el.tag == "cluster":
            check_unique_names(el, where + "." + el.findtext("name"), errors)


def load_bitmasks(path):
    """Return {macro stem: (pos, mask)} from an *_iobitmask.h header."""
    values = {}
    for m in BITMASK_RE.finditer(path.read_text()):
        values.setdefault(m.group(1), {})[m.group(2)] = int(m.group(3), 0)
    return {k: (v["Pos"], v["Msk"]) for k, v in values.items() if "Pos" in v and "Msk" in v}


def crosscheck_bitmasks(fields, bitmasks, warnings):
    """Compare emitted fields with _Pos/_Msk macros whose names end in their path."""
    by_suffix = {}
    for stem, value in bitmasks.items():
        parts = stem.split("_")
        for i in range(1, len(parts)):
            by_suffix.setdefault("_".join(parts[i:]), []).append((stem, value))
    matched = mismatched = 0
    for f in fields:
        path = [p.replace("[0]", "") for p in f["path"]] + [f["register"]]
        bitpos, bits, name, source = f["bitpos"], f["bits"], f["field"], f["source"]
        mask = ((1 << bits) - 1) << bitpos
        candidates = by_suffix.get("_".join(path + [name]), [])
        if not candidates:
            continue
        if any(value == (bitpos, mask) for _, value in candidates):
            matched += 1
            continue
        mismatched += 1
        stem, (pos, msk) = candidates[0]
        warnings.append("%s: field %s.%s at [%d..%d] but %s_Pos/_Msk give %d/0x%X"
                        % (source, ".".join(path), name, bitpos + bits - 1, bitpos, stem, pos, msk))
    return matched, mismatched


def umbrella_includes(path, pattern):
    return re.findall(r'#\s*include\s+"(%s)"' % pattern, path.read_text())


def cpu_element(root, device_header, num_interrupts):
    """Add <cpu> from the BSP_SUPPORT_CORE_CR8 block of the device header."""
    m = re.search(r"#\s*elif\s+defined\(BSP_SUPPORT_CORE_CR8\)(.*?)#\s*endif", device_header.read_text(), re.S)
    defines = dict(re.findall(r"#\s*define\s+(__\w+)\s+(\w+)", m.group(1))) if m else {}
    missing = [d for d in CPU_DEFINES if d not in defines]
    if missing:
        raise HeaderError("%s: CR8 core block lacks %s" % (device_header, ", ".join(missing)))
    value = {d: int(defines[d].rstrip("uUlL"), 0) for d in CPU_DEFINES}
    flag = lambda d: "true" if value[d] else "false"  # noqa: E731
    cpu = ET.SubElement(root, "cpu")
    # The schema has no Cortex-R names; "other" plus the revision and the flags below.
    for tag, text in (("name", "other"), ("revision", CPU_REVISION), ("endian", "little"),
                      ("mpuPresent", flag("__MPU_PRESENT")), ("fpuPresent", flag("__FPU_PRESENT")),
                      ("fpuDP", flag("__FPU_DP")), ("nvicPrioBits", str(value["__NVIC_PRIO_BITS"])),
                      ("vendorSystickConfig", flag("__Vendor_SysTickConfig")),
                      ("deviceNumInterrupts", str(num_interrupts))):
        ET.SubElement(cpu, tag).text = text


def load_interrupts(path, warnings):
    """Return [(name, GIC SPI number, description)] from the IRQn_Type enum."""
    text = path.read_text()
    start, end = text.find("typedef enum IRQn"), text.find("} IRQn_Type")
    if start < 0 or end < start:
        raise HeaderError("%s: no IRQn_Type enum" % path)
    interrupts = []
    for name, number, comment in IRQ_RE.findall(text[start:end]):
        description = comment or name
        cm = IRQ_COMMENT_RE.match(description)
        if cm:
            if int(cm.group(1)) != int(number):
                warnings.append("%s: %s_IRQn = %s but its comment says IRQ %s" % (path.name, name, number, cm.group(1)))
            description = cm.group(2) or name
        interrupts.append((name, int(number), description))
    return interrupts


def interrupt_peripheral(stem, names):
    for pattern, template in IRQ_RULES:
        m = re.match(pattern, stem)
        if m:
            return m.expand(template)
    tokens = stem.split("_")
    for k in range(len(tokens) - 1, 0, -1):
        if "R_" + "_".join(tokens[:k]) in names:
            return "R_" + "_".join(tokens[:k])
    return None


def add_interrupts(peripherals, interrupts, errors):
    """Insert <interrupt> elements before each peripheral's <registers> (schema order)."""
    elements = {p.findtext("name"): p for p in peripherals}
    seen = {}
    for name, number, description in sorted(interrupts, key=lambda i: i[1]):
        if number in seen:
            errors.append("IRQ %d is both %s and %s" % (number, seen[number], name))
            continue
        seen[number] = name
        owner = interrupt_peripheral(name, elements)
        if owner not in elements:
            errors.append("%s_IRQn (%d): no peripheral %s; extend IRQ_RULES" % (name, number, owner or "matches"))
            continue
        p = elements[owner]
        irq = ET.Element("interrupt")
        for tag, text in (("name", name), ("description", description), ("value", str(number))):
            ET.SubElement(irq, tag).text = text
        registers = p.find("registers")
        p.insert(list(p).index(registers) if registers is not None else len(p), irq)


def generate(include_dir, apply_errata=True):
    """Return (SVD text, warnings, stats, fields) for the FSP include directory."""
    errata = {(t, r): v for t, regs in ERRATA.items() for r, v in regs.items()} if apply_errata else {}
    errata_used = set()
    device_header = include_dir / ("%s.h" % DEVICE)
    m = re.search(r'defined\(BSP_SUPPORT_CORE_CR8\)\s*#\s*include\s+"(%s/cr/iodefine\.h)"' % DEVICE,
                  device_header.read_text())
    if not m:
        raise HeaderError("%s: no CR8 iodefine include" % device_header)
    iodefine_umbrella = include_dir / m.group(1)
    bitmask_includes = umbrella_includes(device_header, r"%s/iobitmask\.h" % DEVICE)
    if not bitmask_includes:
        raise HeaderError("%s: no iobitmask.h include" % device_header)
    bitmask_umbrella = include_dir / bitmask_includes[0]
    bitmask_files = {Path(p).name.replace("_iobitmask.h", ""): bitmask_umbrella.parent / p
                     for p in umbrella_includes(bitmask_umbrella, r"[^\"]+_iobitmask\.h")}

    irq_header = include_dir.parents[3] / IRQ_HEADER
    if not irq_header.is_file():
        raise HeaderError("%s not found (expected next to the cmsis/ tree)" % irq_header)

    warnings, errors, all_fields = [], [], []
    interrupts = load_interrupts(irq_header, warnings)
    if not interrupts:
        raise HeaderError("%s: IRQn_Type has no interrupts" % irq_header)
    _, _, umbrella_meta = HeaderParser(iodefine_umbrella).parse()
    root = ET.Element("device", {
        "xmlns:xs": "http://www.w3.org/2001/XMLSchema-instance",
        "schemaVersion": "1.3",
        "xs:noNamespaceSchemaLocation": "CMSIS-SVD.xsd",
    })
    for tag, text in (("vendor", "Renesas Electronics"), ("name", DEVICE),
                      ("version", umbrella_meta["Version"] or "1.00"),
                      ("description", DEVICE_DESCRIPTION)):
        ET.SubElement(root, tag).text = text
    cpu_element(root, device_header, max(number for _, number, _ in interrupts) + 1)
    for tag, text in (("addressUnitBits", "8"), ("width", "32"), ("size", "32"), ("access", "read-write"),
                      ("resetValue", "0x00000000"), ("resetMask", "0x00000000")):
        ET.SubElement(root, tag).text = text
    peripherals = ET.SubElement(root, "peripherals")

    stats = {"headers": 0, "peripherals": 0, "derived": 0, "registers": 0, "interrupts": len(interrupts),
             "fields_checked": 0, "fields_mismatched": 0, "errata": 0}
    for rel in umbrella_includes(iodefine_umbrella, r"[^\"]+_iodefine\.h"):
        path = iodefine_umbrella.parent / rel
        typedefs_list, instances, meta = HeaderParser(path).parse()
        typedefs = {t.name: t for t in typedefs_list}
        layout = Layout(typedefs)
        for t in typedefs_list:
            layout.layout(t.agg)
            sm = re.match(r"Size = (\d+)", t.size_doc or "")
            if sm and int(sm.group(1)) != t.agg.size:
                warnings.append("%s: %s laid out as %d bytes, comment says %s"
                                % (path.name, t.name, t.agg.size, sm.group(1)))
        stem = path.name.replace("_iodefine.h", "")
        emitter = Emitter(typedefs, warnings, errata)
        first_of_type = {}
        stats["headers"] += 1
        for name, type_name, base in instances:
            if type_name not in typedefs:
                raise HeaderError("%s: %s uses unknown type %s" % (path, name, type_name))
            p = ET.SubElement(peripherals, "peripheral")
            if type_name in first_of_type:
                p.set("derivedFrom", first_of_type[type_name])
                ET.SubElement(p, "name").text = name
                ET.SubElement(p, "baseAddress").text = "0x%08X" % base
                stats["derived"] += 1
                continue
            first_of_type[type_name] = name
            typedef = typedefs[type_name]
            ET.SubElement(p, "name").text = name
            ET.SubElement(p, "version").text = meta["Version"] or "1.00"
            ET.SubElement(p, "description").text = meta["Description"] or name
            ET.SubElement(p, "groupName").text = stem.upper()
            ET.SubElement(p, "baseAddress").text = "0x%08X" % base
            block = ET.SubElement(p, "addressBlock")
            ET.SubElement(block, "offset").text = "0x0"
            ET.SubElement(block, "size").text = "0x%X" % typedef.agg.size
            ET.SubElement(block, "usage").text = "registers"
            registers = ET.SubElement(p, "registers")
            emitter.peripheral = name
            emitter.members(typedef, typedef.agg, 0, registers, [])
            check_unique_names(registers, name, errors)
            stats["peripherals"] += 1
            stats["registers"] += sum(1 for _ in registers.iter("register"))
        errata_used |= emitter.errata_used
        stats["errata"] += emitter.errata_applied
        all_fields.extend(emitter.fields)
        if stem in bitmask_files:
            matched, mismatched = crosscheck_bitmasks(emitter.fields, load_bitmasks(bitmask_files[stem]),
                                                      warnings)
            stats["fields_checked"] += matched + mismatched
            stats["fields_mismatched"] += mismatched
        else:
            warnings.append("%s: no matching iobitmask header" % path.name)
    add_interrupts(peripherals, interrupts, errors)
    for typedef, register in sorted(set(errata) - errata_used):
        errors.append("erratum %s.%s matched no register; re-check ERRATA" % (typedef, register))
    if errors:
        raise HeaderError("\n".join(errors))

    ET.indent(root, space="  ")
    source = iodefine_umbrella.relative_to(ROOT) if iodefine_umbrella.is_relative_to(ROOT) else iodefine_umbrella
    text = ("<?xml version='1.0' encoding='utf-8'?>\n"
            "<!-- Generated by generate-rzv2h-svd.py from %s%s. Do not edit; rerun the script. -->\n"
            % (source, " with %d register offset errata" % stats["errata"] if stats["errata"] else "")) + ET.tostring(root, encoding="unicode") + "\n"
    return text, warnings, stats, all_fields


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--include-dir", type=Path, default=DEFAULT_INCLUDE,
                        help="FSP CMSIS Device/RENESAS/Include directory (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                        help="SVD file to write or check (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 when the output differs from the headers")
    parser.add_argument("--no-errata", action="store_true",
                        help="emit the header layout as-is, without the ERRATA offset corrections")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every warning")
    args = parser.parse_args()

    include_dir = args.include_dir.resolve()
    if not (include_dir / ("%s.h" % DEVICE)).is_file():
        print("error: %s/%s.h not found (refs/ is local-only; pass --include-dir)" % (include_dir, DEVICE),
              file=sys.stderr)
        return 2
    try:
        text, warnings, stats, _ = generate(include_dir, apply_errata=not args.no_errata)
    except HeaderError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    if args.verbose:
        for warning in warnings:
            print("warning: " + warning, file=sys.stderr)
    print("%(headers)d headers, %(peripherals)d peripherals (+%(derived)d derived), %(registers)d registers, "
          "%(interrupts)d interrupts; "
          "%(fields_checked)d fields cross-checked against iobitmask, %(fields_mismatched)d mismatched; "
          "%(errata)d register offset errata applied" % stats,
          file=sys.stderr)
    if warnings and not args.verbose:
        print("%d warnings (rerun with -v to list them)" % len(warnings), file=sys.stderr)

    if args.check:
        current = args.output.read_text() if args.output.is_file() else None
        if current != text:
            print("%s is stale; rerun %s" % (args.output, Path(__file__).name), file=sys.stderr)
            return 1
        print("%s is up to date" % args.output, file=sys.stderr)
        return 0
    args.output.write_text(text)
    print("wrote %s" % args.output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
