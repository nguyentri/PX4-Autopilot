# GY-912 ICM20948 Standalone Validation

**Date:** 2026-10-02  
**Board/core:** RDK-RZ/V2H, CR8-0  
**Config:** `rdk-rzv2h:gy912`  
**Evidence:** host checks passed; firmware build-clean; sensor hardware untested

## Scope and wiring

`gy912_test` diagnoses one ICM20948 through SPI0 and its P94 data-ready
interrupt. It reads identity, checks reset/configuration, then prints signed
raw accelerometer and gyroscope samples. This standalone NuttX image does
not start PX4, register a flight sensor, or test magnetometer/barometer data.

| RDK pin | 40-pin header | Module signal | Software use |
|---|---|---|---|
| P90 | 19 | MOSI / SDI | SPI0 mode-1 pinmux |
| P91 | 21 | MISO / SDO | SPI0 mode-1 pinmux |
| P92 | 23 | SCK | SPI0 mode-1 pinmux |
| P93 | 24 | CS / NCS | Active-low GPIO chip select; SSLA0-capable pin |
| P94 | 26 | INT | GPIO/TINT input, active-low pulse, falling-edge callback |
| GND | GND | GND | Common ground |

Disconnect the P94 button-demo wiring before connecting sensor INT. The
`gy912` configuration excludes `ARCH_BUTTONS` and both SPI loopback samples;
that exclusion does not remove external button wiring. Only one sensor may
use P93. Verify the actual module revision, power input, regulator and logic
level adaptation against its schematic before connecting power. Board GPIO
voltage alone does not establish that a module tolerates it.

The sensor uses SPI mode **3**, 8-bit words, MSB first, **1 MHz**. Pinmux mode
1 is a separate GPIO alternate-function setting. The existing board SPI
integration holds P93 low across each whole command/data exchange. P94 uses
`GPIO_TINT_P9_4` (GPIOINT68); native IRQ4 pinmux is a different route.

## Build

Run from the repository root:

```bash
platforms/nuttx/NuttX/build.sh --list
platforms/nuttx/NuttX/build.sh gy912
platforms/nuttx/NuttX/build.sh --no-clean gy912
```

The incremental command is valid only after this script configured `gy912`.
Outputs are `platforms/nuttx/NuttX/nuttx/nuttx` (ELF), `nuttx.bin`, and
`nuttx.hex`. Building changes the active NuttX configuration/output; rebuild
the prior profile with the same script when switching back.

This profile uses RTT0 for NSH input and output through the syslog console
and `SYSLOG_RTT_CONSOLE_INPUT`. The existing `nsh-rtt` profile instead uses
SCI4 for its shell and RTT for logs. Check the resolved `.config` for CR8-0,
SPI0, GPIO IRQ, GY912 and RTT input before loading the image.

## Run after an approved load

Reset, ELF loading and target-memory writes need explicit authorization.
No hardware operation was performed for this guide. Use the approved board
loading procedure in the [deployment guide](../deployment-guide.md), then
attach the bridge to the running image:

```bash
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 platforms/nuttx/NuttX/nuttx/nuttx
platforms/nuttx/Debug/nsh_console_exec.py --timeout 15 --log /tmp/gy912-rtt.log 'gy912_test' 'gy912_test 1' 'gy912_test 20' 'gy912_test'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

`JLinkGDBServer` cannot bridge CR8 RTT. The bridge uses JLinkExe, without
resetting the target. Stop any GDB session before starting it; stop the bridge
before reconnecting GDB. For multiple probes, set `JLINK_SERIAL` as described
in the deployment guide.

NSH syntax is `gy912_test [sample-count]`: default **10**, accepted decimal
count **1..1000**. Extra arguments, signs, whitespace inside a quoted count,
overflow and trailing text fail before SPI/GPIO initialization. Sampling has
a 500 ms deadline per requested sample and reset checks have a one-second
deadline. A large requested count needs a correspondingly larger bridge
timeout; 1000 samples has a sampling deadline budget of 500 seconds plus
startup/cleanup and console transfer time.

These deadlines bound the diagnostic's waits and completion checks. The
native synchronous SPI exchange has its own controller polling timeout and
no cancellation or transfer-status return; console output and an in-progress
exchange can extend observed wall time beyond a wait deadline.

The console helper's process exit status checks prompt/transport completion,
not the builtin command's result. Read the diagnostic result and NSH error
output in the captured transcript; reaching another `nsh>` prompt does not
prove sensor success.

## Acceptance and failure cases

| Check | Required result |
|---|---|
| Identity/reset | Bank-0 WHOAMI `0xea`; reset completion verified |
| Configuration | Banked power, rate/filter and interrupt registers read back |
| Raw samples | Requested count; six signed big-endian accel/gyro values, qualified by raw-data-ready status |
| Interrupt | Observed P94 falling callback during the run; polling-ready status alone cannot pass |
| Missing sensor/wrong identity | Nonzero result with bounded failure |
| Disconnected INT/no callback | Bounded nonzero result even if status becomes ready |
| Missing ready status | Sample deadline fails |
| Invalid count | Nonzero result without bus/pin activity |
| Concurrent command/P94 owned | Rejected without detaching another callback |
| Cleanup | Owned sensor interrupt disabled/read back, callback detached, CS high, lock/guard released |
| Second invocation | Success after success and recovery after ordinary failed runs; no stale count/event/bank ownership |

Stationary values may repeat. Interrupt count need not equal sample count:
the sensor runs continuously, and output/task scheduling can allow multiple
edges between sampled bursts. An old queued event does not qualify a sample;
the command checks bank-0 `INT_STATUS_1` (`0x1a`, bit 0). Raw-data status must
be read explicitly; `INT_ANYRD_2CLEAR` does not clear this register.
Status values with bits outside the raw-ready bit set fail, including the
native controller's `0xff` receive-timeout value. Raw sample bytes have no
independent transport-error indication, so arbitrary sensor data cannot be
used to prove that every SPI transfer succeeded.

Cleanup failures make an otherwise successful run fail. Unknown identity
must not trigger subsequent sensor interrupt-register writes; GPIO attach
failure must not detach an existing owner. Host error-injection checks cover
these control-flow contracts, not physical wiring or pulse capture.

If callback detach or semaphore destruction fails, the command deliberately
retains persistent callback state and the busy guard. Later invocations return
`-EBUSY` until reboot, so an outstanding callback cannot access freed state.
Repeat-after-failure acceptance excludes these retained-state cleanup failures.
An interrupt-disable/readback error still fails the command but can release
the guard after safe callback detach and semaphore destruction.

## Evidence to archive

Record board/module revision and wiring, parent/apps/NuttX source revisions,
ELF SHA-256, approved loading/reset method and the complete RTT transcript.
Capture P93 framing, mode-3 clock edges and P94 falling pulses with a scope or
logic analyzer. Include normal/default/single/repeated runs and missing sensor,
disconnected INT and malformed argument results. A clean build or the earlier
[P94 button confirmation](gpio-button-interrupt-validation.md) does not prove
sensor communication or sensor-generated interrupts.

## Software checkpoint

On 2026-10-02, `python3 test/rzv2h-icm20948-contract-test.py` passed **12 test
methods and 30 runtime scenarios**, including invalid counts, missing callback,
invalid status, late completion and cleanup/reentry failures. Host compilation
uses `-Wall -Wextra -Werror`. Applicable GPIO checks (4), core IRQ (6), remaining
peripherals (4), SCI-SPI (3) and default board (1) passed. The complete GPIO suite
still reports two prior `KeyError` cases for absent `BOARD_LED3_GPIO` and
`BOARD_LED4_GPIO`; their absence was reproduced against the committed baseline.
No existing test was weakened.

NuttX checkpatch passed for both new C files and their header. The final
`platforms/nuttx/NuttX/build.sh --no-clean gy912` completed without warnings;
`nuttx.bin` is **108292 bytes**. The ELF SHA-256 is:

```text
217a310c9da36682a51cdd6c8252421464fbe1a52d162a8b213784ce22e521dd
```

The ELF contains board entry `gy912_main` and builtin wrapper
`gy912_test_main`; the registry contains `gy912_test`, `nsh` and `sh`. Resolved
configuration confirms CR8-0/SPI0/GPIO IRQ/RTT input/GY912 with button and both
loopback samples disabled. For this image `_SEGGER_RTT` is at `0x081a2400` in
uncached SRAM; use the bridge's ELF symbol lookup when another build moves it.
These checks establish software behavior and linkage, not target communication.

## References

- [Implementation plan](../../plans/261002-gy912-icm20948-rzv2h/plan.md)
- [NuttX driver evidence tiers](port-status-nuttx.md)
- [TDK ICM20948 datasheet DS-000189 v1.5](https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ds-000189-icm-20948-v1.5.pdf)

## Unresolved questions

Actual module/board revision, electrical interface and passing hardware
transcript remain unrecorded.
