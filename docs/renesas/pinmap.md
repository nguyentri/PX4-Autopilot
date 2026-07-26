# RZ/V2H Pin Ownership Matrix

**Date:** 2026-07-26
**Status:** Foundational; FSP pin extraction reconciled, target electrical validation pending
**Source of Truth:** [refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c](../../refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c)

Authoritative pin ownership matrix. Each row represents one GPIO pin and its configured alternate function. Cross-referenced against NuttX board configs and active FSP peripherals.

## Serial Policy

The RDK-RZV2H board does not use SCI3 as an active console. Current and target
serial roles are split by mode:

- Standalone CR8-0 NuttX: SCI4 shell + RTT diagnostics.
- Standalone CR8-1 target: SCI5 shell + RTT diagnostics, not yet hardware validated.
- Standalone CM33 target: SCI9 shell + RTT diagnostics, not yet hardware validated.
- Integrated PX4 CR8-0: RTT0 console/debug, SCI4 LiDAR, SCI5 MAVLink/QGroundControl, SCI6 RC, SCI9 GPS.

---

## Pin Numbering Convention

**Format:** `P<port><bit>` where:
- `<port>` = 0–10; hexadecimal-style aliases use `PA` for port 10
- `<bit>` = 0–7 (bit position within port)

**Example:** P70 = Port 7, bit 0

**Total:** ~96 GPIO pins + multiplexed special-function pins.

---

## Active Pin Assignments (RDK-RZV2H)

Subset of pins actively used by PX4 + NuttX drivers:

| Pin | Port.Bit | Alt-Func | Peripheral | Mode | Pull | Drive | Owner File | FSP Ref |
|-----|----------|----------|-----------|------|------|-------|------------|---------|
| **P50** | 5.0 | TINT | GPIO/INT | Input | None; noise filter on | B01 | rzv_gpio.c | MPU9250 DRDY |
| **P52** | 5.2 | GPIO | Safety input | Input | Schmitt + noise filter | B01 | board safety (planned) | GPS safety switch |
| **P53** | 5.3 | AF=11 | GPT10B (PWM4) | Output | None | B01 | rzv_gpt.c | PWM |
| **P70** | 7.0 | AF=1 | RSCI4 TXD | Output | None | B01 | rzv_serial.c | TFmini TX |
| **P71** | 7.1 | AF=1 | RSCI4 RXD | Input | None | B01 | rzv_serial.c | TFmini RX |
| **P72** | 7.2 | AF=1 | RSCI5 TXD | Output | None | B01 | rzv_serial.c | Telemetry TX |
| **P73** | 7.3 | AF=1 | RSCI5 RXD | Input | None | B01 | rzv_serial.c | Telemetry RX |
| **P75** | 7.5 | AF=1 | RSCI6 RXD | Input | Noise-filter | B01 | rzv_serial.c | RC RX |
| **P76** | 7.6 | AF=1 | RSCI7 SDA (I2C) | Bidirectional | External pull-up; noise filter on | B01 | rzv_sci_i2c.c | BMP280 SDA |
| **P77** | 7.7 | AF=1 | RSCI7 SCL (I2C) | Bidirectional | External pull-up; noise filter on | B01 | rzv_sci_i2c.c | BMP280 SCL |
| **P82** | 8.2 | AF=6 | RSCI9 TXD | Output | None | B01 | rzv_serial.c | GPS TX |
| **P83** | 8.3 | AF=6 | RSCI9 RXD | Input | None | B01 | rzv_serial.c | GPS RX |
| **P90** | 9.0 | AF=1 | RSPI0 MOSI | Output | None | B11 | rzv_spi.c | MPU9250 MOSI |
| **P91** | 9.1 | AF=1 | RSPI0 MISO | Input | None | B11 | rzv_spi.c | MPU9250 MISO |
| **P92** | 9.2 | AF=1 | RSPI0 SCK | Output | None | B11 | rzv_spi.c | MPU9250 SCK |
| **P93** | 9.3 | AF=1 | RSPI0 SSLA0 (CS) | Output | None | B11 | rzv_spi.c | MPU9250 CS |
| **P94** | 9.4 | AF=1 | RSPI0 SSLA1 | Output | None | B11 | reserved by SPI0 mux | Unused SSLA1 |
| **P96** | 9.6 | AF=9 | GPT9A (PWM3) | Output | None | B01 | rzv_gpt.c | PWM |
| **P97** | 9.7 | GPIO | GPS buzzer | Output low | None | B01 | board GPIO (planned) | GPS buzzer |
| **PA4 / P10_04** | A.4 | AF=11 | GPT6A (PWM1) | Output | None | B01 | rzv_gpt.c | PWM |
| **PA6 / P10_06** | A.6 | GPIO | Safety LED | Output low | None | B01 | board GPIO (planned) | GPS safety LED |
| **PA7 / P10_07** | A.7 | AF=11 | GPT7B (PWM2) | Output | None | B01 | rzv_gpt.c | PWM |

---

## Pin Ownership by Peripheral

### UART / Serial Communication

| SCI Channel | Pin TX | Pin RX | Pin Flow | Device | Function |
|-------------|--------|--------|----------|--------|----------|
| RSCI4 | P70 | P71 | None | TFminiPlus | LiDAR rangefinder (/dev/ttyS4) |
| RSCI5 | P72 | P73 | None | Sik Telemetry | MAVLink / QGroundControl (/dev/ttyS5) |
| RSCI6 | — | P75 | None | fs-a8s | RC input (`/dev/ttyS6`, 100000 8E2; inversion path requires target proof) |
| RSCI9 | P82 | P83 | None | u-blox M10 | GPS (`/dev/ttyS9`, 115200 8N1) |

**Limitations:** No hardware flow control (RTS/CTS) currently implemented.

### SPI Bus (RSPI0)

| Pin | Function | Device | Signal |
|-----|----------|--------|--------|
| P90 | MOSI | MPU9250 IMU | Data out |
| P91 | MISO | MPU9250 IMU | Data in |
| P92 | SCK | MPU9250 IMU | Clock |
| P93 | CS (SSLA0) | MPU9250 IMU | Chip select |
| P94 | SSLA1 | Unused by reference application | Reserved alternate chip select |

**Speed:** ~10 MHz (SPI mode 0/1).  
**DMA:** Not currently enabled; PIO polling in rzv_spi.c.

### I2C Bus (RSCI7 SCI-mode I2C)

| Pin | Function | Device | Signal |
|-----|----------|--------|--------|
| P76 | SDA | BMP280 barometer | Data |
| P77 | SCL | BMP280 barometer | Clock |

**Address:** 0x76 (BMP280).  
**Speed:** 100 kHz (standard mode).  
**DMA:** Disabled (PIO mode).

### PWM / GPT Outputs (ESC Control)

| GPIO / AF | GPT Timer | Output | Function | Pin |
|-----------|-----------|--------|----------|-----|
| PA4 | GPT6A | PWM1 | Motor 1 (front-right) | PA4 |
| PA7 | GPT7B | PWM2 | Motor 2 (rear-left) | PA7 |
| P96 | GPT9A | PWM3 | Motor 3 (front-left) | P96 |
| P53 | GPT10B | PWM4 | Motor 4 (rear-right) | P53 |

**Frequency:** Configurable (typically 400 Hz for ESC).  
**Duty Cycle:** 1000–2000 µs (1–2 ms pulse width).  
**Source:** [rzv_gpt.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c), [timer_config.cpp](../../boards/renesas/rdk-rzv2h/src/timer_config.cpp)

### GPIO / Interrupts

| Pin | Function | Source | Active Config |
|-----|----------|--------|----------------|
| P50 | GPIO / TINT | Ext. interrupt | IMU INT (edge-triggered) |
| P52 | GPIO input | Safety switch candidate | FSP reference config; PX4 consumption pending |
| P97 | GPIO output low | GPS buzzer candidate | FSP reference config; PX4 consumption pending |
| PA6 / P10_06 | GPIO output low | Safety LED candidate | FSP reference config; PX4 consumption pending |

**Pull-ups/Pull-downs:** P76/P77 require external I2C pull-ups; confirm the populated board value before timing validation.

---

## Pin Availability (Reserved for Future Use)

| Port | Pins | Status | Notes |
|------|------|--------|-------|
| P0 | 0–7 | Unused | Available for GPIO expansion |
| P1 | 0–7 | Unused | Available for GPIO expansion |
| P2 | 0–7 | Unused | Available for GPIO expansion |
| P3 | 0–7 | Unused | Available for GPIO expansion |
| P4 | 0–7 | Unused | Available for GPIO expansion |
| P5 | 1, 4, 6–7 | Unused | P50 interrupt, P52 safety input, P53 PWM |
| P6 | 0–7 | Unused | Available for expansion |
| P8 | 0–1, 4–7 | Unused | P82, P83 reserved (UART) |
| P9 | 5 | Unused | P90–94 SPI0, P96 PWM, P97 buzzer |
| PA | 0–3, 5 | Unused | PA4/PA7 PWM; PA6 safety LED |

---

## Cross-Check Recipe

**Verify pinmap against FSP source:**

```bash
# Extract active pins from pin_data.c
grep -E "BSP_IO_PORT_.*PIN" \
  refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c \
  | sed 's/.*BSP_IO_\(PORT_[^,]*\).*/\1/g' \
  | sort | uniq > /tmp/fsp_pins.txt

# Extract active pins from board defconfig
grep -E "CONFIG_RZV_" \
  platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/nsh/defconfig \
  | grep -oE "P[0-9A-F][0-9]" \
  | sort | uniq > /tmp/nuttx_pins.txt

# Compare (should show minimal diffs)
diff /tmp/fsp_pins.txt /tmp/nuttx_pins.txt
```

**Validate against board_config.h:**

```bash
grep -E "PX4_UART_|GPIO|SPI|I2C" \
  boards/renesas/rdk-rzv2h/src/board_config.h \
  | grep -oE "P[0-9A-F][0-9]"
```

---

## Related Files

- **Hardware Guide:** [hardware.md](./hardware.md)
- **Board Config (PX4):** [../../boards/renesas/rdk-rzv2h/src/board_config.h](../../boards/renesas/rdk-rzv2h/src/board_config.h)
- **NuttX Pin Map Header:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_pinmap.h](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_pinmap.h)
- **GPIO Driver:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c)
- **FSP Source:** [../../refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c](../../refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c)

---

## Maintenance Notes

- **Per-PR Rule:** Update this table when adding new peripheral drivers or changing pin assignments.
- **Verification:** Run cross-check recipe quarterly to catch config drift.
- **If >800 LOC:** Split into `pinmap-uart.md`, `pinmap-spi-i2c.md`, `pinmap-pwm.md` in `peripherals/` directory.
- **Conflicts:** Reserved pins are marked with owner file; confirm in Kconfig before reassignment.

---

## Known Limitations (Phase 1)

1. No internal pull-up/pull-down contract is established in `rzv_gpio.c`; SCI7 I2C requires board-level external pull-ups.
2. SPI DMA not implemented; PIO polling only.
3. UART flow control (RTS/CTS) not wired.
4. Secondary SPI/I2C buses not active; only RSPI0, RSCI7 in use.
5. Multiplexed pins (e.g., P50 as GPIO vs. TINT) require Kconfig guards; conflicts possible in dynamic reconfiguration.
6. P52 safety input, P97 buzzer, and PA6 safety LED are present in the FSP pin configuration but remain **needs on-target/schematic validation** for PX4 ownership.

---

## Next Steps

- **Phase 2:** Add port-status-nuttx.md per-driver validation row.
- **Phase 3:** Add peripherals/canfd.md, peripherals/sdhi.md with their own pin tables.
