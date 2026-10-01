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
| Configs | `canfd` (CH0, `/dev/can0`), `canfd-dual` (CH0 + CH1) — SCI4 console |

Build: `platforms/nuttx/NuttX/build.sh canfd`. The configs enable
`CONFIG_CAN`, `CONFIG_CAN_FD`, `CONFIG_RZV_CANFD`, `CONFIG_RZV_CANFD0`
(`CONFIG_RZV_CANFD1` in `canfd-dual`) and `apps/examples/can`.

## Device / Channel / Pin Map

| Device | Kconfig | Driver channel | RDK label | Pins (PSEL=5) |
|--------|---------|----------------|-----------|---------------|
| `/dev/can0` | `CONFIG_RZV_CANFD0` | 0 | CAN1 | P80 TX (CTX0), P81 RX (CRX0) |
| `/dev/can1` | `CONFIG_RZV_CANFD1` | 1 | CAN2 | P86 TX (**CTX3**), P87 RX (**CRX3**) |

**Open:** chip pin mux (`refs/rzv2h_scripts/rzv2h_pin_mapping.csv`, PSEL=5)
puts CTX3/CRX3 on P86/P87 and CTX1/CRX1 on P82/P83, but
`g_rzv_canfd1_config` uses `.channel = 1` with `RZV_ELC_CANFD_CH1_*`. Either
the pins should be P82/P83, or `/dev/can1` should drive channel 3. The RDK
`pin_data.c` (`refs/px4-freertos-posix-renesas-fsp/rzv_gen/`) configures no
CAN pins, and the EVK `can_fd` samples are a different board, so only the RDK
schematic (which SoC pins reach the "CAN2" connector) can settle it. Internal
loopback does not exercise the pins.

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

- Boot default: internal loopback (`.loopback = true`; CTME=1, INT_LOOP).
- Toggle with the private ioctl `CANIOC_RZV_LOOPBACK`
  (`_CANIOC(CAN_FIRST + CAN_NCMDS + 0)`).

## Evidence

| Item | State |
|------|-------|
| CAN0 internal loopback, 4 frames, IDs/DLCs/payloads match via `/dev/can0` | PASS, J-Link/GDB + RTT, 2026-08-09 |
| External bus (transceiver, termination, analyzer) | open |
| CAN1 (`/dev/can1`), including the channel/pin mismatch above | open |
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
