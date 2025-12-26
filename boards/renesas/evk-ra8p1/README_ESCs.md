# ESC Output Testing Guide for Renesas EVK-RA8P1

## 1. Introduction

This document provides step-by-step procedures for verifying ESC (Electronic Speed Controller) outputs on the **Renesas EVK-RA8P1** PX4 target board. Two ESC control protocols are covered:

1. **Simple PWM ESCs** – Standard analog PWM protocol (1000–2000 µs pulses at 400 Hz)
2. **DShot ESCs** – Digital protocol (DShot150/300/600/1200) with optional bidirectional telemetry

### PWM vs. DShot

| Feature | PWM | DShot |
|---------|-----|-------|
| Signal Type | Analog pulse width | Digital bitstream |
| Frequency | 50–400 Hz typical | 150k–1.2M bps |
| Resolution | ~1000 steps | 2048 steps (11-bit) |
| Latency | Higher | Lower |
| Noise Immunity | Susceptible | Robust |
| Telemetry | Not supported | Optional (BDShot) |
| Calibration | Required | Not required |

### ⚠️ SAFETY WARNING

**Before any testing:**
- **REMOVE ALL PROPELLERS** from motors
- Secure the frame to prevent movement
- Clear the test area of people and objects
- Ensure ESC/battery connections are correct (reverse polarity can destroy ESCs)
- Have a way to quickly disconnect battery power

---

## 2. Prerequisites

### 2.1 Hardware Requirements

| Item | Description |
|------|-------------|
| **Board** | Renesas EVK-RA8P1 evaluation kit |
| **ESCs** | 4× ESCs (PWM-capable, or DShot-capable for DShot testing) |
| **Motors** | 4× brushless motors (matched to ESCs) |
| **Power** | Battery or bench supply for ESC power (typically 3S–6S LiPo) |
| **Logic Supply** | 5V BEC or separate supply for EVK-RA8P1 (if not powered via USB) |
| **Wiring** | Signal wires from ESC inputs to board motor outputs |
| **Ground** | Common ground between ESCs and EVK-RA8P1 |

### 2.2 Tools Required

| Tool | Purpose |
|------|---------|
| **Oscilloscope** or **Logic Analyzer** | Verify PWM/DShot signal waveforms |
| **USB Cable** | Connect to PX4 console (USB-CDC or UART) |
| **QGroundControl** | Parameter configuration and monitoring |
| **Multimeter** | Verify power connections |

### 2.3 Firmware Requirements

Build and flash the PX4 firmware:

```bash
# Standard build (supports both PWM and DShot via parameters)
cd PX4-Autopilot
make renesas_evk-ra8p1_default

# Flash using J-Link or other supported programmer
# (Refer to board documentation for flashing procedure)
```

### 2.4 Key Parameters

| Parameter | Description | PWM Value | DShot Value |
|-----------|-------------|-----------|-------------|
| `DSHOT_CONFIG` | Protocol selection | `0` | `150`, `300`, `600`, or `1200` |
| `PWM_MAIN_RATE` | PWM frequency (Hz) | `400` | N/A (ignored in DShot mode) |
| `PWM_MAIN_MIN` | Minimum pulse (µs) | `1000` | N/A |
| `PWM_MAIN_MAX` | Maximum pulse (µs) | `2000` | N/A |
| `PWM_MAIN_DIS` | Disarmed pulse (µs) | `900` | N/A |
| `PWM_MAIN_FUNCn` | Motor function assignment | `101`–`104` | `101`–`104` |

---

## 3. Pin Mapping Overview

### 3.1 Motor Output Pin Assignments

The EVK-RA8P1 uses GPT (General PWM Timer) channels for motor control:

| Motor | PX4 Channel | GPT Timer | Output | MCU Pin | Port.Pin | Physical Location |
|-------|-------------|-----------|--------|---------|----------|-------------------|
| **1** (Front Right) | `PWM_MAIN_FUNC1` | GPT3 | GTIOC3A | P912 | Port9.Pin12 | J1 Header |
| **2** (Rear Left) | `PWM_MAIN_FUNC2` | GPT5 | GTIOC5A | P915 | Port9.Pin15 | J1 Header |
| **3** (Front Left) | `PWM_MAIN_FUNC3` | GPT11 | GTIOC11A | P903 | Port9.Pin3 | J1 Header |
| **4** (Rear Right) | `PWM_MAIN_FUNC4` | GPT13 | GTIOC13A | P515 | Port5.Pin15 | J2 Header |

### 3.2 Timer Specifications

- **Timer Clock (PCLKD)**: 250 MHz
- **PWM Mode**: All 4 channels support PWM (400 Hz default)
- **DShot Mode**: All 4 channels support DShot150/300/600/1200
- **Synchronized Start**: All timers start simultaneously via GTSTR register

### 3.3 Wiring Diagram

```
EVK-RA8P1                          ESC
┌─────────────┐                   ┌─────────┐
│             │                   │         │
│  P912 (M1) ─┼──── Signal ──────►│ ESC 1   │───► Motor 1
│  GND       ─┼──── Ground ──────►│         │
│             │                   └─────────┘
│             │
│  P915 (M2) ─┼──── Signal ──────► ESC 2 ───► Motor 2
│  P903 (M3) ─┼──── Signal ──────► ESC 3 ───► Motor 3
│  P515 (M4) ─┼──── Signal ──────► ESC 4 ───► Motor 4
│             │
└─────────────┘

⚠️ IMPORTANT: Connect GND between board and all ESCs!
```

---

## 4. Testing ESCs with Simple PWM

### 4.1 Firmware and Parameter Setup

1. **Verify firmware is flashed:**
   ```bash
   # Connect via USB serial or QGC MAVLink console
   ver all
   ```

2. **Set PWM mode parameters:**
   ```bash
   # Disable DShot (use PWM)
   param set DSHOT_CONFIG 0

   # Set PWM frequency and range
   param set PWM_MAIN_RATE 400
   param set PWM_MAIN_MIN 1000
   param set PWM_MAIN_MAX 2000
   param set PWM_MAIN_DIS 900

   # Assign motor functions (quadcopter X-config)
   param set PWM_MAIN_FUNC1 101   # Motor 1 - Front Right
   param set PWM_MAIN_FUNC2 102   # Motor 2 - Rear Left
   param set PWM_MAIN_FUNC3 103   # Motor 3 - Front Left
   param set PWM_MAIN_FUNC4 104   # Motor 4 - Rear Right

   # Save and reboot
   param save
   reboot
   ```

3. **Verify PWM driver started:**
   ```bash
   pwm_out status
   ```
   Expected output shows 4 channels configured.

### 4.2 Static PWM Output Test (Oscilloscope/Logic Analyzer)

**Setup:**
1. Connect oscilloscope probe to Motor 1 signal pin (P912)
2. Connect probe ground to board GND
3. Set oscilloscope: 1 ms/div timebase, 2V/div vertical

**Test Commands:**

> **Note:** The `pwm` command is deprecated. Use `actuator_test` instead.
> Values are normalized (0.0 = 1000µs, 1.0 = 2000µs).

```bash
# Test minimum pulse (1000 µs)
actuator_test set -m 1 -v 0.0

# Test mid-range pulse (1500 µs)
actuator_test set -m 1 -v 0.5

# Test maximum pulse (1900 µs)
actuator_test set -m 1 -v 0.9

# Stop test
actuator_test set -m 1 -v -1
```

**Expected Waveform:**

```
         ┌────┐              ┌────┐              ┌────┐
         │    │              │    │              │    │
    ─────┘    └──────────────┘    └──────────────┘    └─────
         │←─→│
         1.0ms (1000µs pulse)

    ├────────── 2.5ms (400 Hz period) ──────────┤
```

**Verification Checklist:**

| Test | Expected | Measured |
|------|----------|----------|
| Frequency | 400 Hz (2.5 ms period) | _______ Hz |
| Pulse @ 1000 | 1000 µs ±10 µs | _______ µs |
| Pulse @ 1500 | 1500 µs ±10 µs | _______ µs |
| Pulse @ 1900 | 1900 µs ±10 µs | _______ µs |
| Logic High | 3.3V | _______ V |
| Logic Low | 0V | _______ V |

### 4.3 ESC Response Check (Props Removed!)

**⚠️ Ensure propellers are removed before proceeding!**

1. **Connect ESCs to motors and power:**
   - Connect signal wires from all 4 ESCs to motor pins
   - Connect common ground
   - Power ESCs with battery (expect ESC initialization tones)

2. **Arm the system via PX4 shell:**
   ```bash
   # Bypass safety checks for bench test
   param set CBRK_IO_SAFETY 22027

   # Arm manually
   commander arm -f
   ```

3. **Test motor response:**
   ```bash
   # Set Motor 1 to low throttle (10% = 1100us)
   actuator_test set -m 1 -v 0.1

   # Verify motor spins slowly
   # If no spin, increase slightly:
   actuator_test set -m 1 -v 0.15

   # Stop motor
   actuator_test set -m 1 -v -1
   ```

4. **Test individual channels:**
   ```bash
   # Motor 1 only
   actuator_test set -m 1 -v 0.2
   # Verify: Only Motor 1 (Front Right) spins

   # Motor 2 only
   actuator_test set -m 2 -v 0.2
   # Verify: Only Motor 2 (Rear Left) spins

   # Continue for Motors 3 and 4...
   ```

5. **Disarm:**
   ```bash
   commander disarm
   ```

### 4.4 Channel Mapping Verification

Test each channel individually and verify physical motor position:

| Command | Expected Motor | Physical Position | ✓/✗ |
|---------|----------------|-------------------|-----|
| `actuator_test set -m 1 -v 0.2` | Motor 1 | Front Right | [ ] |
| `actuator_test set -m 2 -v 0.2` | Motor 2 | Rear Left | [ ] |
| `actuator_test set -m 3 -v 0.2` | Motor 3 | Front Left | [ ] |
| `actuator_test set -m 4 -v 0.2` | Motor 4 | Rear Right | [ ] |

### 4.5 Safety Checks

| Test | Procedure | Expected Result | ✓/✗ |
|------|-----------|-----------------|-----|
| Disarm stops motors | `commander disarm` | All motors stop immediately | [ ] |
| Reboot safe | `reboot` | Motors stay off after boot | [ ] |
| Kill switch | Trigger kill switch | Motors stop, system locks | [ ] |

---

## 5. Testing ESCs with DShot

### 5.1 Enabling DShot

DShot is enabled via the `DSHOT_CONFIG` parameter:

| Value | Protocol | Bit Rate | Use Case |
|-------|----------|----------|----------|
| `0` | PWM | N/A | Standard ESCs |
| `150` | DShot150 | 150 kbps | Long wires, legacy ESCs |
| `300` | DShot300 | 300 kbps | Most applications |
| `600` | DShot600 | 600 kbps | **Recommended** |
| `1200` | DShot1200 | 1.2 Mbps | Short wires, high performance |

**Enable DShot600:**
```bash
# Set DShot mode
param set DSHOT_CONFIG 600

# Save and reboot to apply
param save
reboot
```

**Verify DShot driver started:**
```bash
dshot status
```

### 5.2 DShot Signal Verification (Logic Analyzer)

**Setup:**
1. Connect logic analyzer to Motor 1 signal pin (P912)
2. Set sample rate: ≥5 MHz (10 MHz recommended for DShot600)
3. Trigger on falling edge

**Test Command:**
```bash
# Arm and send DShot command
commander arm -f

# Use actuator_test for DShot output
actuator_test set -m 1 -v 0.1
```

**Expected DShot Frame:**

DShot sends 16-bit frames:
- 11 bits: Throttle value (0–2047)
- 1 bit: Telemetry request
- 4 bits: CRC checksum

```
DShot600 Frame (16 bits @ 600 kbps = 26.67 µs total)

Bit encoding:
  "0" = 37.5% duty cycle (625 ns high, 1042 ns low)
  "1" = 75.0% duty cycle (1250 ns high, 417 ns low)

  ┌──┐     ┌────┐   ┌────┐   ┌──┐
  │  │     │    │   │    │   │  │
──┘  └─────┘    └───┘    └───┘  └──
  "0"      "1"      "1"      "0"
```

**DShot Timing Reference:**

| Protocol | Bit Period | T0H (37.5%) | T1H (75.0%) | Frame Time |
|----------|------------|-------------|-------------|------------|
| DShot150 | 6.67 µs | 2.50 µs | 5.00 µs | 106.7 µs |
| DShot300 | 3.33 µs | 1.25 µs | 2.50 µs | 53.3 µs |
| DShot600 | 1.67 µs | 625 ns | 1250 ns | 26.7 µs |
| DShot1200 | 833 ns | 313 ns | 625 ns | 13.3 µs |

### 5.3 ESC Response Check (DShot)

**⚠️ Propellers must be removed!**

1. **Arm the system:**
   ```bash
   commander arm -f
   ```

2. **Test motor response:**
   ```bash
   # Test Motor 1 at 10% throttle
   actuator_test set -m 1 -v 0.1

   # Test all motors at 10%
   actuator_test set -m 1 -v 0.1
   actuator_test set -m 2 -v 0.1
   actuator_test set -m 3 -v 0.1
   actuator_test set -m 4 -v 0.1
   ```

3. **Iterate through throttle values:**
   ```bash
   # Increase throttle gradually
   actuator_test set -m 1 -v 0.2
   actuator_test set -m 1 -v 0.3
   # ...

   # Stop motor
   actuator_test set -m 1 -v 0.0
   ```

4. **Disarm:**
   ```bash
   commander disarm
   ```

### 5.4 DShot Special Commands

DShot supports special commands for ESC configuration:

```bash
# Request ESC information (if supported)
dshot esc_info -m 1

# Reverse motor direction (toggle)
dshot reverse -m 1

# Play beep sequence (useful for motor identification)
dshot beep1 -m 1
dshot beep2 -m 2
dshot beep3 -m 3
dshot beep4 -m 4
```

### 5.5 Bidirectional DShot Telemetry (Optional)

If ESCs support bidirectional DShot (BDShot), telemetry data can be received:

**Enable telemetry:**
```bash
param set DSHOT_TEL_CFG 1
param save
reboot
```

**Check telemetry status:**
```bash
# View ESC telemetry topic
listener esc_status
```

**Expected telemetry data:**
- eRPM (electrical RPM)
- Voltage (some ESCs)
- Current (some ESCs)
- Temperature (some ESCs)

### 5.6 Fallback to PWM

If DShot causes issues, revert to PWM:

```bash
# Disable DShot
param set DSHOT_CONFIG 0

# Save and reboot
param save
reboot

# Verify PWM mode
pwm_out status
```

---

## 6. Troubleshooting

### 6.1 No Signal on Pin

**Symptoms:** Oscilloscope shows no signal or flat line

**Checklist:**
1. [ ] Verify correct pin (P912/P915/P903/P515)
2. [ ] Check GPIO alternate function configured:
   ```bash
   # Verify timer driver status
   pwm_out status   # for PWM
   dshot status     # for DShot
   ```
3. [ ] Confirm timer clock enabled (MSTPCRE register)
4. [ ] Test with different channel to isolate pin vs. software issue
5. [ ] Check for pin conflicts (I2C, SPI, other peripherals)

### 6.2 Wrong Frequency or Pulse Width (PWM)

**Symptoms:** Frequency not 400 Hz, or pulse width incorrect

**Checklist:**
1. [ ] Verify `PWM_MAIN_RATE` parameter:
   ```bash
   param show PWM_MAIN_RATE
   ```
2. [ ] Check timer prescaler in firmware matches PCLKD (250 MHz)
3. [ ] Ensure no parameter conflict (DSHOT_CONFIG should be 0)
4. [ ] Verify pulse unit is microseconds in test command

### 6.3 ESC Won't Arm or Spin

**Symptoms:** Motors don't respond to commands

**Checklist:**
1. [ ] Verify armed state:
   ```bash
   commander status
   ```
2. [ ] Check for safety switch lockout:
   ```bash
   param show CBRK_IO_SAFETY
   # Set to 22027 to bypass for bench testing
   ```
3. [ ] Verify PWM_MAIN_MIN is above ESC threshold (typically 1000–1100 µs)
4. [ ] ESC calibration (for PWM):
   - Power off ESC
   - Set output to max (2000 µs)
   - Power on ESC (wait for tones)
   - Set output to min (1000 µs)
   - Wait for confirmation tones
5. [ ] Check ESC power supply voltage

### 6.4 DShot Noise or Decoding Errors

**Symptoms:** ESCs beep erratically, motors stutter, or don't respond

**Checklist:**
1. [ ] Reduce DShot speed:
   ```bash
   param set DSHOT_CONFIG 300   # or 150
   param save
   reboot
   ```
2. [ ] Check wire length (<30 cm recommended for DShot600)
3. [ ] Verify common ground between board and ESCs
4. [ ] Use shielded or twisted pair wiring
5. [ ] Add 1kΩ pull-down resistor at ESC input if signal floats
6. [ ] Check for EMI sources (motors, switching regulators)

### 6.5 Motor Mapping Incorrect

**Symptoms:** Wrong motor responds to channel command

**Checklist:**
1. [ ] Verify physical wiring matches pin mapping table
2. [ ] Check `PWM_MAIN_FUNCn` assignments:
   ```bash
   param show PWM_MAIN_FUNC*
   ```
3. [ ] Swap signal wires at ESC end (not board end) if needed

---

## 7. Appendix

### 7.1 Known-Good PWM Configuration

```bash
# PWM mode parameters for EVK-RA8P1
param set DSHOT_CONFIG 0
param set PWM_MAIN_RATE 400
param set PWM_MAIN_MIN 1000
param set PWM_MAIN_MAX 2000
param set PWM_MAIN_DIS 900
param set PWM_MAIN_FUNC1 101
param set PWM_MAIN_FUNC2 102
param set PWM_MAIN_FUNC3 103
param set PWM_MAIN_FUNC4 104
param set PWM_MAIN_FAIL1 900
param set PWM_MAIN_FAIL2 900
param set PWM_MAIN_FAIL3 900
param set PWM_MAIN_FAIL4 900
param save
```

### 7.2 Known-Good DShot600 Configuration

```bash
# DShot600 mode parameters for EVK-RA8P1
param set DSHOT_CONFIG 600
param set PWM_MAIN_FUNC1 101
param set PWM_MAIN_FUNC2 102
param set PWM_MAIN_FUNC3 103
param set PWM_MAIN_FUNC4 104
# Optional: Enable telemetry if ESCs support it
param set DSHOT_TEL_CFG 0  # 0=disabled, 1=enabled
param save
```

### 7.3 Quick Reference: Test Commands

| Action | Command |
|--------|---------|
| Check PWM status | `pwm_out status` |
| Check DShot status | `dshot status` |
| Arm (forced) | `commander arm -f` |
| Disarm | `commander disarm` |
| PWM test single channel | `actuator_test set -m <1-4> -v <0.0-1.0>` |
| PWM test all channels | (Use individual commands) |
| Actuator test (DShot) | `actuator_test set -m <1-4> -v <0.0-1.0>` |
| DShot beep | `dshot beep<1-5> -m <1-4>` |
| View ESC telemetry | `listener esc_status` |
| Check parameters | `param show <PARAM_NAME>` |
| Save parameters | `param save` |
| Reboot | `reboot` |

### 7.4 Hardware Timer Summary

| Resource | Allocation | Notes |
|----------|------------|-------|
| GPT3 | Motor 1 (P912) | DShot-capable, DMA-capable |
| GPT5 | Motor 2 (P915) | DShot-capable, DMA-capable |
| GPT11 | Motor 3 (P903) | DShot-capable, DMA-capable |
| GPT13 | Motor 4 (P515) | DShot-capable, DMA-capable |
| PCLKD | 250 MHz | Timer source clock |

---

## Document Information

| Field | Value |
|-------|-------|
| Target Board | Renesas EVK-RA8P1 |
| PX4 Version | v1.15+ |
| Last Updated | 2025-12-24 |
| Author | PX4 Development Team |

---

**⚠️ FINAL REMINDER: Always test with propellers removed!**
