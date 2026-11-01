# ADC Peripheral Notes

**Date:** 2026-10-14
**Hardware:** Renesas RZ/V2H (R9A09G057H), RDK-RZ/V2H
**Status:** bounded on-target for CR8-0 software trigger/read/close; analog accuracy remains unqualified. Authoritative row: [port-status-nuttx.md](../port-status-nuttx.md) #1. PX4 HAL: deferred/non-gating (post-G9).

Source-verified notes for `rzv_adc.c` (ADC_E, 12-bit SAR). Audit:
[audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md](../../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md)
(clock/ELC and the byte-wide `ADELCCR` access are fixed in source).

---

## Files

| What | Path (under `platforms/nuttx/NuttX/nuttx/`) |
|------|------|
| Arch driver (ADC lower half) | `arch/arm/src/rzv/rzv_adc.c`, `rzv_adc.h` |
| Register defs | `arch/arm/src/rzv/hardware/rzv_adc.h` |
| Board glue | `boards/arm/rzv/rdk-rzv2h/src/rzv2h_adc.c` (`rzv2h_adc_setup()`, called from `rzv2h_bringup.c`) |
| Channels / pins | `boards/arm/rzv/rdk-rzv2h/include/board.h` (`BOARD_ADC_CHANNEL_n`, `BOARD_ADC_PIN_ANnnn`) |
| Config | `adc` — `CONFIG_RZV_ADC`, `CONFIG_RZV_ADC0`; serial console (SCI5), RTT off |

Build: `platforms/nuttx/NuttX/build.sh adc`.

## Instance and Channels

- ADC_E0, base `RZV_ADC_E0_BASE` = `0x11C00000`; registers as `/dev/adc0`
  via `rzv_adc_initialize("/dev/adc0", chanlist, n)`.
- The driver accepts channels 0–7 (`ADANSA0` low byte). `board.h` enables
  **0–3** (AN000–AN003); 4–7 are commented out.
- `BOARD_ADC_PIN_AN00x` are all commented out ("verify with schematic"), so no
  pin is configured. RDK routing of AN000–AN007 is unverified.
- The RDK `pin_data.c` configures no ADC pins; the EVK `adc_e` samples are a
  different board. Pin assignment needs the RDK schematic.
- Defining a `BOARD_ADC_PIN_*` now builds: the board helper calls
  `rzv_gpioconfig()` (a misspelled `rzv_gpio_config()` was fixed 2026-10-01).

## Clock

`rzv_clock_enable(RZV_CPG_CLK_ADC0)` + `rzv_module_unreset()` in the driver.
The ADC clock frequency and conversion time have not been read back; do not
use them in a timing budget yet.

## Operation

The current implementation is a 12-bit Group-A software-scan lower half;
timer/external triggers, groups B/C, compare windows, sample-state tuning,
calibration, and DMA are outside its contract. The NuttX ADC upper-half owns
the `/dev/adc0` open/ioctl/read interface; read the driver and selected
`apps/examples/adc` configuration for the current call and message contract.

The `adc` profile selects the stock `apps/examples/adc` command with software
triggering and a bounded default of eight sample groups. Use `adc -n 1` for
one group. The wrapper build links `adc_main`; pin routing remains unverified.
The isolated `adc-rtt` fixture has a named trigger/read/close transcript; see
the evidence below.

Initialization failure restores the ADC module-stop bit, destroys an acquired
semaphore, reasserts reset and disables the acquired clock. Registration
success retains the clock and semaphore across upper-half open/close cycles;
repeated board initialization does not reinitialize a registered device.

## Interrupt

Group-A scan-end uses `RZV_INTC_IRQSEL_ADC0_ADA_ADIREQ_N` (575) through
`rzv_icu_attach()` on open. INTR8SEL requires an IRQ selector, not ELC event
256. The physical GIC INTID is allocated at runtime; there is no fixed ADC
IRQ number. Attach disabled, select edge sensitivity with
`rzv_gic_set_irq_type(irq, true)`, then enable the allocated line. ICU defaults
to level sensitivity; the observed scan-end request needs edge latching.
The [ADC repair report](../../../plans/reports/debug-261014-1122-rzv2h-adc-completion.md)
records missing ISR delivery before this repair, a passing edge comparator,
and 105 completed scan groups on the uninstrumented image. Earlier selector-only
results remain historical; analog value accuracy is unverified.

## Register authority

Register widths, offsets, trigger routing, and result access are owned by
`hardware/rzv_adc.h`, `rzv_adc.c`, and the core-matched `adc_e_iodefine.h`.
Use `svd_register_tool.py --svd rzv2h.svd` for target decoding; do not copy a
second register inventory into this note.

## Evidence

| Item | State |
|------|-------|
| Source audit, clock/ELC/`ADELCCR` fixes | done (2026-08-09) |
| `/dev/adc0` trigger/read/close on target | bounded CR8-0 proof: 105 groups /420 records across two warm loads (2026-10-14) |
| Conversion of a known voltage (analog HIL) | open |
| RDK pin routing for AN000–AN007 | open |
| PX4 `adc` consumer (battery etc.) | deferred, post-G9 |

## FSP Reference

Core-matched EVK sample: `refs/rzv2h_evk/adc_e/adc_e_rzv2h_evk_<core>_ep/`
(`<core>` = `cm33`, `cr8_0`, `cr8_1`). EVK board: use for IP behavior only,
not pins. Driver `rzv/fsp/src/r_adc_e/`; config
in `configuration.xml`, `rzv_cfg/fsp_cfg/r_adc_e_cfg.h`, `rzv_gen/`. Do not
infer ADC_E registers from other Renesas ADC families. See
[reference-source-map.md](../reference-source-map.md).

## Related

- [validation-checklist.md](../validation/validation-checklist.md)
- [pinmap.md](../pinmap.md)
