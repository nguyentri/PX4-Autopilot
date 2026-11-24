---
phase: 5
title: "Phase 5: GPT, AGT, ULPT, POEG, CAC, RTC, WDT/IWDT, LPM"
status: pending
priority: P1
effort: "1.5d"
dependencies: [3]
---

# Phase 5: Timers, watchdogs, power

## Scope
- Modules: `ra_gpt.c`, `ra_agt.c`, `ra_ulpt.c`, `ra_poeg.c` + `ra_poeg_chardev.c`, `ra_cac.c`, `ra_rtc.c` + `ra_rtc_lowerhalf.c`, `ra_wdt.c`, `ra_iwdt.c`, `ra_lpm.c`
- Board glue: `ra8p1_pwm.c`, `ra8p1_agt.c`, `ra8p1_opeg.c`, `ra8p1_cac.c`, `ra8p1_rtc.c`, `ra8p1_wdt.c`, `ra8p1_iwdt.c`, `ra8p1_iwdg.c`, `ra8p1_wdg_test.c`, `ra8p1_lpm.c`
- Configs: `pwm`, `agt`, `poeg`, `cac`, `rtc`, `iwdt`, `wdt-cm85`, `lpm` (CM85); `wdt-cm33` (CM33, with its own trace matrix)
- FSP: `r_gpt` (`gpt`, `gpt_input_capture`), `r_agt` (`agt`), `r_ulpt` (`lpm`), `r_poeg` (`poeg`), `r_cac`+`r_cgc` (`cac`), `r_rtc` (`rtc`), `r_wdt` (`wdt`), `r_iwdt` (`iwdt`), `r_lpm` (`lpm`)

## Tasks & Steps
1. GPT: the PCLKD/GTCLK source, prescaler math, 32-bit wrap, buffer and compare update timing, output enable, and the polarity of the PWM upper-half contract.
2. AGT/ULPT: the clock source (this ties to C2 `ra_clock_pclkb_frequency`) and the count/underflow semantics.
3. POEG: the group mapping to GPT channels, the chardev registration (`/dev/poeg1`, this ties to C1) and the reset after a trip.
4. WDT/IWDT: OFS0 vs register-start mode, whether refresh is legal at all times, the NMI/reset choice, and the CM85 vs CM33 instance ownership (is WDT per core?).
5. RTC: the sub-clock source, the RTC/RCR write-wait sequence, alarm/periodic IRQs and the lower-half return codes.
6. LPM: the sleep/standby entry sequence, wake sources, clock restore and `ra_idle.c` interaction. Check the effect on the other core.
7. Build a GPT channel ownership table for the system tick, HRT, PWM, DShot and the CM33 `timer_config.cpp`; phase 11 consumes it.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-timers-watchdog-power.md`. Waveform and timing claims need scope evidence, so record them as missing.
