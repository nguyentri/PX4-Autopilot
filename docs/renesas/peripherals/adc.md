# ADC Peripheral Specification

**Date:** 2026-07-11  
**Hardware:** Renesas RZ/V2H (R9A09G057H)  
**Scope:** Analog-to-Digital Converter (ADC) block documentation for driver development.

---

## Hardware Block Overview

**Peripheral:** 12-bit successive-approximation ADC with programmable channel scanning and ELC trigger support.

**Instance on RDK-RZ/V2H:**
- ADC0: Primary analog input (16 channels available)

---

## Channel Map

### ADC0 Input Channels (typical assignment)

| Channel | Port | Pin | Signal | Sensor Example |
|---------|------|-----|--------|-----------------|
| 0 | (analog) | AN000 | Vref+ | (internal reference) |
| 1 | (analog) | AN001 | Vref- | (ground) |
| 2 | 11 | 0 | Battery voltage | LiPo cell monitor |
| 3 | 11 | 1 | Airspeed differential | Pitot tube (differential pressure) |
| 4 | 11 | 2 | Aux ADC-1 | Spare analog input |
| 5 | 11 | 3 | Aux ADC-2 | Spare analog input |
| 6–15 | — | — | (not used on standard RDK) | (future expansion) |

**Verification:** Cross-reference board schematics and `rzv_pinmap.h` for actual assignments.

**Pin Configuration:** Analog input pins do NOT require alternate function selection; ADC automatically multiplexes on hardware.

---

## Voltage Reference & Input Range

**Reference Voltage:** VREF+ and VREF- (typically 3.3V and GND on RDK).

**Input Range:** 0 to VREF+ (12-bit resolution).

**Resolution:** 3.3V / 4096 steps ≈ 0.805 mV per LSB.

**Calibration:** Optional internal calibration routine (self-calibrate before first measurement to correct offset/gain drift).

---

## Trigger Sources

**ADC Start Trigger Options:**

| Source | Purpose | Driver Config |
|--------|---------|---------------|
| **Software** | Polled ADC reads; `adc_read()` starts conversion. | `CONFIG_ADC_POLLED` |
| **Timer (GTM)** | Periodic scanning (e.g., 100 Hz sample rate). | `CONFIG_ADC_TIMER_TRIGGER` |
| **ELC Event** | Synchronized to external event (e.g., GPIO interrupt). | `CONFIG_RZV_ADC_ELC` |

**Recommended for Flight Control:** Timer trigger (GTM) to ensure deterministic sampling synchronized with flight loop.

---

## Sampling Configuration

**Sample Duration:** Programmable via ADSR (ADC Sampling Time Register).

**Typical Values:**
- **Fast:** 2.5 µs sample time (8 ADC clock cycles)
- **Standard:** 5 µs sample time (16 ADC clock cycles)
- **High-precision:** 10 µs sample time (32 ADC clock cycles)

**Clock Source:** ADC CLK (from CPG module).

**Clock Frequency:** 20 MHz (typical).

**Conversion Time:** ~20 µs for 12-bit result (includes sampling + conversion).

---

## DMAC Support (Optional)

**DMA-Accelerated Scanning:**

| Channel | Direction | Purpose |
|---------|-----------|---------|
| (configurable) | ADC result → RAM | High-speed continuous sampling |

**Use Case:** High-frequency IMU pressure sampling or vibrational analysis.

**Cache:** If DMA used, invalidate result buffer post-transfer (ARM dcache).

---

## Interrupt Mapping

**Interrupt Controller:** ICU

| Event | ICU IRQ | Handler |
|-------|---------|---------|
| ADC0 Conversion Complete | 183 | `rzv_adc_interrupt()` |

(IRQ number from UM section Interrupt Controller; verify against `rzv_irq.h`.)

---

## Clock Source

**Peripheral Clock:** ADC_CLK (from CPG module).

**Derivation:**
- Base clock: 100 MHz (typical PCLK)
- ADC divisor: Typically 1/5 → 20 MHz final ADC clock
- Verify in CPG CPG_CLKDIV_ADC register

---

## FSP Reference

If available in `refs/px4-freertos-posix-renesas-fsp/`:

- **Path:** `rzv/fsp/src/r_adc/r_adc.c`
- **Header:** `rzv/fsp/inc/api/r_adc.h`

---

## NuttX Driver

**File:** `arch/arm/src/rzv/rzv_adc.c`  
**Board Helpers:** `boards/arm/rzv/rdk-rzv2h/src/rzv2h_adc.c`

**Initialization:**
```c
adc_register(ADC0);  /* Register /dev/adc0 */
```

**Sample Configuration:**
- `configs/adc/defconfig` — ADC0 enabled with polled mode.

**ADC Read:**
```c
int fd = open("/dev/adc0", O_RDONLY);
uint16_t result;
ssize_t nread = read(fd, &result, sizeof(result));
/* result = 0–4095 (12-bit value) */
close(fd);
```

---

## Register Map

**Base Address (from UM):**
- ADC0: 0x110A0000 (shared with other analog peripherals)

**Key Registers:**
- **ADCSR** (ADC Control Register): Enable ADC, select scan mode, trigger source.
- **ADANS** (ADC Analog Input Select): Choose channels to scan.
- **ADSR** (ADC Sampling Time): Adjust sample duration.
- **ADDR[0–15]** (ADC Data Registers): Result per channel (read-only).
- **ADINFO** (ADC Information): Status flags (conversion complete, etc.).

**PGA (Programmable Gain Amplifier):** If available on hardware, configure via ADGAINX registers (optional for sensor pre-amplification).

---

## Driver Validation

**Checklist:** [Validation Checklist](../validation-checklist.md)

**Key Tests:**
- **Initialization:** Start ADC0, verify clock divisor applied.
- **Single Read:** Sample known voltage (e.g., 1.65V = 0x800 at mid-scale), verify ±2% accuracy.
- **Channel Scan:** Read all active channels sequentially; verify no cross-talk.
- **Accuracy:** Compare NuttX driver result to FSP reference for same input.
- **Thermal Drift:** Monitor result stability over 1-hour uptime; drift <0.1%/°C.
- **Stress:** Continuous 1 kHz sampling for 10k samples; no data loss.

**Test Fixture:** `configs/adc/` board config + external voltage divider (or known voltage source).

---

## PX4 Sensor Integration

Expected on CR8-1: ADC2 (battery voltage), ADC3 (airspeed). Published to uORB via IPC bridge for CR8-0 fusion.

---

## Related Docs

- [Port Status Matrix](../port-status-nuttx.md) — ADC driver row.
- [System Architecture](../../system-architecture.md) — ADC role in telemetry & monitoring.
- [PX4 HAL Port Status](../port-status-px4-hal.md) — ADC HAL integration.
