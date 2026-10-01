# CAN-FD Peripheral Notes

**Date:** 2026-10-01
**Hardware:** Renesas RZ/V2H (R9A09G057H), RDK-RZ/V2H
**Status:** bounded on-target (CAN0 internal loopback). Authoritative row: [port-status-nuttx.md](../port-status-nuttx.md) #2.

Source-verified notes for `rzv_canfd.c`. Facts below are taken from the
NuttX source; anything not in source is marked open.

---

## Files

| What | Path (under `platforms/nuttx/NuttX/nuttx/`) |
|------|------|
| Arch driver | `arch/arm/src/rzv/rzv_canfd.c`, `rzv_canfd.h` |
| Register defs | `arch/arm/src/rzv/hardware/rzv_canfd.h` |
| Board glue | `boards/arm/rzv/rdk-rzv2h/src/rzv2h_canfd.c` (`board_canfd_initialize()`, called from `rzv2h_bringup.c`) |
| Pins | `boards/arm/rzv/rdk-rzv2h/include/board.h` (`BOARD_CANFD{0,1}_{TX,RX}_GPIO`) |
| Configs | `canfd` (CH0, `/dev/can0`), `canfd-dual` (CH0 + CH1), `canfd-ext` (CH0 + CH1, loopback off, external-bus test) — SCI4 console |

Build: `platforms/nuttx/NuttX/build.sh canfd`. The configs enable
`CONFIG_CAN`, `CONFIG_CAN_FD`, `CONFIG_RZV_CANFD`, `CONFIG_RZV_CANFD0`
(`CONFIG_RZV_CANFD1` in `canfd-dual`) and `apps/examples/can`.

## Device / Channel / Pin Map

| Device | Kconfig | Driver channel | RDK label | Pins (PSEL=5) |
|--------|---------|----------------|-----------|---------------|
| `/dev/can0` | `CONFIG_RZV_CANFD0` | 0 | CAN1 | P80 TX (CTX0), P81 RX (CRX0) |
| `/dev/can1` | `CONFIG_RZV_CANFD1` | 1 | CAN2 | P82 TX (CTX1), P83 RX (CRX1) |

P82/P83 are shared with SCI9 (GPS M10). `rzv2h_canfd.c` stops the build with
`#error` if `CONFIG_RZV_CANFD1` and `CONFIG_RZV_SCI9` are both set. CAN2 →
P82/P83 is confirmed from the RDK schematic (2026-10-01); before that the board
used P86/P87, which carry CTX3/CRX3 (channel 3), not channel 1.

## Register Block

- Base `RZV_CANFD_BASE` = `0x12440000` (one controller, per-channel CFDC
  blocks at stride `0x10`, global registers from `0x80`).
- TX buffer access window is `BASE + 0x10000` (corrected 2026-08-09).
- Decode with `platforms/nuttx/Debug/svd_register_tool.py --svd rzv2h.svd`.

## Clock and Bit Timing

- `rzv_clock_enable(RZV_CPG_CLK_CANFD)` + `rzv_module_unreset()` in the driver.
- Constants assume CANFDCLK = 80 MHz (not read back from CPG):

| Phase | Bitrate | BRP | TSEG1 | TSEG2 | SJW | Tq per bit |
|-------|---------|-----|-------|-------|-----|------------|
| Nominal | 400 kbit/s | 2 | 74 | 25 | 25 | 100 (1 + 74 + 25) |
| Data | 3.2 Mbit/s | 1 | 16 | 8 | 8 | 25 (1 + 16 + 8) |

Bitrate = CANFDCLK / (BRP × (1 + TSEG1 + TSEG2)). Registers hold field − 1.
Bitrates are compile-time constants; there is no runtime bitrate ioctl.

## Interrupts

All CAN-FD events are **selectable ICU routes** attached with
`rzv_icu_attach()`; there are no fixed IRQ numbers.

| Event | ELC source |
|-------|------------|
| Global error (shared) | `RZV_ELC_CANFD_GLERR` |
| RX FIFO (shared) | `RZV_ELC_CANFD_RXFINT` |
| Per-channel TX / error | `RZV_ELC_CANFD_CHn_TRX`, `RZV_ELC_CANFD_CHn_ERR` |

Loopback completion is serviced synchronously in the driver because late
selectable-ICU route writes did not latch on target. Interrupt-driven
completion is an open gate.

No DMA path exists.

## Modes

- Boot default: internal loopback (CTME=1, INT_LOOP), set by
  `CONFIG_RZV_CANFD_BOOT_LOOPBACK` (default `y`). With `n` the channels
  start on the bus; `canfd-ext` does this.
- Toggle at run time with the private ioctl `CANIOC_RZV_LOOPBACK`
  (`_CANIOC(CAN_FIRST + CAN_NCMDS + 0)`; arg 0 = bus, 1 = loopback).
  `apps/examples/can` never issues it.
- Classic frames with DLC > 8 are rejected (`-EINVAL`); FD frames need
  `ch_edl` (and `ch_brs` for the 3.2 Mbit/s data phase).

## External-Bus Test (`/dev/can1`)

Not run yet. Proves CH1 pins, transceiver path, nominal bit timing, and the
interrupt-driven TX/RX completion that loopback bypasses.

**Hardware**

- CAN transceiver on CAN2 (P82 TX, P83 RX) and a 120 Ω terminator at each
  bus end. Whether the RDK fits transceivers/terminators on board is open;
  check the schematic before wiring.
- Analyzer (PCAN, Kvaser, ...) set to classic CAN, **400 kbit/s, sample point
  75 %**, in normal (ACKing) mode. A listen-only analyzer gives no ACK and
  the first frame retransmits forever, unless another node on the bus ACKs.
- Optional second node: wire CAN1 (`/dev/can0`, P80/P81) on the same bus.
  It also starts on the bus in `canfd-ext` and ACKs in hardware even if no
  task reads it.

**TX: board → analyzer**

1. Build: `platforms/nuttx/NuttX/build.sh canfd-ext`. The example writes 8
   standard-ID classic frames on `/dev/can1` and exits.
2. RAM-load `platforms/nuttx/NuttX/nuttx/nuttx` on CR8-0 (needs user
   approval for J-Link reset/load; see
   [deployment-guide.md](../../deployment-guide.md)). Console is SCI4.
3. `nsh> can`. Expected console: `Bit timing not available: 25` (the ioctl
   is not implemented), `nmsgs: 8`, then `ID:    1 DLC: 1` …
   `ID:    8 DLC: 8`, then `Terminating!`.
4. Expected on the analyzer: frame *k* (1–8) has ID `0x00k`, DLC *k*, data
   counting up from `sum(1..k-1)`. ID 1 = `00`; ID 2 = `01 02`; ID 3 =
   `03 04 05`; … ID 8 = `1C 1D … 23`.

**RX: analyzer → board**

```bash
cd platforms/nuttx/NuttX/nuttx
kconfig-tweak --file .config --disable EXAMPLES_CAN_WRITE --enable EXAMPLES_CAN_READ
make olddefconfig
cd .. && ./build.sh --no-clean canfd-ext
```

Load, run `nsh> can`, then send 8 standard frames at 400 kbit/s from the
analyzer. The console prints one `ID: … DLC: …` line per frame, followed by
`Data received:` and the bytes.

**Pass:** all 8 frames are seen on the analyzer with exact ID/DLC/data, and
all 8 analyzer frames are printed by the board. There must be no error
frames, and the board must not go bus-off. Record the transcript in the
Evidence table below and in [port-status-nuttx.md](../port-status-nuttx.md).

**Triage**

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| Console stops after `ID:    7`, `can` hangs on write 8; analyzer shows 7 frames | TX-complete interrupt never fires. Each `write()` still kicks the mailbox, but `can_txdone()` never frees the upper-half FIFO (`CAN_FIFOSIZE` 8 = 7 usable slots) | `CFDTMSTS16` (byte, `0x124407E0`): `TMTRF=TX_OK` with no ISR = ICU route not latched |
| Frame repeats on analyzer, `ACK error` | No node ACKs | Analyzer in normal mode, or add CAN1 node |
| Analyzer shows error frames / wrong bitrate | CANFDCLK ≠ 80 MHz, or a transceiver/termination fault | Scope bit time (2.5 µs); `R_CANFD.CFDC1.ERFL` (`0x1244001C`) |
| `can` blocks forever in RX | RX FIFO interrupt route not latched | `CFDRFSTS` message count > 0 with no ISR |
| Bus-off | Wiring, TX/RX swapped, missing termination | `R_CANFD.CFDC1.STS` (`0x12440018`) |

Decode with `platforms/nuttx/Debug/svd_register_tool.py cmd gdb
R_CANFD.CFDC1.STS R_CANFD.CFDC1.ERFL R_CANFD.CFDTMSTS16`. Reading registers
in a GDB session needs the RTT bridge stopped (one probe, one owner).

## Evidence

| Item | State |
|------|-------|
| CAN0 internal loopback, 4 frames, IDs/DLCs/payloads match via `/dev/can0` | PASS, J-Link/GDB + RTT, 2026-08-09 |
| External bus (transceiver, termination, analyzer) | open; procedure above |
| CAN1 (`/dev/can1`) on P82/P83, external bus | open (pins fixed, `canfd-ext` build-clean 2026-10-01) |
| Interrupt-driven TX/RX completion | open |
| PX4 `src/drivers/can/` / UAVCAN integration | planned ([port-status-px4-hal.md](../port-status-px4-hal.md)) |

## FSP Reference

Core-matched EVK sample: `refs/rzv2h_evk/can_fd/can_fd_rzv2h_evk_<core>_ep/`
(`<core>` = `cm33`, `cr8_0`, `cr8_1`). EVK board: use for IP behavior only,
not pins. Driver `rzv/fsp/src/r_canfd/`; config
in `configuration.xml`, `rzv_cfg/fsp_cfg/r_canfd_cfg.h`, `rzv_gen/`. See
[reference-source-map.md](../reference-source-map.md).

## Related

- [validation-checklist.md](../validation-checklist.md)
- [pinmap.md](../pinmap.md)
