# GY-912 ICM20948 Standalone Validation

**Date:** 2026-10-11<br>
**Board/core:** RDK-RZ/V2H, CR8-0  
**Config:** `rdk-rzv2h:gy912`  
**Evidence:** captured host/build checks passed. The bounded user-reported
sensor pass used historical GPIO CS/P94 IRQ wiring ([archived RTT excerpt](../evidence/gy912-icm20948-rtt-261011.txt),
[status report](../../../plans/reports/pm-261011-1859-gy912-icm20948-on-target.md));
it does not qualify the selected live DMA/SSLA0 variant. Recorded DMA target
attempts and their failures remain in the section below; capture resolved
configuration and exact ELF for each new result.

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
| P93 | 24 | CS / NCS | SPI0 SSLA0-capable output or GPIO CS; the resolved `.config` selects the active mux |
| P94 | 26 | INT | GPIO/TINT input, active-low pulse, falling-edge callback |
| GND | GND | GND | Common ground |

This is the legacy GY-912/ICM20948 profile. Disconnect the P94 button-demo
wiring before connecting sensor INT. The
`gy912` configuration excludes `ARCH_BUTTONS` and both SPI loopback samples;
that exclusion does not remove external button wiring. Only one sensor may
use P93. Verify the actual module revision, power input,
regulator and logic level adaptation against its schematic before connecting
power. Board GPIO voltage alone does not establish that a module tolerates it.

The [sensor wiring profiles](../pinmap.md#sensor-wiring-profiles) define the
native and opt-in extension ownership for P90–P95. In this legacy sample P94 is
the ICM20948 interrupt and P93 is its single CS; P94 cannot also be extension
CS1, and the `nsh-leds` button image cannot run with extension wiring. Preserve
this standalone GPIO-CS/P94-DRDY sample and its hardware-SSL/DMA evidence;
the resolved profile configuration and exact ELF remain authoritative for a
run.

The sensor uses SPI mode **3**, 8-bit words, MSB first, **1 MHz**. Pinmux mode
1 is a separate GPIO alternate-function setting. P93 stays low across each
whole command/data exchange: the SSLA0 hardware output asserts once per DMA
frame (see [SPI0 DMA and hardware CS](#spi0-dma-and-hardware-ssla0-cs)), or the
GPIO path drives it from `rzv_spi_select()`. P94 uses
`GPIO_TINT_P9_4` (GPIOINT68); native IRQ4 pinmux is a different route.

With `RZV2H_SPI0_HARDWARE_SSL` off, the P93 CS aliases in [board.h](../../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/include/board.h)
select GPIO output. Board SPI initialization and the GPIO observation test
use the shared board CS mapping, `BOARD_SPI0_SS0_GPIO`
(`GPIO_P9_3_OUTPUT_HIGH`), and leave CS high when idle. The descriptor's
initial-level flag applies at configuration; subsequent writes use their
explicit requested level. High is inactive; CS must go low during a selected
transaction. If it stays high throughout traffic, check that
`rzv_spi_select()` receives the initialized SPI0 device and that internal
loopback is disabled; loopback intentionally keeps the sensor deselected.

## SPI0 DMA and hardware SSLA0 CS

The `gy912` profile supports SPI0 DMAC and optional hardware SSLA0. Inspect the
resolved `.config` and the exact ELF before loading an image: the selected
configuration determines the DMAC unit/channels and whether P93 is hardware
SSLA0 or GPIO CS. Historical captures below retain the settings of the image
that produced each result.

| Option | Value | Effect |
|---|---|---|
| `CONFIG_RZV_DMAC` | selected in resolved `.config` | DMAC_B driver for the selected unit |
| `CONFIG_RZV_DMAC_SPI0_TX_CHANNEL` / `_RX_CHANNEL` | selected in resolved `.config` | Channels paced by SPI0 TXI (event 141) / RXI (event 140) |
| `CONFIG_RZV_SPI0_DMA` | selected in resolved `.config` | When enabled, every SPI0 exchange, including single-word `send`, runs through DMA |
| `CONFIG_RZV2H_SPI0_HARDWARE_SSL` | selected in resolved `.config` | When enabled, P93 = `GPIO_SSLA0_P9_3_M1`, IOLH b'11 (FSP "X6"), slow slew; when disabled, `rzv_spi_select()` drives GPIO CS |

Each exchange of up to 256 bytes is copied through 32-byte-aligned bounce
buffers and sent as one continuous frame; with SSLKP clear the SSLA0 output
asserts for that frame and negates when it ends. The ICM20948 code issues the
bank select and each register transaction as separate `SPI_EXCHANGE` calls,
so each becomes its own CS frame, matching the GPIO behavior. Longer
exchanges are split into multiple frames with a warning. The sequence follows
the FSP SPI_B DMA driver: SPE off, FIFO reset, `SPDCR2=0`, RX channel
(SPDR → memory, AM=4, REQD=1) then TX channel (memory → SPDR, AM=4, REQD=0),
then SPTIE/SPRIE and SPE. Completion is polled on the RX channel; SPSR errors,
DMA errors and timeouts fill the receive data with `0xff`.

With hardware SSL enabled, `gy912_test cs` (GPIO observation) returns
`-ENOTSUP` because P93 is no longer a GPIO. Turn `RZV2H_SPI0_HARDWARE_SSL` off (it
requires `RZV_SPI0_DMA` and excludes the SPI internal-loopback sample) to
restore GPIO CS.

The archived hardware-SSL/GPIO-CS attempts below use their recorded historical
images. Do not infer the live channel or CS mapping from an older ELF or
capture; the resolved `.config` and exact loaded ELF are authoritative.

**Evidence:** the first user-reported run with hardware SSL + DMA (2026-10-11)
failed: `WHO_AM_I=0x00 expected=0xea`, `result=-19`, no SPI or DMA error or
timeout logged, so the DMA exchanges reported completion. The defconfig was
returned to GPIO CS with DMA on to separate the DMA path from SSL framing.
That GPIO CS + DMA image (ELF SHA-256 `4f8fe869…e4b`, RAM-loaded on CR8-0
with `rzv2h-ipc-hil-loadstart.gdb`, no reset) also **fails**: every exchange
logs `RX DMA error CHSTAT=0x00000010` (ER set, EN clear) and `-EIO`, so
`WHO_AM_I=0xff`, `result=-19`, `IRQ=0`. That archived DMA receive path was therefore
broken independently of SSL framing. One known difference from FSP: our
hardware-trigger path sets CHCFG.HIEN (rising-edge detect), while FSP's SPI_B
channels use no detection (LOEN/HIEN/LVL = 0); this is unproven as the
cause. Host DMAC regressions (`test/rzv2h-dmac-runtime-test.py`, 12 tests,
including peripheral-to-memory receive) and all `test/rzv2h*` contracts pass;
`gy912`, `spi-loopback`, `hil-spi-loopback`, `hil-full`, `dmac-memcpy`,
`bmm150`, `pwm` and PX4 `renesas_rdk-rzv2h_{simple,dshot}` build. First
target gates: WHOAMI `0xea`, raw samples with P94 IRQs, and an analyzer trace
showing P93 low per exchange. On timeout the driver logs RX/TX `CHSTAT`,
`SPSR` and remaining bytes.

## Build

Run from the repository root:

```bash
platforms/nuttx/NuttX/build.sh --list
platforms/nuttx/NuttX/build.sh gy912
platforms/nuttx/NuttX/build.sh --no-clean gy912
```

The incremental command is valid only after this script configured `gy912`.
After a PX4 build, run the clean `gy912` command first to restore the standalone
NuttX configuration before using `--no-clean` again.
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
loading procedure in the [deployment guide](../../deployment-guide.md), then
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

## Complete standalone sample capture — 2026-10-14

The [current report](../../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md)
records independent `gy912-polled-gpio-cs` and `gy912-dma-ssl-rtt` images on
CR8-0. Both reduced-log fixtures pass `gy912_test 1`, `20` and a repeated
`20`, with WHOAMI `0xea`, configuration readbacks, exact sample totals,
positive cumulative P94 IRQ counts and clean reentry. GPIO-CS also passes
20 P93 readbacks and leaves CS high. Gated CPU SPCR2/SPSR snapshots accompany
each image; full hashes/configs and transcripts are linked from the report.

These are bounded standalone results. The original verbose 8 KiB RTT images
faulted during twenty-sample runs; the reduced-log fixtures retain WARN/ERROR
and essential sensor output with assertions/stack coloration. That workaround
does not prove the original crash mechanism is repaired. Large cumulative IRQ
counts do not qualify distinct physical edges, rate, latency, bus waveforms,
FIFO, magnetometer, calibration, PX4 integration or production behavior.
Shipped `gy912` is preserved; earlier failed DMA/SSL images remain historical.

## On-target sensor checkpoint

The user-reported pass is bounded on-target evidence for the standalone
GY-912/ICM20948 path after restoring CS to P93, with P90 MOSI, P91 MISO, P92
SCK and P94 INT. The archived excerpt includes:

```text
ICM20948 sample=9 accel=(8699,8539,-10966) gyro=(33,58,6) IRQ=3863
```

The excerpt is partial: it does not include WHOAMI/configuration output, the
final result or sample total, a complete transcript, or a logic-analyzer
trace. It therefore extends the existing SPI/GPIO bounded-on-target evidence
without promoting the standalone image to PX4 sensor integration, FIFO,
magnetometer, PWM, or production validation.

## GPIO-only CS observation

On 2026-10-11, the user identified and repaired a broken CS-to-analyzer wire
that caused the earlier stuck-high observation. CS is restored to P93 after
the temporary P50 experiment. The user then reported that the standalone
`gy912_test` sensor run passed on CR8-0. The [archived RTT excerpt](../evidence/gy912-icm20948-rtt-261011.txt)
shows SPI0 CS selection messages and one raw sample; the [status report](../../../plans/reports/pm-261011-1859-gy912-icm20948-on-target.md)
records the user attribution and evidence limits. No fresh logic-analyzer
capture was supplied, so the GPIO-only procedure below remains available for
a separately instrumented P93 check.

After loading the rebuilt `gy912` image, run:

```text
nsh> gy912_test cs
```

This mode configures P93 with `GPIO_P9_3_OUTPUT_HIGH`, then writes low for
one second and high for one second, repeating **10 cycles** (about 20 seconds).
It reads the GPIO input after each hold and prints:

```text
P93 CS step=1 write=0 read=0
P93 CS step=2 write=1 read=1
...
P93 CS step=20 write=1 read=1
P93 CS GPIO result=0
```

A readback mismatch produces a nonzero result but the pattern continues so
it can still be captured. GPIO write or sleep errors stop the pattern, with
an attempt to restore CS high. Normal completion also leaves CS high. This
mode shares the sensor test's busy guard and makes no SPI calls or P94
interrupt changes. Board boot still initializes SPI0; no transfer is requested
by this mode. The existing `gy912_test [sample-count]` mode remains available.

Connect the module CS wire and analyzer probe to **P93 (header pin 24)**.
Optionally probe **header pin 23 (P92)** with a common ground. Expect the slow
low/high pattern on P93; the command does not request clock pulses on P92.
Compare the analyzer signal with each printed
readback. GPIO input readback alone does not prove the signal reaches the
header or sensor.

With the RTT bridge attached, wait for the final result even if NSH returns
an early prompt:

```bash
platforms/nuttx/Debug/nsh_console_exec.py --timeout 30 --until 'P93 CS GPIO result=' --log /tmp/gy912-cs-rtt.log 'gy912_test cs'
```

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
disconnected INT and malformed argument results. The archived excerpt and user
report extend the existing [P94 button confirmation](../evidence/gpio-button-interrupt-validation.md),
but do not replace the complete transcript, exact-image provenance, or direct
waveform evidence required for the remaining sensor gates.

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

- [Implementation plan](../../../plans/261002-gy912-icm20948-rzv2h/plan.md)
- [NuttX driver evidence tiers](../port-status-nuttx.md)
- [TDK ICM20948 datasheet DS-000189 v1.5](https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ds-000189-icm-20948-v1.5.pdf)

## Unresolved questions

Actual module/board revision, electrical interface, complete passing hardware
transcript, exact loaded ELF hash/source revisions, direct P93/P94 waveform
capture, and repeated/negative hardware cases remain unrecorded.
