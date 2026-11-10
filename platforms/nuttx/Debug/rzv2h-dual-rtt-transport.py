#!/usr/bin/env python3
"""RTT over the RZ/V2H AXI-AP: raw J-Link DAP access and RTT ring arithmetic.

One J-Link session reads and writes both CR8 RTT control blocks over the
system bus (AP1, the AXI-AP) with no core connect: no stop-mode halt, and no
connect/reset sequence that could reset the SoC. The bridge
(`rzv2h-dual-rtt-bridge.py`) drives this module; tests drive the ring logic
against a fake word memory.

Rules from the board gate (docs/renesas/evidence/dual-rtt-single-probe-axi-ap-gate-261110.md):
- MEM-AP TAR auto-increment only holds inside a 1 KiB block: reprogram TAR at
  every boundary or reads return stale data.
- Keep the AXI-AP CSW protection bits (0x10806052).
- Check DP CTRL/STAT for debug and system power before any AP access, and
  never touch memory again after a failed connect or a DAP error.
"""
from __future__ import annotations

import ctypes

JLINK_DLL = "/opt/SEGGER/JLink/libjlinkarm.so"
# The DLL calls used here were qualified on V8.94; older DLLs are refused.
MIN_DLL_VERSION = 89400
AP_SELECT = 0x01000000          # DP SELECT: AP1 (AXI-AP), bank 0
AXI_AP_CSW = 0x10806052         # original prot bits, 32-bit, single increment
TAR_BLOCK = 0x400
DP_CTRL_STAT, DP_SELECT = 1, 2
AP_CSW, AP_TAR, AP_DRW = 0, 1, 3
POWER_ACK = 0xA0000000          # CSYSPWRUPACK | CDBGPWRUPACK
STICKY = 0x32                   # STICKYERR | STICKYCMP | STICKYORUN
RTT_ID = b"SEGGER RTT"


class DapError(Exception):
    """The DAP refused an access or lost power. Stop: no retry, no memory access."""


class ConnectError(DapError):
    """The probe session never came up; nothing was written to the target."""


def tar_chunks(addr: int, words: int):
    """Splits a word read at 1 KiB TAR boundaries: yields (address, count)."""
    while words:
        count = min(words, (TAR_BLOCK - (addr & (TAR_BLOCK - 1))) // 4)
        yield addr, count
        addr += count * 4
        words -= count


class WordMemory:
    """Byte access on top of `read_words(addr, n)` / `write_word(addr, value)`."""

    def read_words(self, addr: int, count: int) -> list[int]:
        raise NotImplementedError

    def write_word(self, addr: int, value: int) -> None:
        raise NotImplementedError

    def check(self) -> None:
        """Raises DapError when the memory path faulted; a fake never does."""

    def close(self) -> None:
        """Releases the probe session."""

    def read_bytes(self, addr: int, size: int) -> bytes:
        if size <= 0:
            return b""
        base = addr & ~3
        words = self.read_words(base, (addr - base + size + 3) // 4)
        raw = b"".join(word.to_bytes(4, "little") for word in words)
        return raw[addr - base: addr - base + size]

    def write_bytes(self, addr: int, data: bytes) -> None:
        # Read-modify-write whole words so partial words keep their neighbours.
        base = addr & ~3
        span = (addr - base + len(data) + 3) // 4 * 4
        current = bytearray(self.read_bytes(base, span))
        current[addr - base: addr - base + len(data)] = data
        for offset in range(0, span, 4):
            self.write_word(base + offset, int.from_bytes(current[offset:offset + 4], "little"))


class AxiApMemory(WordMemory):
    """J-Link DLL session on the AXI-AP of one probe (raw DAP, no core connect)."""

    def __init__(self, serial: int, speed_khz: int = 4000, dll_path: str = JLINK_DLL):
        self.dll = ctypes.CDLL(dll_path)
        self.dll.JLINKARM_OpenEx.restype = ctypes.c_char_p
        self.open = False
        self.version = int(self.dll.JLINKARM_GetDLLVersion())
        if self.version < MIN_DLL_VERSION:
            raise ConnectError(f"J-Link DLL {self.version} is older than the qualified V8.94 ({MIN_DLL_VERSION})")
        if self.dll.JLINKARM_EMU_SelectByUSBSN(int(serial)) < 0:
            raise ConnectError(f"J-Link {serial} not found")
        error = self.dll.JLINKARM_OpenEx(None, None)
        if error:
            raise ConnectError(f"J-Link open failed: {error.decode(errors='replace')}")
        self.open = True
        self.dll.JLINKARM_TIF_Select(1)  # SWD
        self.dll.JLINKARM_SetSpeed(int(speed_khz))
        if self.dll.JLINKARM_CORESIGHT_Configure(b"") < 0:
            raise ConnectError("CoreSight DAP configure failed")
        stat = self._reg_read(DP_CTRL_STAT, 0)
        if stat & POWER_ACK != POWER_ACK:
            raise ConnectError(f"debug/system power not up (CTRL/STAT=0x{stat:08x})")
        self._reg_write(DP_SELECT, 0, AP_SELECT)
        self._reg_write(AP_CSW, 1, AXI_AP_CSW)
        if self._reg_read(AP_CSW, 1) != AXI_AP_CSW:
            raise ConnectError("AXI-AP CSW did not take")

    def _reg_read(self, reg: int, ap: int) -> int:
        value = ctypes.c_uint32()
        if self.dll.JLINKARM_CORESIGHT_ReadAPDPReg(reg, ap, ctypes.byref(value)) < 0:
            raise DapError(f"{'AP' if ap else 'DP'} read {reg} failed")
        return value.value

    def _reg_write(self, reg: int, ap: int, value: int) -> None:
        if self.dll.JLINKARM_CORESIGHT_WriteAPDPReg(reg, ap, ctypes.c_uint32(value)) < 0:
            raise DapError(f"{'AP' if ap else 'DP'} write {reg} failed")

    def read_words(self, addr: int, count: int) -> list[int]:
        out: list[int] = []
        for start, words in tar_chunks(addr, count):
            self._reg_write(AP_TAR, 1, start)
            out += [self._reg_read(AP_DRW, 1) for _ in range(words)]
        return out

    def write_word(self, addr: int, value: int) -> None:
        self._reg_write(AP_TAR, 1, addr)
        self._reg_write(AP_DRW, 1, value)

    def check(self) -> None:
        """Once per poll cycle: power still up and no sticky DAP error."""
        stat = self._reg_read(DP_CTRL_STAT, 0)
        if stat & POWER_ACK != POWER_ACK or stat & STICKY:
            raise DapError(f"DAP fault (CTRL/STAT=0x{stat:08x})")

    def close(self) -> None:
        if self.open:
            self.open = False
            self.dll.JLINKARM_Close()


class RttChannel:
    """Up/down buffer 0 of one control block; the target owns WrOff (up) and RdOff (down)."""

    def __init__(self, memory: WordMemory, name: str, control_block: int, drop_counter: int | None = None):
        self.memory, self.name = memory, name
        ident = memory.read_bytes(control_block, 16)
        if not ident.startswith(RTT_ID):
            raise ValueError(f"{name}: no RTT control block at 0x{control_block:08x}")
        up_count, down_count = memory.read_words(control_block + 0x10, 2)
        if not up_count or not down_count:
            raise ValueError(f"{name}: control block has no up or down buffer")
        self.up = control_block + 0x18
        self.down = self.up + up_count * 24
        _, self.up_buffer, self.up_size, _, _, _ = memory.read_words(self.up, 6)
        _, self.down_buffer, self.down_size, _, _, _ = memory.read_words(self.down, 6)
        if not self.up_size or not self.down_size:
            raise ValueError(f"{name}: RTT buffer 0 has no storage")
        self.control_block = control_block
        self.layout = (self.up_buffer, self.up_size, self.down_buffer, self.down_size)
        self.drop_counter = drop_counter
        self.drop_base = self.dropped_total() if drop_counter is not None else None

    def verify(self) -> None:
        """A reload rewrites the control block: the ID and buffer layout must still match."""
        ident = self.memory.read_bytes(self.control_block, 16)
        _, up_buffer, up_size, _, _, _ = self.memory.read_words(self.up, 6)
        _, down_buffer, down_size, _, _, _ = self.memory.read_words(self.down, 6)
        if not ident.startswith(RTT_ID) or (up_buffer, up_size, down_buffer, down_size) != self.layout:
            raise ValueError(f"{self.name}: RTT control block changed (image reloaded?)")

    def read(self) -> bytes:
        """Drains the up buffer, then hands the space back by writing RdOff."""
        write, read = self.memory.read_words(self.up + 12, 2)
        if write >= self.up_size or read >= self.up_size:
            raise ValueError(f"{self.name}: up buffer offsets out of range ({write}, {read})")
        if write == read:
            return b""
        if write > read:
            data = self.memory.read_bytes(self.up_buffer + read, write - read)
        else:
            data = (self.memory.read_bytes(self.up_buffer + read, self.up_size - read) +
                    self.memory.read_bytes(self.up_buffer, write))
        self.memory.write_word(self.up + 16, write)
        return data

    def free(self) -> int:
        write, read = self.memory.read_words(self.down + 12, 2)
        return (read - write - 1) % self.down_size

    def write(self, data: bytes) -> int:
        """Writes what fits in the down buffer; returns the bytes taken."""
        write, read = self.memory.read_words(self.down + 12, 2)
        if write >= self.down_size or read >= self.down_size:
            raise ValueError(f"{self.name}: down buffer offsets out of range ({write}, {read})")
        data = data[:(read - write - 1) % self.down_size]
        if not data:
            return 0
        first = min(len(data), self.down_size - write)
        self.memory.write_bytes(self.down_buffer + write, data[:first])
        if first < len(data):
            self.memory.write_bytes(self.down_buffer, data[first:])
        # WrOff last: the target must never see bytes that are not there yet.
        self.memory.write_word(self.down + 12, (write + len(data)) % self.down_size)
        return len(data)

    def dropped_total(self) -> int:
        return self.memory.read_words(self.drop_counter, 1)[0] if self.drop_counter is not None else 0

    def dropped_since_attach(self) -> int | None:
        """The counter is not zeroed at boot, so report the change since attach."""
        if self.drop_counter is None:
            return None
        return (self.dropped_total() - self.drop_base) & 0xFFFFFFFF
