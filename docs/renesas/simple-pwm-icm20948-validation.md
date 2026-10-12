# Simple PWM and ICM20948 Bench Validation

**Date:** 2026-10-11  
**Board/core:** RDK-RZ/V2H, CR8-0  
**Target:** `renesas_rdk-rzv2h_simple`  
**Evidence:** build-clean; fresh four-profile software checks passed; hardware untested

## Profile and prerequisites

This compact PX4 image is the native legacy bench: it starts PWMOut and one
SPI0 ICM20948 accel/gyro instance independently.
It retains RTT/HRT/work queues/uORB and volatile `/fs/params`, with no flight
modules, `sensors`, allocator startup, MAVLink, IPC, RC, barometer or automatic
magnetometer. Control allocator is linked only for mixer metadata. Dedicated
`nuttx-config/simple` and `ROMFS/rdk-rzv2h-simple` prevent payload startup/fallback
into `nsh`. Retired core-only resources/evidence remain historical.

Identify the actual module/revision and verify its regulator, supply and logic
level adaptation from its schematic before powering it. A GY-912 label or the
board GPIO voltage does not prove module tolerance. See the
[standalone module constraints](gy912-icm20948-validation.md#scope-and-wiring).
Disconnect P94 button wiring and other SPI0/P94 users. In this legacy image,
one sensor owns P93 and P94 callback ownership is exclusive; sensor reset/stop
can detach that descriptor. The fitted extension reference is a future,
default-off profile with three polled ICM45686 devices sharing P90/P91/P92 and
configurable CS lines P93/P94/P95, with no DRDY. Its P94 CS1 wiring is
incompatible with this image's P94 interrupt contract. Do not run standalone
`gy912_test` or `/dev/pwmN` commands in this image. Use disconnected motors/ESCs
and compatible high-impedance probes.

| Signal | RDK pin | Contract |
|---|---|---|
| MOSI/SDI | P90 | SPI0 alternate function |
| MISO/SDO | P91 | SPI0 alternate function |
| SCK | P92 | SPI mode 3, 1 MHz, 8-bit MSB first |
| CS/NCS | P93 | SSLA0-capable pin used as active-low GPIO CS in this legacy image |
| INT | P94 | Input/pull-up/TINT; no button or competing callback owner |
| PWM motor 1 | PA4 | GPT6A |
| PWM motor 2 | PA7 | GPT7B |
| PWM motor 3 | P96 | GPT9A |
| PWM motor 4 | P53 | GPT10B |

The SPI table contains one profile-selected device; default/DShot use MPU9250.
Native board SPI setup configures the pins and holds CS over each command/data
exchange. Canonical GPIO port/pin shifts and mode flags replace stale encodings;
omitted optional DRDY/power pins remain absent instead of selecting P00. GPIO
IRQ slots initialize once before callbacks, preserving live owners on repeated
board initialization. The PX4-only bus uses `LOCK_NONE`; exclusive ownership
is a prerequisite, not shared-bus arbitration.

## Build and artifact checks

Run from repository root, sequentially with other RZ/V builds:

```bash
./build.sh --list
./build.sh renesas_rdk-rzv2h_simple
./build.sh --no-clean renesas_rdk-rzv2h_simple
python3 test/rzv2h-simple-artifact-contract-test.py --build-dir build/renesas_rdk-rzv2h_simple --board-label simple
```

Incremental mode is for the same configured profile. Exact ELF:
`build/renesas_rdk-rzv2h_simple/renesas_rdk-rzv2h_simple.elf`.
The build gates inspect resolved simple config/ROMFS/builtins, selected sensor,
PWM/RTT/GPIO IRQ, absent flight/payload startup and ELF symbols. Shared-HAL
regressions also require fresh default, DShot and SIH builds. Save logs, source
revisions and ELF SHA-256; software artifacts are not hardware proof.

Software checkpoint, 2026-10-04: 114 distinct Python source methods and the Bash
OneShot/DShot runner passed. Fresh repository-wrapper builds passed for
simple/default/DShot/SIH, with respectively 6/6/6/12 artifact methods, then a
fresh final simple restoration passed all six artifact methods again. The
[tester report](../../plans/261004-rzv2h-simple-pwm-icm20948/reports/tester-261004-simple.md)
records source/host checks, resolved configuration, linked SPI implementations
and failed attempts; [persistent evidence](../../plans/261004-rzv2h-simple-pwm-icm20948/reports/software-evidence/)
includes passing build logs and frozen source hashes. Final simple ELF SHA-256:
`0794001c7754539cccd01ed747d4783363632be36dd5b2409f790b15fb2ad55c`;
binary 328640 bytes; `_SEGGER_RTT` at `0x081a2400`.
This is evidence for the preserved dirty workspace, not isolated bare HEAD.
It does not establish sensor samples, FIFO processing, callbacks or electrical
waveforms. Recheck symbols against the exact ELF used in any later session.

## RTT after a separately approved load

Reset, ELF load and target-memory writes require separate explicit approval;
no target operation has been performed for this guide. Follow the
[deployment guide](../deployment-guide.md). Use the exact loaded ELF to discover
`_SEGGER_RTT`, without assuming another image's address:

```bash
arm-none-eabi-nm build/renesas_rdk-rzv2h_simple/renesas_rdk-rzv2h_simple.elf | rg _SEGGER_RTT
JLINK_SERIAL=<probe-serial> platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 build/renesas_rdk-rzv2h_simple/renesas_rdk-rzv2h_simple.elf
platforms/nuttx/Debug/nsh_console_exec.py --timeout 15 --log /tmp/simple-rtt.log 'ver all' 'work_queue status' 'icm20948 -s -b 0 -R 0 status' 'pwm_out status'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

The bridge uses JLinkExe on the running core; JLinkGDBServer cannot bridge CR8
RTT. One probe has one owner: stop GDB before RTT, and RTT before GDB.

## Sensor acceptance within a bounded window

Boot issues checked `pwm_out start` and `icm20948 -s -b 0 -R 0 start` requests.
Each failure prints ERROR independently and leaves diagnostics accessible.
Both starts are asynchronous: accepted requests do not establish readiness.
Rotation 0 is an unverified bench mounting placeholder, not a flight calibration.
Do not duplicate the already-started sensor instance.

Allow at most ten seconds after the startup request, checking status/topics at
bounded intervals. A listener may return immediately before a first publication;
retry within this observation window rather than restarting the sensor. No fresh
samples by the deadline is a runtime failure, not permission to wait indefinitely.

```text
icm20948 -s -b 0 -R 0 status
listener sensor_accel -n 5
listener sensor_gyro -n 5
listener sensor_accel_fifo -n 5
listener sensor_gyro_fifo -n 5
perf
```

Record three independent results:

1. Raw accel/gyro: matching expected device IDs, increasing timestamps and fresh
   plausible measurements; no error-counter growth over the observation window.
2. FIFO acquisition: fresh accel/gyro FIFO topics with matching IDs, increasing
   timestamps and positive sample counts, or an observed successful
   `FIFORead` → `ProcessAccel`/`ProcessGyro` path. Direct-register publishing when
   FIFO count is zero does not satisfy FIFO acceptance.
3. P94 delivery: measured INT waveform and observed
   `ICM20948::DataReadyInterruptCallback` through approved debugger observation.
   Existing driver active-low pulses use a rising deassertion callback; preserve
   that source behavior and compare the real waveform. Polling fallback can
   publish data without callbacks. `status`/missed-interrupt counters alone do
   not prove callback delivery. Record polling-only operation as an open DRDY gate.

Before a debugger halt/breakpoint, finish the actuator window, `pwm_out stop`
and measure inactive pins. Timeouts require running software; GPT can continue
an active waveform while the core is halted. A halt is neither an actuator
stop/timeout test nor an interrupt-latency measurement.

For optional magnetometer work only, stop the existing instance, then use
`icm20948 -s -b 0 -R 0 -M start`. `-M` is a flag; never `-M 1`. This is outside
baseline accel/gyro acceptance and requires the actual auxiliary sensor.

## Four-channel PWM measurements

Boot must leave all four output pins inactive. Verify PWM initialization and
actual parameters independently of sensor startup:

```text
pwm_out status
param show PWM_MAIN_TIM*
param show PWM_MAIN_FUNC*
param show PWM_MAIN_MIN*
param show PWM_MAIN_MAX*
param show PWM_MAIN_DIS*
param show PWM_MAIN_FAIL*
actuator_test set -m 1 -v 0 -t 5
```

Defaults: TIM0..3 400 Hz, FUNC1..4 101..104, MIN1100/MAX1900/DIS1000/FAIL1000 µs.
With the default nonreversed/nonreversible motor configuration, normalized zero
requests the 1100 µs minimum, not 0 µs or a raw-value argument. Capture PA4 for
five seconds: expected period 2.5 ms, then all motor channels inactive after
timeout. Repeat individually with `-m 2`, `-m 3`, `-m 4` for PA7/P96/P53.
PWMOut enables all configured channels during each active test: measure and
record DIS1000 pulses on the unrequested channels during that window. Parameter
overrides can change the expected waveform; record resolved values first.
DIS/FAIL1000 does not imply continuing pulses after disabled motor outputs.

Record boot inactivity, each finite waveform, timeout and `pwm_out stop`
inactivity, plus repeated stop/start behavior. Use `pwm_out start` to resume
a stopped instance; never a nonexistent `pwm_out test` command. Measure before
debugger halts. State instrument resolution, voltage interface and chosen
physical tolerances; no accepted tolerance or flight claim is implied here.

## Evidence and unresolved gates

Save exact source/artifact hashes, module/board identity, RTT transcript,
raw/FIFO observations, callback evidence, four-pin captures and failure cases.
Record missing sensor/no samples, polling-only operation, duplicate/repeated
starts/stops and actuator expiry separately. Keep previous standalone/SIH
transcripts scoped to their original images.

Hardware execution remains pending: exact module electrical interface, mounting
rotation, raw/FIFO acquisition, P94 callbacks and PWM electrical measurements.
This bench image does not establish flight readiness or cold boot.
