---
phase: 3
title: "Phase 3: ICU, ELC, DTC, DMAC"
status: pending
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: ICU, ELC, DTC, DMAC (CM85)

## Goal
Verify event-to-IRQ linking, ELC routing and the DMA engines, because the timer, ADC, serial and storage drivers depend on them.

## Scope
- Modules: `ra_icu.c`, `ra_elc.c`, `ra_dtc.c`, `ra_dmac.c`; board `ra8p1_elc.c`
- Configs: no dedicated config. Trace the consumers `adc-b-hwtrigger`, `sci-spi`, `spi-loopback`, `sdhi`, `ospi-b`
- FSP: `r_icu` (`ek_ra8p1/icu`, `iic_master`), `r_elc` (`ek_ra8p1/elc`), `r_dtc` (`ek_ra8p1/spi`, `sci_spi`), `r_dmac` (`ek_ra8p1/dmac`, `adc`)

## Tasks & Steps
1. `IELSRn` programming and the event numbers in `ra8p1_irq.h` vs the device header `ELC_EVENT` and FSP `vector_data.c`. `bsp_elc.h` is empty, so name the hardware manual as the missing authority where needed.
2. Attach/enable/ack/clear/detach ordering, IR flag clearing before the NVIC acknowledge, and NVIC priority range.
3. ELC link set/clear and the PRCR/ELCR lock. Check whether consumers depend on `CONFIG_RA_ICU`/`CONFIG_RA_ELC` while those are commented out or off.
4. DMAC: channel allocation, activation source, transfer widths, block/repeat mode, completion/error ISR, abort. On CM85, D-cache clean/invalidate on CPU addresses with line alignment.
5. DTC: vector table placement and alignment, descriptor lifetime, chain mode, the DTCST/DTCCR ordering.
6. Check that the CM33 image cannot program the same ICU slots or DMAC channels (an ownership collision).

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-icu-elc-dma.md`

## Verification
- Symbols from the phase-1 ELFs of consumer configs show which of these drivers are actually linked. A driver that no config links is an evidence finding.
