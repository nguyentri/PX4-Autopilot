# demosih customer showcase — bounded on-target run — 2026-11-10

Target `renesas_rdk-rzv2h_demosih` on CR8-0, RDK-RZ/V2H, base HEAD
`b6653932480` plus uncommitted demosih changes. RAM load with
`rzv2h-load-one-core.sh cr8_0` (VERIFY PASS). QGC/MAVLink on SCI5
`/dev/ttyUSB0` at 115200. Raw transcript:
`demosih-showcase-onboard-transcript-261110.txt`.

All flight data comes from PX4 SIH. Real bench sensors (ICM45686, BMP280,
TFmini, ADS1115) run alongside and are streamed for display. They never feed
EKF2. This record covers the showcase only, not flight readiness.

## Result

| Check | Result |
|-------|--------|
| Sensor selection | SIH accel/gyro `1310988`, baro `6620172`, mag `197388` are instance 0 and selected. Real ICM45686 `3407874` and BMP280 `4159033` are instance 1. |
| Origin | 10.8056 N, 106.6785 E, 5.0 m AMSL. Position 0.9 m from origin at rest. |
| Link | 2.4–3.3 kB/s at `MAV_0_RATE 4800`. No BAD_DATA, no HIL_* streams. |
| Mission | Takeoff to 20 m, 3 waypoints (80 m square), RTL. Accepted, armed on the first attempt, items 0–3 reached, landed and disarmed after 143–152 s. Passed twice. |
| Battery | Simulated 4S. Went from 95 % to 80 % during one mission. |
| ADS1115 | A0 17570 counts ≈ 3.294 V, A1 ≈ 0, A2 ≈ 35 counts ≈ 6.9 mV, A3 ≈ 0. Matches bench wiring (A0 at 3.3 V, others near GND). `adc_report.timestamp` is now non-zero. |
| Load | CPU idle ≈ 52 %. SIH stack 1420/2000 used. |

## Fixes made during the run

- `sih.cpp`: task stack raised from 1560 to 2048. This NuttX build has no
  interrupt stack, so ISRs nest on the task stack, and only 92 bytes were left
  free.
- `ads1115_main.cpp`: stamp `adc_report` before each publish. The timestamp was
  always 0.
- demosih defaults:
  - `MAV_0_RATE 4800`. Above 5000 B/s PX4 enables HIL streams that saturate
    115200 baud.
  - `BAT1_N_CELLS 4`. With 0 cells, BATTERY_STATUS reported 65535 V.
  - `COM_ARM_IMU_ACC 30`. The real ICM reads gravity on X, ≈ 14 m/s² from the
    level SIH IMU.

## Second run: dedicated interrupt stack

Without an interrupt stack, every IRQ handler ran on the interrupted task's
stack, and the ARMv7-R vector code also reserves a second exception context
there. demosih now has its own defconfig: the demo defconfig plus
`CONFIG_ARCH_INTERRUPTSTACK=2048`. The demo target is unchanged.

The run was a fresh RAM load with the probe detached, the same mission, then
the MAVLink shell:

| Check | Before | After |
|-------|--------|-------|
| navigator free stack after mission | 188 B | 436 B |
| `wq:SPI0` free stack | 268 B | 652 B |
| SIH free stack | 580 B | 960 B |
| Interrupt stack peak | n/a | 260 / 2048 B |
| Mission | pass | pass (armed first try, items 0–3, disarmed at 151 s) |
| SCI5 RX errors (GDB, after run) | n/a | 0 overrun, 0 framing |
| Steady-state link, 30 s | n/a | 3.4 kB/s, 0 BAD_DATA |

The log had no TIMEOUT, no inconsistency and no `unstable` messages.

### MAVLink shell "first session only"

The shell itself is fine. Each session starts a new `nsh` and its close
packet stops it. Seven sessions with no probe attached (three spaced ≈ 15 s
apart, four 1 s apart) all answered. SCI5 counted exactly the bytes the host
sent (4 × 124), and the overrun counter did not change.

Packets were lost only while the JLinkExe RTT bridge was attached. J-Link
reaches CR8-0 RTT in stop mode and halts the core. A halt longer than about
1.4 ms fills the 16-byte SCI5 FIFO at 115200, so bytes overrun (4 counted),
a shell command or close packet is lost, and the SIH baro reported a
TIMEOUT. Measure link and sensor timing with the probe detached. The
AXI-AP dual-RTT path does not halt the core.

The host's `rx loss` figure in `mavlink status` is not real loss. Each new
host connection restarts its sequence numbers, and PX4 counts the gap. The
host saw 19 BAD_DATA packets only in the first 10 s after a fresh load,
which is boot-time noise, and none in steady state.

## Third run: ADS1115 in QGC, and the demo target

`rzv2h_adc_telemetry` (board module, `adc_telemetry/`) forwards `adc_report`
as `debug_key_value`, one channel every 125 ms, and both images stream
`NAMED_VALUE_FLOAT` at 10 Hz. QGC shows `ADS_A0`..`ADS_A3` in volts in the
MAVLink Inspector, each at 2 Hz.

The interrupt stack moved into the shared demo defconfig, so
`nuttx-config/demosih/defconfig` is a symlink to it again and the `demo`
target has the same fix. Both targets were clean-built, RAM-loaded and
checked with the probe detached:

| Check | demosih (115200) | demo (57600) |
|-------|------------------|--------------|
| `ADS_A0` | 3.2923–3.2936 V, 2.1 Hz | 3.2925–3.2936 V, 2.1 Hz |
| `ADS_A1` / `ADS_A3` | 0 V ± 0.4 mV, 2.1 Hz | 0 V ± 0.4 mV, 2.1 Hz |
| `ADS_A2` | 2.8–3.6 mV, 2.1 Hz | 2.6–3.4 mV, 2.1 Hz |
| Telemetry published / stale | 1197 / 2 | 597 / 0 |
| Link, steady state | 3.1–3.4 kB/s, `txerr` 0 | 2.4–2.6 kB/s, `txerr` 0 |
| Tightest task stack | navigator 436 B free | navigator 612 B free |
| `wq:SPI0` free stack | 652 B | 652 B |
| Interrupt stack peak | 260 / 2048 B | 260 / 2048 B |
| CPU idle | 52 % | 46 % |
| Mission | pass (armed first try, items 0–3, disarmed at 153.6 s) | n/a (no SIH) |

Neither log had a TIMEOUT or `unstable` message.

## Garbled telemetry frames: host-side FT232R overrun

The 0 to 21 BAD_DATA packets per 30 s seen by pymavlink in the third run do
not come from the board. The FT232R adapter on the PC overruns its 256-byte
receive buffer whenever the USB/IP path (usbipd-win 5.3.0 into WSL2) stops
polling it for longer than the buffer lasts: about 95 ms at the `demo` rate
(2.7 kB/s) and 75 ms at the `demosih` rate (3.4 kB/s). The chip then drops
bytes and sets its overrun status bit, and the Linux `ftdi_sio` driver
inserts one NUL byte into the stream for every packet that carries the bit.
One stall therefore damages several consecutive frames.

Evidence, from 14 raw captures of `/dev/ttyUSB0` with the kernel tty
counters (`TIOCGICOUNT`), probe detached:

| Image, host state | Window | Kernel overruns | Corrupted runs |
|-------------------|--------|-----------------|----------------|
| demo 57600, host load 2–4 | 30 s | 5 | 4 (one event) |
| demo 57600, host load 2–4 | 3 × 60 s | 0 | 0 |
| demo 57600, 16 busy loops | 60 s | 44 | 40 (11 events) |
| demosih 115200, host load 5–6 | 60 s | 6 | 6 |
| demosih 115200, host load 4–5 | 60 s | 146 | 102 |
| demosih 115200, 16 busy loops | 60 s | 654 | 481, about 9 % of bytes lost |

- Framing errors, parity errors and tty buffer overruns were 0 in every
  capture, which rules out a baud-rate or wiring fault.
- In every capture the number of extra bytes (captured bytes minus the
  kernel receive count) equals the overrun count exactly.
- About half of the corrupted runs become CRC-valid frames again when the
  NUL bytes alone are removed; the rest also lost bytes.
- Every corruption event follows a pause of at least 78 ms in which the
  host received nothing. The board keeps sending: `mavlink status` reported
  `txerr` 0 in steady state in the third run.
- The host load in the "busy loops" rows was generated on purpose. The
  other rows had only the load of unrelated builds on the same PC.

The FTDI low-latency mode (latency timer 1 ms instead of 16 ms) shortened
the longest pause from 121–162 ms to 81 ms but did not remove the overruns
(2, 5 and 0 in three 40 s windows, against 47, 0 and 4 without it).

The board has no RTS/CTS on SCI5, so the adapter cannot hold the board off.
The capture summaries are at the end of the transcript.

## Fourth run: pair load with `flash_dual.sh`

`./flash_dual.sh demosih` loads CR8-0 `renesas_rdk-rzv2h_demosih` and its
default partner, CR8-1 `renesas_rdk-rzv2h-io-cr8_1_demo` (the IPC heartbeat
responder). The image was built from HEAD `07b3b3ab7f5`. Checks ran over
the MAVLink shell at 115200 with the probe detached.

| Check | Result |
|-------|--------|
| Single loads after a board reset | CR8-0 started from held-in-reset, then VERIFY PASS. CR8-1 VERIFY PASS. CR8-0 telemetry kept streaming through the CR8-1 load. |
| Pair load on the same boot (run twice) | Both cores VERIFY PASS, exit 0, no `ERROR:` in either load log |
| `ver all` | variant `demosih`, git `07b3b3ab7f5`, NuttX 12.0.0 |
| `rzv2h_heartbeat status` | Link online and peer alive. tx/rx 160/160 at about 20 s, `bad_hdr` 0. The 3 timeouts happened while both cores booted and did not grow. |
| ADS1115 `adc_report` | A0 17569 counts ≈ 3.29 V, A1/A3 0, A2 12 counts. Timestamp is non-zero. |
| Mission (single-core load) | Accepted, armed on the first attempt, items 0–3 reached, max relative altitude 30 m, battery 100 → 87 %, disarmed at 158.8 s |
| Link | 3.3–3.6 kB/s, `txerr` 0 |

The first two pair loads, made right after the USB adapters were
re-attached, failed. CR8-0's `go` returned `ERROR: CPU is not halted`
before CR8-1 was touched. CR8-1 then rejected the CP15 write and its RAM
could not be read, and afterwards both cores read PC 0 and CPSR 0. A board
reset cleared this. The guarded loader used to report "loaded" despite the
J-Link error, so the failure only showed at verify. It now fails the load on
any `ERROR:` reply and does not attempt the CR8-1 load. A load straight
after a cold power-on has passed only for single cores so far; a pair load
from cold power-on is not yet checked.

## Open items

- Corrupted telemetry frames on the WSL host are a host-side artefact (see
  "Garbled telemetry frames" above). The showcase runs QGC on Windows with
  the native FTDI driver, which has no USB/IP hop; that path is not yet
  checked.
- pymavlink occasionally raises a `TypeError` in `add_message` when it
  connects mid-stream. This is a host tool issue; retrying works.
- Boot noise:
  - harmless param-not-found messages
  - volatile `/fs/params`
  - one `ekf2 missing data` preflight message at startup
  - `sensor_agp_sim: command not found` from rcS
