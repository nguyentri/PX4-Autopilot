# Demo Bench Validation (`renesas_rdk-rzv2h_demo`)

**Board/core:** RDK-RZ/V2H, CR8-0
**Status:** build-clean; ICM-45686 bounded on-target (2026-11-01); BMP280,
TFmini, QGC and PWM capture **pending**

## Scope

One PX4 image that shows, at the same time:

- four PWM outputs on a logic analyzer;
- ICM-45686 accel/gyro (SPI0, polled, CS P93) and BMP280 baro (SCI7 I2C, 0x76);
- TFmini Plus range on SCI4;
- QGroundControl over a USB-UART on SCI5.

Not in scope: arming or flight, magnetometer, GPS, RC, DShot, CR8-1 outputs.
The image starts commander, but with no magnetometer, GPS or RC its
pre-arm checks are not expected to pass.

## Wiring

| Function | RDK pins | Notes |
|---|---|---|
| PWM1–4 | PA4 (GPT6A), PA7 (GPT7B), P96 (GPT9A), P53 (GPT10B) | Logic analyzer channels + common GND |
| ICM-45686 | P90 MOSI, P91 MISO, P92 SCK, P93 CS | P94/P95 unused; no DRDY |
| BMP280 | P76 SDA, P77 SCL | CSB high (I2C), SDO low (0x76) |
| TFmini Plus | P70 TX → sensor RX, P71 RX ← sensor TX | 115200 8N1 |
| QGC USB-UART | P72 TX → adapter RX, P73 RX ← adapter TX | 57600 8N1, 3.3 V logic |

Run the standalone samples first to separate wiring faults from PX4:
[ICM-45686](icm45686-spi-validation.md) and [BMP280](bmp280-i2c-validation.md).

## Build and load

```bash
./build.sh renesas_rdk-rzv2h_demo
platforms/nuttx/Debug/rzv2h-ipc/rzv2h-load-one-core.sh cr8_0 build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf
```

## Checks

1. Boot log: `ICM45686 started on SPI0 CS pin 3` and `BMP280 started on SCI7 I2C bus 7`, no `ERROR [init]`.
2. Sensors over RTT (`nsh_console_exec.py --marker ...`):
   `listener sensor_accel`, `listener sensor_gyro`, `listener sensor_baro`, `listener distance_sensor`.
3. QGC: connect the USB-UART at 57600 baud; check the vehicle connects
   and the attitude, baro altitude and distance values update.
4. PWM: capture all four channels. Disarmed output is 400 Hz at 1000 µs
   (`PWM_MAIN_DIS`). Drive one channel with `actuator_test set -m 1 -v 0.5 -t 2`
   or the QGC Actuators tab (`COM_MOT_TEST_EN`, default 1) and capture the pulse width change
   (1100–1900 µs range).

Record the ELF hash, RTT transcript and analyzer capture together before
updating any driver's status in `port-status-*.md`.

## Results

### 2026-11-01 — ICM-45686 (CR8-0, RTT)

ELF sha256 `670d2391…7f918055` (build variant `demo`), single-core load.

- Boot: `icm45686 #0 on SPI bus 0`, `ICM45686 started on SPI0 CS pin 3`.
- `work_queue status`: `icm45686` on `wq:SPI0` at 632 Hz (1250 us target);
  `uorb top`: `sensor_accel`/`sensor_gyro` 662 Hz.
- `listener sensor_accel`: (-1.02, -7.71, 5.89) m/s² (|a| = 9.76), 27.2 °C,
  `error_count 0`; `sensor_gyro` about 0.008 rad/s at rest.
- `icm45686 status`: bad register/transfer 0, FIFO overflow/empty 0, one
  FIFO reset at start.
- `Accel #0 fail: TIMEOUT` and `vehicle_imu` data gaps track RTT stop-mode
  halts (max intervals ~570 ms). Over 30 s with the bridge stopped,
  `ekf2: IMU message missed` stayed at 32; gaps rose only by the reconnect.
- `listener <topic> -n 2` timed out while plain `listener <topic>` printed
  data; not investigated.

Open on this run: BMP280 `no instance started` on SCI7 (same as the
standalone sample); PWM capture, TFmini readings and QGC not yet checked.

### 2026-11-02 — TFmini Plus on SCI4: no data (wiring/power)

Same ELF. `tfmini status`: port `/dev/ttyS4`, `read` counting at ~115 Hz,
`com_err 0`; `listener distance_sensor`: never published. Driver params
`SENS_TFMINI_CFG 401`, `SER_EXT2_BAUD 115200`.

Read-only GDB snapshot (no RTT attached):

- `g_sci4priv`: 115200 8N1, FIFO 32, IRQ 170–173, `pinmux_done`, `rx_count 0`,
  frame/overrun/parity 0; `g_sci4port.open_count 1`.
- `R_SCI4.CCR0 0x00010411` (RE, TE, RIE set), `CSR 0x60000000`, `FRSR 0`.
- `R_GPIO.PFC27 0x11101111`, `PMC27 0xef`: P70/P71 in SCI4 function.
- `R_GPIO.PIN27 0xcd` in 40/40 samples: P70 (TX) high, **P71 (RX) low**;
  P73 (SCI5 RX, FTDI attached) high for comparison.

The receiver is configured and idle; the RX pin never sees an idle-high UART
line. Check TFmini 5 V supply, common GND and sensor TXD → P71 before any
firmware change.

During this run CR8-0 was found held in reset (DBGEN) once between two probe
sessions with no reset marker in the tool logs; the image was reloaded.

### 2026-11-02 — TFmini Plus recheck after rewiring: working, sensor at 1 Hz

Same ELF, reloaded after a power cycle.

- `R_GPIO.PIN27 0xcf` in 40/40 samples: P71 (RX) now idle high.
- `listener distance_sensor`: `current_distance 0.91` m, device
  `SERIAL:4`, min/max 0.4/12 m; `tfmini: com_err 0`.
- `uorb top`: `distance_sensor` at 1 Hz in three samples.
- `g_sci4priv.rx_count` 522 → 711 over 21 s (about 9 B/s, one 9-byte frame
  per second), frame/overrun 0. The SCI4 link loses nothing; the sensor itself
  outputs 1 Hz. The PX4 driver does not set the sensor frame rate (factory
  default 100 Hz), so the unit's stored configuration needs changing.
