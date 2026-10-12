# SDHI Peripheral Notes

**Date:** 2026-10-01
**Hardware:** Renesas RZ/V2H (R9A09G057H), RDK-RZ/V2H
**Status:** build-clean, no target evidence. Authoritative row: [port-status-nuttx.md](../port-status-nuttx.md) #35.

Source-verified notes for `rzv_sdhi.c`. SDHI/ULog is post-G9 and does not
gate the first PX4 run. Audit:
[audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md](../../../plans/reports/audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md).

---

## Files

| What | Path (under `platforms/nuttx/NuttX/nuttx/`) |
|------|------|
| Arch driver (SDIO lower half) | `arch/arm/src/rzv/rzv_sdhi.c`, `rzv_sdhi.h` |
| Register defs | `arch/arm/src/rzv/hardware/rzv_sdhi.h` |
| Board glue | `boards/arm/rzv/rdk-rzv2h/src/rzv2h_sdhi.c` (`rzv2h_sdhi_initialize()`, called from `rzv2h_bringup.c`) |
| Config | `sdhi` — `CONFIG_RZV_SDHI`, `CONFIG_MMCSD`, `CONFIG_MMCSD_SDIO`, `CONFIG_FS_FAT`; SCI4 console |

Build: `platforms/nuttx/NuttX/build.sh sdhi`.

Bring-up path: `rzv_sdhi_initialize(0)` → `mmcsd_slotinitialize(0, sdio)` →
`/dev/mmcsd0`. Mount (untested on target):

```
nsh> mount -t vfat /dev/mmcsd0 /mnt/sd
```

## Instances

| Slot | Base | Use |
|------|------|-----|
| SD0 | `0x15C00000` | RDK microSD connector (QSD0_*), the only slot the board registers |
| SD1 | `0x15C10000` | not wired by the board code |
| SD2 | `0x15C20000` | not wired by the board code |

## Pins

SD0 uses **dedicated I/O pins** (FSP encoding `0xFFFF09xx`/`0xFFFF0Axx`), not
PORT/PSEL-muxed IOs. Boot firmware configures them; NuttX does not.

| Signal | Ball | FSP pin ID |
|--------|------|------------|
| SD0CLK | AN37 | 0xFFFF0900 |
| SD0CMD | AN36 | 0xFFFF0901 |
| SD0DAT0 | AP35 | 0xFFFF0A00 |
| SD0DAT1 | AN35 | 0xFFFF0A01 |
| SD0DAT2 | AP37 | 0xFFFF0A02 |
| SD0DAT3 | AR37 | 0xFFFF0A03 |

Card detect is in the controller (`SD_INFO1.SDCDIN`, bit 3), read by
`rzv_sdhi_status()`. There is no card-detect GPIO and no separate CD interrupt.

## Clock and Reset

- `rzv_clock_enable_sdhi(slot)` gates IMCLK (SDHI0: CPG_CLKON_10 bit 3);
  `rzv_reset_release_sdhi(slot)` releases IXRST (RST domain 10 bit 7).
- IMCLK2/CLK_HS/ACLK are left to boot firmware by design.
- Driver assumes IMCLK = 200 MHz. SDCLK = (IMCLK / 4) / N:

| Request | DIV | SDCLK |
|---------|-----|-------|
| `CLOCK_IDMODE` | 1/128 | ~391 kHz |
| `CLOCK_SD_TRANSFER_1BIT` / `_4BIT` | 1/2 | 25 MHz |

Divider change follows the UM rule: wait `CBSY=0`, clear SCLKEN, write DIV,
set SCLKEN. No high-speed (50 MHz) or UHS modes.

## Data Path

- PIO only. `rzv_sdhi_capabilities()` returns `SDIO_CAPS_4BIT`; DMA is not
  advertised (`SDIO_CAPS_DMASUPPORTED` unset) and there is no DMAC channel.
- Bus width 1-bit (reset default) or 4-bit via `SD_OPTION.WIDTH1`. No 8-bit eMMC.

## Interrupts

One combined ISR, `rzv_sdhi_interrupt()`, on SD0 OXMNIRQ = GIC SPI 735 =
NuttX IRQ 767. It demuxes `SD_INFO1`/`SD_INFO2`: response end, access end,
PIO buffer read/write, errors, card insert/remove.

## Evidence

| Item | State |
|------|-------|
| Builds, registers `/dev/mmcsd0` | build-clean |
| Register readback, CMD0/CMD8/ACMD41 on target | open |
| PIO block read/write, FAT mount | open |
| PX4 ULog on SD | post-G9, not started ([port-status-px4-hal.md](../port-status-px4-hal.md)) |

## Reference Sources

There is **no** SDHI EVK sample and no FSP `r_sdhi` driver in `refs/`. Use
the checked-in CMSIS header, the hardware manual, and the legacy IRQ table
(`refs/rzv2h_gb_ether/include/rzv2h_irq.h`). Do not borrow DMA behavior from
the SPI-B `r_dmac_b` example. See [reference-source-map.md](../reference-source-map.md).

## Related

- [validation-checklist.md](../validation/validation-checklist.md)
