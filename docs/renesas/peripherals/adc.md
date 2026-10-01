# ADC Peripheral Notes

**Date:** 2026-10-01
**Hardware:** Renesas RZ/V2H (R9A09G057H), RDK-RZ/V2H
**Status:** blocked, no target conversion evidence. Authoritative row: [port-status-nuttx.md](../port-status-nuttx.md) #1. PX4 HAL: deferred/non-gating (post-G9).

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
| Config | `adc` — `CONFIG_RZV_ADC`, `CONFIG_RZV_ADC0`; SCI4 console, RTT off |

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

- 12-bit resolution (`ADCER.ADPRC = 0`), Group-A software scan only.
- Start a scan with `ioctl(fd, ANIOC_TRIGGER, 0)`; `ANIOC_GET_NCHANNELS` is
  also supported. Results arrive through the ADC upper-half FIFO, one
  `struct adc_msg_s` per enabled channel.
- Not implemented: timer/external triggers, groups B/C, compare windows,
  sample-state tuning, calibration, DMA.

```c
int fd = open("/dev/adc0", O_RDONLY);
ioctl(fd, ANIOC_TRIGGER, 0);
struct adc_msg_s s[4];
ssize_t n = read(fd, s, sizeof(s));   /* s[i].am_channel, s[i].am_data */
close(fd);
```

`apps/examples/adc` (`adc -n 1`) is the usual NSH test if enabled in the config.

## Interrupt

Scan-end event `RZV_ELC_ADC0_ADA_ADELCREQ` is routed through the ICU with
`rzv_icu_attach()` on open. That route is selectable, so the INTID is
allocated at runtime; there is no fixed ADC IRQ number.

## Key Registers

`ADCSR` (start/scan mode), `ADANSA0` (Group-A channel mask), `ADCER`
(resolution/format), `ADSTRGR` (trigger select), `ADELCCR` (8-bit, ELC
control), `ADDR0`–`ADDR7` (results). Widths and offsets: `hardware/rzv_adc.h`
and the core-matched `adc_e_iodefine.h`. Decode on target with
`svd_register_tool.py --svd rzv2h.svd`.

## Evidence

| Item | State |
|------|-------|
| Source audit, clock/ELC/`ADELCCR` fixes | done (2026-08-09) |
| `/dev/adc0` register + open on target | open |
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

- [validation-checklist.md](../validation-checklist.md)
- [pinmap.md](../pinmap.md)
