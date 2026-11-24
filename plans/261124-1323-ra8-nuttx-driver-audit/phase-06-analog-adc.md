---
phase: 6
title: "Phase 6: ADC_B"
status: pending
priority: P2
effort: "0.5d"
dependencies: [3]
---

# Phase 6: ADC_B (CM85) and RA8E1 ADC blast radius

## Scope
- Modules: `ra_adc_b.c`, `hardware/ra8p1/ra_adc_b.h`. `ra_adc.c` (RA8E1 ADC12) is read only to check the group selection and C3 `RA_ADC1_BASE`.
- Board glue: `ra8p1_adc_b.c`, `ra8p1_adc_b_hwtrigger.c`
- Configs: `adc-b`, `adc-b-hwtrigger`
- FSP: `r_adc_b` (`ek_ra8p1/adc`, `_quickstart`, `usb_pcdc`), `r_dmac` from `ek_ra8p1/adc`

## Tasks & Steps
1. Check the unit, channel and sampling-state tables, the scan group and trigger (ELC/GPT) routing, calibration, and the conversion-complete ISR, all against `r_adc_b` and `configuration.xml`.
2. Check the upper-half `adc_dev_s` contract: channel ordering, FIFO, and how the reset/setup/shutdown ops behave.
3. Check the hwtrigger config against the phase-3 ELC findings.
4. Check the PX4 `renesas/ra8/adc` HAL channel map; it is shared with RA8E1.
5. Check the EK analog pins against `board.h`.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-adc-b.md`
