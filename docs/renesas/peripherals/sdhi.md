# SDHI Peripheral Specification

**Date:** 2026-07-11  
**Hardware:** Renesas RZ/V2H (R9A09G057H)  
**Scope:** SD Host Interface (SDHI) controller block documentation for driver development.

---

## Hardware Block Overview

**Peripheral:** SD/MMC Host Interface controller for SD card and eMMC support.

**Instance on RDK-RZ/V2H:**
- SDHI0: Primary SD/MMC slot (mounted on carrier board)

---

## Slot Configuration

### SDHI0 Slot

**Card Slot Type:** SD v3.0 / eMMC support (mechanical slot with card-detect switch).

**Pin Assignments (RDK-RZV2H SD0):**

SD0 uses **dedicated I/O pins** on R9A09G057H (FSP encoding `0xFFFF09xx` /
`0xFFFF0Axx`), not normal PORT/PSEL-muxed IOs. They are configured by the boot
firmware (u-boot / TF-A) before NuttX starts; NuttX does not program them.

| Signal | Pin | FSP dedicated-pin ID |
|--------|-----|----------------------|
| SD0CLK  | AN37 | 0xFFFF0900 |
| SD0CMD  | AN36 | 0xFFFF0901 |
| SD0DAT0 | AP35 | 0xFFFF0A00 |
| SD0DAT1 | AN35 | 0xFFFF0A01 |
| SD0DAT2 | AP37 | 0xFFFF0A02 |
| SD0DAT3 | AR37 | 0xFFFF0A03 |

**Card Detect:** via the SDHI controller (`SD_INFO1.SDCDIN`, bit 3 = card
present), not a separate GPIO. See `rzv_sdhi_status()`.

**Verification:** Dedicated-pin IDs from `refs/rz-fsp-master bsp_override.h`;
card-detect path confirmed for RDK-RZV2H.

**Pull-ups:** Standard SDHI spec requires 50 kΩ pull-ups on data/cmd lines (typically on carrier board).

---

## Clock Source

**Peripheral Clock:** SDHI_CLK (from CPG module).

**Derivation:**
- Base clock: 200 MHz (typical for SDHI)
- Divisor stages: SDCLK divider (1/2, 1/4, 1/8, ... 1/512)
- Final frequency: SDHI_CLK / divisor

**Common Frequencies:**
- **Initialization:** 400 kHz (slow clock for ACMD41 discovery phase)
- **High-speed:** 50 MHz (SD v2 default)
- **UHS-I (future):** 104 MHz (if supported by controller and card)

**Clock switching:** Driver must adjust divisor during init sequence; verify divisor field in SDCLK_CTRL register.

---

## Interrupt Mapping

**Interrupt Controller:** ICU

| Event | NuttX INTID | GIC SPI | Handler |
|-------|-------------|---------|---------|
| SDHI0 CH0 OXMNIRQ (response/access/error/card-detect) | 767 | 735 | `rzv_sdhi_interrupt()` |

A single combined ISR demuxes INFO1/INFO2 (response done, access end, PIO
read/write, errors, and card-detect). There is no separate card-detect handler.
Source: `refs/rzv2h_gb_ether/include/rzv2h_irq.h:681` (SPI 735 + base 32 = 767).

---

## DMAC Channel Assignment

**Optional DMA for block transfers:**

| Channel | Direction | Purpose |
|---------|-----------|---------|
| 6 | Card → RAM | DMA-accelerated SD read |
| 7 | RAM → Card | DMA-accelerated SD write |

**Cache Operations:** If DMA used, invalidate RX buffer post-transfer; flush TX buffer pre-transfer (ARM dcache).

**Linked Descriptors:** For multi-block reads/writes; verify descriptor chain alignment and length bounds.

---

## Card Detection & Interrupt Handling

**Card Detect Pin:**
- Port 5 Pin 7 (GPIO input, active low when card inserted).
- Debounce: Software debounce recommended (20 ms polling window).
- Interrupt source: ICU 237; triggered on level change.

**ISR Behavior:**
1. Read CD pin state (0 = card present, 1 = card absent).
2. Trigger slot rescan (call `sdio_mediachange_initialize()` or equivalent).
3. If card removed: finalize transactions, unmount filesystem.
4. If card inserted: delay 1 second (mechanical settle), then probe MMC/SD commands.

**Hot-swap:** Supported; driver must handle card insertion/removal without freezing.

---

## FSP Reference

If available in `refs/px4-freertos-posix-renesas-fsp/`:

- **Path:** `rzv/fsp/src/r_sdhi/r_sdhi.c`
- **Header:** `rzv/fsp/inc/api/r_sdhi.h`
- **DMAC integration:** See `r_dmac.c` for linked descriptor setup.

---

## NuttX Driver

**File:** `arch/arm/src/rzv/rzv_sdhi.c`  
**Header:** `arch/arm/src/rzv/hardware/rzv_sdhi.h`

**Initialization:**
```c
sdio_initialize(0);  /* Initialize SDHI0; register MMC/SD block device */
```

**Sample Configuration:**
- `configs/sdhi/defconfig` — SDHI0 enabled, automatic card detection.

**Mount Example:**
```bash
mount -t vfat /dev/mmcsd0 /mnt/sd
```

---

## Register Map

**Base Address (from UM):**
- SDHI0: 0x11C00000

**Key Registers:**
- **SDCLK_CTRL** (SD Clock Control): Frequency divisor.
- **SD_CMD** (SD Command Register): Issue command to card.
- **SD_ARG** (SD Argument Register): Command argument.
- **SD_STOP** (SD Stop Register): Abort current transfer.
- **SD_SECCNT** (SD Sector Count Register): Number of blocks to transfer.
- **SD_RSP10 / SD_RSP32 / SD_RSP54 / SD_RSP76** (Response registers): Card response data.
- **SD_INFO1 / SD_INFO2** (Status/interrupt flags): RX ready, TX ready, errors.
- **SDIO_MODE** (I/O Register): Register access control.

---

## Driver Validation

**Checklist:** [Validation Checklist](../validation-checklist.md)

**Key Tests:**
- **Card Detection:** Insert card, verify `CD` interrupt fires; rescan succeeds.
- **Initialization:** Issue ACMD41, verify 400 kHz clock.
- **Read/Write:** Copy 10 MB file to card; verify integrity (CRC).
- **Hot-swap:** Remove card during idle, verify graceful unmount; re-insert and remount.
- **Stress:** Continuous read/write for 1 hour; monitor error counters.

**Test Fixture:** `configs/sdhi/` board config + microSD card (any class, ≥1 GB).

---

## Related Docs

- [Port Status Matrix](../port-status-nuttx.md) — SDHI driver row.
- [Deployment Guide](../../deployment-guide.md) — SD card flashing and boot procedures.
- [System Architecture](../../system-architecture.md) — Storage role in flight logging.
