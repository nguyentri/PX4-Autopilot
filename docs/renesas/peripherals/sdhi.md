# SDHI Peripheral Notes

**Date:** 2026-10-24
**Hardware:** Renesas RZ/V2H (R9A09G057H), RDK-RZ/V2H
**Status:** bounded controller-only checks on all three channels; media transfers untested. Authoritative row: [port-status-nuttx.md](../port-status-nuttx.md) #35.

The current lower half is CR8-only; CM33 selection is disabled because its
address and NVIC routing path is not implemented. No SDHI I/O header exists
in the supplied per-core corpus, so the SD register layout uses the HWM as
the documented fallback authority.

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
| Config | `sdhi` — `CONFIG_RZV_SDHI`, `CONFIG_MMCSD`, `CONFIG_MMCSD_SDIO`, `CONFIG_FS_FAT`; serial console (SCI5) |

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

The controller-only `sdhi0-board-rtt` through `sdhi2-board-rtt` profiles inspect
each selected instance without binding/probing media. They require a declared
clock/pad handoff and do not change the ordinary board's SD0-only binding.

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

Card detect is in the controller. `rzv_sdhi_status()` reports presence from
the `SD_INFO1.SDCD` state bit (bit 5); `SDCDIN`/`SDCDRM` (bits 4/3) are only
insert/remove latches. There is no card-detect GPIO, no debounce and no
media-change callback yet.

## Clock and Reset

- `rzv_clock_enable_sdhi(slot)` gates IMCLK (SDHI0: CPG_CLKON_10 bit 3);
  `rzv_reset_release_sdhi(slot)` releases IXRST (RST domain 10 bit 7).
- The helper controls IMCLK/IMCLK2/CLK_HS/ACLK together. Parent-clock and
  pad-routing ownership remain with boot firmware.
- Driver assumes IMCLK = 200 MHz. SDCLK = (IMCLK / 4) / N:

| Request | DIV | SDCLK |
|---------|-----|-------|
| `CLOCK_IDMODE` | 1/128 | ~391 kHz |
| `CLOCK_SD_TRANSFER_1BIT` / `_4BIT` | 1/2 | 25 MHz |

Divider change follows the UM rule: wait `CBSY=0` and `SCLKDIVEN=1`, clear
SCLKEN, write DIV with SCLKEN clear, then set SCLKEN. A busy or locked
controller leaves `SD_CLK_CTRL` unchanged; `widebus()` also waits `CBSY=0`
before writing `SD_OPTION`. No high-speed (50 MHz) or UHS modes.

## Data Path

- PIO only. `rzv_sdhi_capabilities()` returns `SDIO_CAPS_4BIT |
  SDIO_CAPS_DMABEFOREWRITE`, so mmcsd arms the write buffer before CMD24/25.
  DMA is not advertised (`SDIO_CAPS_DMASUPPORTED` unset); no DMAC channel.
- Command and data phases are tracked separately. `sendcmd()` arms RSPEND and
  errors; `waitresponse()` waits at most 500 ms. `recvsetup()`/`sendsetup()`
  arm BRE/BWE, ACEND and errors; `eventwait()` waits the caller timeout plus
  100 ms, or 2 s when no timeout was requested.
- `SD_CMD` carries the response type (MD2:0), data/read/multi bits and
  MD7:6=01 (no auto CMD12; mmcsd sends CMD12). Multi-block transfers program
  `SD_SECCNT` and `SD_STOP.SEC`; single blocks clear `SD_STOP`. `SD_SIZE`
  follows the transfer (8 bytes for the SCR read, 512 otherwise).
- Each BRE/BWE clears its flag first, then moves exactly one `SD_SIZE` block
  through `SD_BUF0`. Overflow or a short transfer at ACEND reports an error.
  Stale ACEND/BRE/BWE latches are cleared before a transfer is unmasked.
- R2 responses are shifted by 8 bits so `R2[0]` holds R[127:96].
- Recovery: a command timeout pulses `SOFT_RST.SDRST` and restores
  `SD_OPTION`, `SD_CLK_CTRL` and `SD_SIZE`. `cancel()` releases both the
  command and the data waiter once with `SDIOWAIT_ERROR` and masks all
  sources. Completion that lands just after a timeout is still returned.
- Bus width 1-bit (reset default) or 4-bit via `SD_OPTION.WIDTH1`. No 8-bit eMMC.

## Interrupts

One combined ISR, `rzv_sdhi_interrupt()`, per slot. The OXMN source is an
ICU selectable event: `rzv_icu_attach(RZV_IRQSEL_SDHI_OXMN(slot), ...)`
with `RZV_IRQSEL_SDHI_OXMN(n) = 392 + 2n`, and the ICU allocates the NuttX
IRQ. The ISR services only the currently enabled `SD_INFO1`/`SD_INFO2`
sources: response end, access end, PIO buffer read/write and errors.

## Evidence

| Item | State |
|------|-------|
| Builds, registers `/dev/mmcsd0` | build-clean |
| Controller identities SDHI0/1/2 and idle cancellation | bounded on-target; [transcript matrix](../evidence/sensor-free-rtt-matrix-261024.json) |
| Command encoding, PIO block/multi-block, SCR, timeout/cancel recovery | host-tested against a register model ([command/data test](../../../test/rzv2h-sdhi-command-data-runtime-test.py)) |
| CMD0/CMD8/ACMD41 on target | open |
| PIO block read/write, FAT mount | open |
| PX4 ULog on SD | post-G9, not started ([port-status-px4-hal.md](../port-status-px4-hal.md)) |

The sample snapshot checks implemented interrupt-mask bits. Reserved bits do
not read back as all ones: CPU reads after idle cancellation were
`SD_INFO1_MASK=0x0001031d`, `SD_INFO2_MASK=0x00008b7f`. This evidence does not
qualify command, transfer or media behavior.

## Reference Sources

There is **no** SDHI EVK sample and no FSP `r_sdhi` driver in `refs/`. Use
the checked-in CMSIS header, the hardware manual, and the legacy IRQ table
(`refs/rzv2h_gb_ether/include/rzv2h_irq.h`). Do not borrow DMA behavior from
the SPI-B `r_dmac_b` example. See [reference-source-map.md](../reference-source-map.md).

## Related

- [validation-checklist.md](../validation/validation-checklist.md)
