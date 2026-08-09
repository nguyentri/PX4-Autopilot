# ADC Peripheral Specification

**Date:** 2026-07-11  
**Hardware:** Renesas RZ/V2H (R9A09G057H)  
**Scope:** Analog-to-Digital Converter (ADC) block documentation for driver development.

---

## Hardware Block Overview

**Peripheral:** 12-bit successive-approximation ADC with programmable channel scanning and ELC trigger support.

**Instance used by the active port:** ADC_E0, eight external channels (0–7).
Board routing and sensor ownership remain unverified against the RDK schematic.

---

## Channel Map

The active lower half accepts channels 0–7 and programs `ADANSA0`. The checked-in
EVK examples are configuration evidence, not proof of RDK connector routing.
Confirm package pins, analog mode, and board-level signal ownership from the RDK
schematic before assigning battery, airspeed, or other sensors.

---

## Voltage Reference & Input Range

**Reference Voltage:** VREF+ and VREF- (typically 3.3V and GND on RDK).

**Input Range:** 0 to VREF+ (12-bit resolution).

**Resolution:** 3.3V / 4096 steps ≈ 0.805 mV per LSB.

No calibration routine is implemented by the active lower half.

---

## Trigger Sources

The active driver implements Group-A software scans only. Users start a scan with
`ioctl(fd, ANIOC_TRIGGER, 0)`; scan-end arrives through the configured ELC event,
ICU slot, and ADC upper-half FIFO. Timer/external triggering is not implemented.

---

## Sampling Configuration

The lower half selects 12-bit conversion and the configured channel mask. It does
not expose sample-state timing controls. Clock frequency and conversion latency
must be measured from the active CPG setup and target hardware before use in a
timing budget.

---

## DMAC Support

The active driver does not implement ADC DMA transfers.

---

## Interrupt Mapping

**Interrupt Controller:** ICU

| Event | Routing | Handler |
|-------|---------|---------|
| ADC Group-A scan end | selectable ELC event → dynamically allocated ICU/GIC INTID | `rzv_adc_interrupt()` |

Do not hard-code IRQ 183. The active configuration uses an event selector and
`rzv_icu_attach()` returns a physical INTID from the selectable range.

---

## Clock Source

The board setup enables the ADC CPG clock and releases its module stop/reset
before registering `/dev/adc0`. Exact target frequency still requires CPG
readback or authoritative clock-tree evidence.

---

## FSP Reference

Use the core-matched `adc_e` EVK project described in
[reference-source-map.md](../reference-source-map.md):

- **Project:** `refs/rzv2h_evk/adc_e/adc_e_rzv2h_evk_<core>_ep/e2studio/`
- **Driver:** `rzv/fsp/src/r_adc_e/r_adc_e.c`
- **Configuration:** `configuration.xml`, `rzv_cfg/fsp_cfg/r_adc_e_cfg.h`
- **Generated integration:** `rzv_gen/{hal_data,vector_data,pin_data}.*`

Select `<core>` as `cm33`, `cr8_0`, or `cr8_1`. The integrated PX4/FreeRTOS
tree remains secondary evidence for RDK application ownership.

---

## NuttX Driver

**File:** `arch/arm/src/rzv/rzv_adc.c`  
**Board Helpers:** `boards/arm/rzv/rdk-rzv2h/src/rzv2h_adc.c`

**Board registration:**
```c
rzv_adc_initialize("/dev/adc0", chanlist, nchannels);
```

**Sample Configuration:**
- `configs/adc/defconfig` — ADC_E0 sample configuration.

**ADC Read:**
```c
int fd = open("/dev/adc0", O_RDONLY);
ioctl(fd, ANIOC_TRIGGER, 0);
struct adc_msg_s samples[8];
ssize_t nread = read(fd, samples, sizeof(samples));
/* Each message carries channel ID and 12-bit sample data. */
close(fd);
```

---

## Register Map

**Active ADC_E0 base:** `0x11C00000`.

**Key Registers:**
- **ADCSR** (ADC Control Register): Enable ADC, select scan mode, trigger source.
- **ADANSA0:** Group-A channel mask for channels 0–7.
- **ADCER:** conversion resolution/format control.
- **ADSTRGR:** scan trigger selection.
- **ADELCCR:** byte-wide event-link control register.
- **ADDR[0–7]:** per-channel conversion results.

See `hardware/rzv_adc.h` and the core-matched CMSIS `adc_e_iodefine.h` for
widths and offsets. Do not infer unsupported ADC_E registers from other Renesas
ADC families.

---

## Driver Validation

**Checklist:** [Validation Checklist](../validation-checklist.md)

**Key Tests:**
- **Initialization:** register/open/close without alignment or bus faults.
- **Single Read:** Sample known voltage (e.g., 1.65V = 0x800 at mid-scale), verify ±2% accuracy.
- **Channel Scan:** Read all active channels sequentially; verify no cross-talk.
- **Accuracy:** Compare NuttX driver result to FSP reference for same input.
- **Thermal Drift:** Monitor result stability over 1-hour uptime; drift <0.1%/°C.
- **Stress:** repeated `ANIOC_TRIGGER` scans with FIFO consumption; no loss.

**Test Fixture:** `configs/adc/` board config + external voltage divider (or known voltage source).

---

## PX4 Sensor Integration

PX4 sensor-channel ownership and any CR8 inter-core publication remain future
integration work; the active lower half does not establish these mappings.

---

## Related Docs

- [Port Status Matrix](../port-status-nuttx.md) — ADC driver row.
- [System Architecture](../../system-architecture.md) — ADC role in telemetry & monitoring.
- [PX4 HAL Port Status](../port-status-px4-hal.md) — ADC HAL integration.
