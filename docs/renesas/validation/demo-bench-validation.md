# Demo Bench Validation (`renesas_rdk-rzv2h_demo`)

**Board/core:** RDK-RZ/V2H, CR8-0
**Status:** build-clean; ICM-45686 bounded on-target (2026-11-01); TFmini
bounded on-target at the unit's 1 Hz (2026-11-02); BMP280 bounded on-target
after the SCI-I2C TXI fix (2026-11-08); SCI5 MAVLink RX/reconnect bounded
on-target with a host GCS emulator (2026-11-08); QGC GUI and PWM capture **pending**

## Scope

One PX4 image that shows, at the same time:

- four PWM outputs on a logic analyzer;
- ICM-45686 accel/gyro (SPI0, polled, CS P93) and BMP280 baro (SCI7 I2C, 0x76);
- ADS1115 ADC (SCI0 I2C, PX4 bus 0, 0x48);
- TFmini Plus range on SCI4;
- QGroundControl over a USB-UART on SCI5.

Not in scope: arming or flight, magnetometer, GPS, RC, DShot, CR8-1 outputs.
The image starts commander, but with no magnetometer, GPS or RC its
pre-arm checks are not expected to pass.

`COM_RC_IN_MODE` remains available to QGC and defaults to 4 (stick input
disabled). This does not enable an RC receiver or driver. `SYS_AUTOSTART`
remains 4014. Their presence in the parameter table is independent of whether
the optional RC hardware is built.

The IMU, barometer, TFmini and PWM driver start automatically. The demo's
`rc.board_extras` hook runs after the generated serial startup and requests
these streams on SCI5; no manual RTT stream commands are needed:

| Stream | Requested rate | QGC MAVLink Inspector fields |
|---|---|---|
| `HIGHRES_IMU` | 10 Hz | `xacc/yacc/zacc`, `xgyro/ygyro/zgyro` |
| `SCALED_PRESSURE` | 2 Hz | `press_abs` (hPa), `temperature` (centidegrees C) |
| `DISTANCE_SENSOR` | 2 Hz | `current_distance` (cm) |
| `SERVO_OUTPUT_RAW` (port 0) | 2 Hz | `servo1_raw` through `servo4_raw` (µs) |

Rates depend on available samples and link bandwidth. In particular, the
recorded TFmini unit produces only 1 Hz. These settings do not change its
stored measurement rate. Parameter defaults preserve explicit user settings;
if telemetry was disabled, check `MAV_0_CONFIG=101` (TEL1), `MAV_0_MODE=0`
(Normal), `MAV_0_FLOW_CTRL=0` and `SER_TEL1_BAUD=57600`. Parameters remain
volatile on this board.

SCI5 RX/TX rings are 512 bytes each. The prior 256-byte ring exposed only
255 usable TX bytes, less than the 266-byte MAVLink 2 FTP frame/burst-send
requirement. Small sensor messages could be sent while metadata downloads
stalled. The packet regression serializes an FTP response and exercises the
production send guard; it also checks the resolved firmware buffer sizes.

The demo embeds parameter, event and actuator metadata in ROMFS for retrieval
over MAVLink FTP, so QGC can load the Actuators page for this custom target
without relying on metadata published on PX4's firmware server. Other board
profiles retain their existing flash-size settings.

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
```

RTT is optional for diagnostics; QGC startup does not require it. Firmware
does not start the host bridge. A bridge from an earlier host session can
remain running until explicitly stopped. If a boot transcript is needed,
start it with the exact loaded ELF and stop it after collecting diagnostics:

```bash
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf
```

## Checks

1. Boot log: `ICM45686 started on SPI0 CS pin 3`, `BMP280 started on SCI7 I2C bus 7` and
   `ADS1115 started on SCI0 I2C bus 0`, no `ERROR [init]`.
2. Sensors over RTT (`nsh_console_exec.py --marker ...`):
   `listener sensor_accel`, `listener sensor_gyro`, `listener sensor_baro`, `listener distance_sensor`.
3. Stop the RTT bridge before watching live data:
   `platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop`. RTT stop-mode access can
   introduce sensor timing gaps. In QGC, add a Serial link for the USB-UART
   at 57600 baud with flow control off. Open Analyze Tools → MAVLink Inspector
   and check the fields above update. Tilt the IMU and move a flat target in
   front of the LiDAR. Attitude/altitude estimates depend on estimator health;
   inspect the sensor messages directly if those displays do not update.
   Judge sensor health from counters across a detached window, not from log
   lines printed while attached: read `sensors status`, `bmp280 status`,
   `icm45686 status` and `ads1115 status`, stop the bridge for at least 60 s,
   reattach and read them again. Each attach adds a fixed cost (one
   `Accel #0`/`BARO #0` TIMEOUT, several validator failsafe events, a few
   `vehicle_imu` gaps, about 35 ADS1115 comms errors); a detached window must
   add no more than one attach does, and bus error counters must stay at 0.
4. PWM: capture all four channels. Expected disarmed output is 400 Hz at 1000 µs
   (`PWM_MAIN_DIS`). Drive one channel with `actuator_test set -m 1 -v 0.5 -t 2`
   or the QGC Actuators tab (`COM_MOT_TEST_EN`, default 1) and capture the pulse width change
   (1100–1900 µs range).

For QGC actuator testing, keep the vehicle disarmed and remove propellers
(prefer a logic analyzer with ESCs disconnected for initial checks). Open
Configure → Actuators (Vehicle Setup in older QGC versions) and enable its
test sliders, then move one motor slider at a time. The demo explicitly
defaults `COM_MOT_TEST_EN=1`; an
explicit user value of 0 still disables tests. Commander rejects tests while
armed or while an available safety button is engaged, and bounds each
request to 3 seconds. Boot does not send actuator-test or arm commands.
If the sliders are unavailable, use Analyze Tools → MAVLink Console to run
`actuator_test set -m 1 -v 0.5 -t 2`, repeating with `-m 2`, `-m 3` and `-m 4`.
Verify the pulse change and return to 1000 µs on the analyzer; reported
`SERVO_OUTPUT_RAW` values alone do not prove electrical PWM output.

Software regression checks:

```bash
python3 test/rzv2h-demo-startup-test.py --build-dir build/renesas_rdk-rzv2h_demo
python3 test/rzv2h-drone-profile-contract-test.py
```

Record the ELF hash, RTT transcript and analyzer capture together before
updating any driver's status in `port-status-*.md`.

## Parameter-storage check

`/fs` is TMPFS, not xSPI/LittleFS; `/etc` is ROMFS. On a fresh boot,
`/fs/params` may not exist until parameters are first saved. That initial
import error alone is not evidence of an xSPI fault. Compiled and board
defaults remain available in the live parameter table. The BSON file stores
changed values, so a parameter at its board default need not appear there.

With the matching demo image running, use the RTT helper with `--marker`:

```text
mount
param status
param show SYS_AUTOSTART
param show COM_RC_IN_MODE
param save
bsondump docsize /fs/params
bsondump /fs/params
```

Check that `param save` succeeds and the BSON saved/decoded lengths match.
These commands save the current values without resetting calibration.
This verifies the current RAM-backed store, not power-cycle persistence.

The 2026-11-08 on-target check used demo ELF SHA256
`ca9de163811fb6c0204963d13be096ea02bc9525a80b4d7e2d68fef0a3c42f3c`.
It confirmed `SYS_AUTOSTART=4014`, `COM_RC_IN_MODE=4`, successful save and
complete BSON readback with matching decoded/saved sizes of 153 bytes.
QGC download confirmation remains open: SCI5 RX was zero during that check,
so bidirectional UART communication still needs verification with QGC connected.

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

### 2026-11-08 — BMP280 after the SCI-I2C TXI fix: working, about 11 Hz

ELF sha256 `7aa63d05…3405320d` (PX4 `b3307083505`, NuttX `edef1d3f78`,
build variant `demo`), guarded single-core load, VERIFY PASS.

- Boot: `bmp280 #0 on I2C bus 7 address 0x76`, `BMP280 started on SCI7 I2C
  bus 7`; ICM-45686 and TFmini start as before.
- `listener sensor_baro`: 99,301 Pa, 32.7 °C, device `I2C:7 (0x76)`,
  `error_count 0`; `vehicle_air_data`: baro altitude 169.9 m.
- `bmp280 status`: comms errors 0 after 9,874 samples.
- Rate: 8,194 samples over the first 754 s of uptime, most of it with no
  RTT attached (10.9 Hz), and 1,677 samples over the next 155.6 s of target
  time (10.8 Hz). RTT attachment does not change it. This is the stock
  driver's forced-mode cycle: `measure()` and `collect()` each reschedule
  after 43.2 ms, so one sample takes two intervals plus I2C time.
  `work_queue status` shows about 18 Hz because it counts both phases.
- `BARO #0 failed: TIMEOUT` (`vehicle_air_data`) still appears while RTT is
  attached, alongside the known `Accel #0 fail: TIMEOUT`. One early measure
  took 1.49 s. Whether the timeout also occurs detached was not separated:
  the log buffered while detached was drained without inspection.
- Same image: ICM-45686 at 629 Hz, |a| = 9.79 m/s², `error_count 0`;
  TFmini 0.91 m at 1 Hz.

The earlier `no instance started` result on this target was the SCI-I2C TXI
handler bug, not the module; see
[BMP280 validation, 2026-11-08](bmp280-i2c-validation.md#board-run-2026-11-08-pass-after-txi-fix).
The host transaction test `test/rzv2h-sci-i2c-runtime-test.py` now models the
TXI entry acknowledge and fails if the handler writes `CFCLR.TDREC` again.

### 2026-11-08 — SCI5 MAVLink RX after the TCSETS fix: reconnect works

ELF sha256 `f6503c66…fe76f2180d` (NuttX `23e4246429`, build variant `demo`),
guarded single-core load, VERIFY PASS.

- Before the fix: `mavlink status` showed `rx 0.0 B/s`, and SCI5 had
  `rx_count 0` with `CCR0 0x00000411` (RIE clear). The `TCSETS` from MAVLink's
  `tcsetattr()` re-ran `rzv_setup()`, which cleared the interrupt enables set
  at open. MAVLink waits in `poll()`, so nothing turned RIE back on.
- After the fix: SCI5 shows `CCR0 0x00010411` after boot.
- Host FT232R on P72/P73 at 57600 8N1: 680 valid frames in 15 s with 2 bad
  bytes, both from a partial frame when the capture started.
- A pymavlink GCS emulator ran heartbeat, `AUTOPILOT_VERSION` request and a
  full parameter download, then disconnected, three rounds in a row. Every
  round got the version and 802/802 parameters in 11–15 s.
- Host regression test: `test/rzv2h-serial-tcsets-runtime-test.py`.

### 2026-11-09 — free-running HRT: sensors and PWM unchanged, reboot resets

ELF sha256 `b9f836ef…86b6bf7f` (NuttX `cac03a185e` plus the
free-running `rzv_hrt.c`, build variant `demo`), single-core load.
[Run record](../evidence/rtt-hil-demo-hardware-run-261109.md).

- `icm45686 status`: bad register/transfer 0, FIFO overflow 0, one FIFO reset
  at start. Accel at 666.7 Hz.
- `pwm_out` interval averaged 1459 us, and `bmp280` reported 0 comms errors.
- The `Accel #0` / `BARO #0` TIMEOUTs and `vehicle_imu` gaps match the
  2026-11-01 run. Over 30 s with the bridge stopped, the gap counters (13 →
  27–31) rose only around the two reconnects.
- `reboot` stopped the console. A follow-up read-only connect reported CR8-0
  `DBGEN is not asserted`, so the SoC reset happened.

### 2026-11-09 — sensor TIMEOUTs are attach-only; ADS1115 auto-start

ELF sha256 `054989d2…` (build variant `demo`, ADS1115 started by
`init/demo/rc.board_sensors`), single-core load.
[Diagnosis report](../../../plans/reports/debugger-261109-1509-demo-sensor-timeouts-rtt-attach.md).

- Cold load then 60–90 s with no probe: the buffered boot log has no TIMEOUT;
  the `Accel #0`/`BARO #0` TIMEOUT lines appear only at attach. This settles
  the open question of the 2026-11-08 BMP280 run.
- Detach windows of 5 s and 120 s added the same counts (validator failsafe
  +6 to +8, `vehicle_imu` gaps +5 to +10). `bmp280 comms errors` and
  `icm45686` bad register/transfer stayed 0, so no bus speed change is needed.
- ADS1115: boot shows `ADS1115 started on SCI0 I2C bus 0`; `adc_report` from
  `I2C:0 (0x48)` with 4 channels. 60 s detached added 5554 cycles (80 Hz) and
  34 comms errors, the same as one attach; a first read after a 60 s detached
  boot showed 18. The driver also counts "conversion not ready" as a comms
  error. `adc_report.timestamp` stays 0 (stock driver).
