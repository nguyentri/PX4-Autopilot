# BMP280 SCI7 I2C Standalone Validation

**Date:** 2026-11-01  
**Board/core:** RDK-RZ/V2H, CR8-0  
**Config:** `rdk-rzv2h:bmp280`  
**Evidence:** host tests passed; firmware build-clean; one board run failed with
no ACK at 0x76 or 0x77, so sensor hardware remains **pending**

## Scope and wiring

`bmp280` is a standalone NSH example (`apps/examples/bmp280`) that drives a
Bosch BMP280 over `/dev/i2c7` with `I2CIOC_TRANSFER`. It reads the chip ID,
soft-resets the part, reads the 24-byte trim block and runs a bounded number of
forced conversions. It then prints compensated temperature (degC) and pressure
(Pa). It does not start PX4, register a uORB sensor or use the generic NuttX
BMP280 lower half.

| RDK pin | 40-pin header | Module signal | Software use |
|---|---|---|---|
| 3V3 | 1 | VCC / VIN | Sensor supply |
| P76 | 3 | SDA | RSCI7 SDA, Mode 1 |
| P77 | 5 | SCL | RSCI7 SCL, Mode 1 |
| GND | 6 | GND | Common ground |

Module straps:

- **CSB** must be tied high (3V3) for I2C. If CSB is low at power-up, the part
  latches SPI mode until it is power-cycled.
- **SDO** low selects 0x76, the default. SDO high selects 0x77, which needs
  `-a 0x77`. There is no silent fallback to the other address.

The board fits R180/R181 pull-ups on P76/P77. A module with its own pull-ups
places them in parallel. The sample accepts a BMP280 (ID 0x58) or a BME280
(ID 0x60, temperature and pressure only; humidity is not read). Any other ID,
such as a BMP388/BMP390, fails the run.

The [sensor wiring profiles](../pinmap.md#sensor-wiring-profiles) define who
owns the shared SCI7 bus. The standalone sample owns only the selected address
for the duration of one run. BMM150 on the same bus is **not validated**
([BMM150 guide](bmm150-i2c-validation.md)) and is not evidence for SCI7
transfers.

## Build

```bash
platforms/nuttx/NuttX/build.sh bmp280
python3 test/rzv2h-bmp280-sample-test.py
```

The config enables `RZV_SCI_I2C`, `RZV_SCI7_I2C`, `I2C_DRIVER`, `I2C_RESET`
and `EXAMPLES_BMP280`. It keeps SCI7 UART/SPI, RIIC7, `SENSORS_BMP280` and the
BMM150/GY-912 examples off. NSH runs on RTT0. Building replaces the active
NuttX configuration; to switch back, rebuild the prior profile with the same
script.

`platforms/nuttx/Debug/rzv2h-sample-build.py --profile bmp280` is the
archive path the sample lab expects. On 2026-11-01 it failed for every profile
(BMM150 too) with `Missing shared build lock helper`. The cause is
`platforms/nuttx/NuttX/build.sh` resolving `Tools/firmware_workspace/build_lock.sh`
relative to the tool's isolated `/tmp` snapshot. The board run below therefore
used a direct `build.sh bmp280` ELF that was hashed before loading.

## Run

```bash
platforms/nuttx/Debug/rzv2h-ipc/rzv2h-load-one-core.sh cr8_0 <bmp280-elf>
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 <bmp280-elf>
X=platforms/nuttx/Debug/nsh_console_exec.py
$X --timeout 10 --log 01-ls.log 'ls /dev'
for c in 'bmp280 -n 10' 'bmp280 -a 0x75 -n 1' 'bmp280 -n 0' 'bmp280 -n 10'; do
  $X --timeout 30 --until 'bmp280: (PASS|FAIL)' --log "$(echo $c | tr ' ' _).log" "$c"
  $X --timeout 10 'ps'
done
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

Send one `bmp280` command per helper call. The builtin runs in the background
(see below), so its output arrives after the next `nsh>` prompt: a plain
multi-command call times out on the first one, and `--marker` overlaps the
next command with the running one. `--until` waits for the terminal line.
`bmp280 -n 0` prints usage and then `bmp280: FAIL`; that FAIL is the expected
rejection, so check its log for `Usage: bmp280`.

Syntax: `bmp280 [-b bus] [-a addr] [-f hz] [-n samples]`.

- Defaults: bus 7, address 0x76, 100000 Hz, 10 samples.
- Arguments are parsed with `strtol(..., 0)` and range-checked: bus 0..255,
  address 0x08..0x77, frequency 10000..400000 Hz, samples 1..100. Trailing
  text is rejected, but a leading `0` means octal (`-b 010` is bus 8), a
  leading sign or space is accepted, and a repeated option keeps the last
  value. This matches the BMM150 sample's parser.
- Malformed values, extra operands and `-n 0` are rejected before the bus is
  opened. `-h` prints usage and exits 0.
- Use `-a 0x75` as the missing-device case only after confirming nothing on the
  bus answers at that address.

SCI-I2C frequency requests are ceilings. At the nominal 100 MHz P5CLK, 100000
selects 97,656 Hz and 400000 selects 260,416 Hz (see
[port status](../port-status-nuttx.md)).

Each sample runs this sequence:

1. Write ctrl_meas `0x55` (T×2, P×16, forced).
2. Wait the datasheet maximum of 43,225 µs.
3. Poll status for at most 20 ms more.
4. Accept the conversion only when the measuring bit is clear and ctrl_meas
   has returned to sleep.
5. Read the 6 data bytes from 0xF7.

Register reads are a NOSTOP write followed by a read (repeated START).
Compensation is the Bosch integer algorithm in 64-bit with overflow checks.
Results outside -40..85 degC or 30000..110000 Pa are failures.

The output must contain, in this order:

```text
bmp280: addr 0x76 chip ID 0x58 (BMP280)
bmp280: [0] T=<degC> degC P=<Pa> Pa      (exactly n records, indices 0..n-1)
bmp280: 10 samples
bmp280: PASS
```

Every failure after the bus is opened closes the fd, prints
`bmp280: error <errno>` and `bmp280: FAIL`, and exits nonzero. A failed open
prints `open ... failed` and `bmp280: FAIL`. Invalid arguments print usage
and `bmp280: FAIL` without opening the bus. `-h` prints usage only and exits
0. The defconfig lacks `CONFIG_SCHED_WAITPID`, so NSH runs the
builtin in the background, as it does for BMM150. Read the terminal line, then
check with `ps` that no `bmp280` task is left. The console helper's exit status
proves transport only.

## Acceptance

| Check | Required result |
|---|---|
| Device node | `/dev/i2c7` present |
| Identity | Exactly one `addr 0x76 chip ID 0x58 (BMP280)` line (the sample also accepts a BME280 `0x60 (BME280)`; the runner oracle does not) |
| Samples | Requested count, ordered, explicit degC/Pa, inside the envelope; stationary pressure is local barometric pressure, not a fixed sea-level value |
| Missing device | Unused address fails boundedly (`-6` ENXIO), no hang, no leftover task |
| Invalid argument | `-n 0`, `-a foo` rejected before bus access |
| Recovery | The next default run passes |

The runner oracle (`rzv2h-sample-runner.py`, `bmp280` native branch) requires
the same whole-line grammar and order, so echoed command text cannot pass it.
An optional analyzer capture would show the repeated START, the master NACK on
the last byte and the SCL rate. Without one, the electrical timing is
unobserved.

## Board run, 2026-11-01

ELF built directly with `build.sh bmp280` (parent `cf975186d91`, apps
`10f44d28e1b`, NuttX `d403f1159c3`, all three with uncommitted work):

```text
9fa1def3604437dccedcffddd85830754a69e822c4b5733708185bb4961705df  nuttx.elf
```

- Load: J-Link 52000195 had no other owner. A guarded CR8-0 load verified the
  image (PC `0x40806400`). The RTT bridge ran on `127.0.0.1:19021`, with
  `_SEGGER_RTT` at `0x081a2400`.
- `ls /dev`: `console`, `i2c7`, `null`.
- `bmp280 -n 10`: `chip ID read failed: -6`, then `bmp280: error -6` and
  `bmp280: FAIL`.
- `bmp280 -a 0x77 -n 1`: same -6 NACK.
- `ps`: only Idle and `nsh_main`, so both failures were bounded with no leftover
  task.
- After the bridge stopped, a read-only GDB snapshot (`jlink-gdb-oneshot.py`,
  GPIO base `0x10410020`) showed the pads and controller were set up correctly:
  - PMC7 = 0xC0 and PFC7 = 0x11000000: P76/P77 are in peripheral Mode 1.
  - PIN7 = 0xC0: both lines idle high.
  - `R_SCI7.CCR3` = 0x00040203: MOD=4, Simple-I2C.
  - `R_SCI7.CSR` = 0xE0008000: RXDMON=1.

The pin mux and the Simple-I2C mode are right, and the bus is not stuck low.
Because the on-board pull-ups hold the lines high with or without a module,
no ACK at either strap address points to the module side:

- not powered or not connected;
- CSB low at power-up (SPI latched);
- SDA/SCL swapped;
- not a BMP280 at 0x76 or 0x77.

The SCI7 address phase itself has never been observed on target (see the
SCI-I2C row in [port status](../port-status-nuttx.md)). If the module checks
out, put a scope or analyzer on SCL/SDA during `bmp280 -n 1` to confirm that
a START and the 0x76 address byte are actually driven.

Transcripts are in
`plans/261101-1810-bmp280-sci7-i2c-sample/artifacts/direct-build/board-run/`.
The run proves bounded failure handling on the target. It does **not** prove
SCI7 data transfers or the sensor.

### Re-run with CSB at GND and SDO at 3V3, 2026-11-01

This run used the same ELF and the same guarded load (VERIFY PASS, no reset
markers in the logs).

- `bmp280 -a 0x77 -n 10` and `bmp280 -a 0x76 -n 10` both returned
  `chip ID read failed: -6` and then `bmp280: FAIL`.
- `ps` was clean afterwards.
- P76/P77 were again in Mode 1 and idle high, with SCI7 in Simple-I2C mode.
- P72/P73 also read as Mode 1. Those are SCI5 telemetry pins left set by an
  earlier image, and they don't involve SCI7.

The result is expected. **CSB at GND selects SPI**, and a BMP280 does not
answer on I2C after CSB has been low. Rewire CSB to 3V3 and power-cycle the
module, then use `-a 0x77`, because SDO at 3V3 selects 0x77. The logs are in
`plans/261101-1810-bmp280-sci7-i2c-sample/artifacts/direct-build/board-run-csb-gnd-sdo-3v3/`.

### Re-runs with CSB at 3V3, 2026-11-01

These runs used the same ELF (SHA-256 `9fa1def3…`) and the same guarded load.

**SDO at 3V3 (module power-cycled):**

- `bmp280 -a 0x77 -n 10` returned `-6`, and `-a 0x76 -n 1` returned `-6`.
- After that, the RTT bridge closed and the GDB one-shot reported
  `DBGEN is not asserted`, which means CR8-0 was held in reset. The bridge log
  had no reset marker.
- The `-f 10000` command never reached the board. Its log and the next `ps`
  log were written in the same second the `0x76` run ended.
- A recovery load ("core held in reset; starting it", then VERIFY PASS) failed
  again within about 50 s, after one more `-6` run.

**SDO at GND (board reset by the user):**

- After the reload, `bmp280 -n 10` (0x76) and `-a 0x77 -n 1` both returned
  `-6`.
- This time CR8-0 stayed alive. `ps` passed four times over about 95 s, and
  again after the last run.
- The earlier resets did not reproduce. Their cause is unknown, and the
  bmp280 command is not shown to trigger them.

**Analysis:**

- Every strap combination has now NACKed at both addresses.
- Per `port-status-nuttx.md` row 28, SCI-I2C has never completed an external
  transfer on target. The driver is therefore as much a suspect as the module.
- The FreeRTOS reference ran a BMP280 at 0x76 on this RSCI7 route with FSP
  `r_sci_b_i2c`. Its P76/P77 pin config sets only peripheral mode and the noise
  filter (no open-drain), which matches `board.h`.

The logs are in `board-run-csb-3v3-sdo-3v3/`, `board-run-csb-3v3-recovery/` and
`board-run-csb-3v3-sdo-gnd/` under
`plans/261101-1810-bmp280-sci7-i2c-sample/artifacts/direct-build/`.

### Logic-analyzer capture, 2026-11-02

The sample was rebuilt with `platforms/nuttx/NuttX/build.sh bmp280` (ELF SHA-256
`ad728b0c929235df3b1194335ac169ca2eff63f39b2630ff56c23ee85a8ce32f`, `_SEGGER_RTT`
0x081a2400) and loaded on CR8-0. The module was wired with CSB and SDO open and
VCC on 3V3. Two loops of `bmp280 -n 1` at 0x76 gave 60 of 60 and 99 of 99
`chip ID read failed: -6`, with no pass.

The user's capture (`BMP_280_I2C.png`) decodes as one clean address phase:

| Field | Observed |
|---|---|
| START | SDA falls while SCL is high |
| SCL period | 10.25 us (about 97.6 kHz, matches the 97,656 Hz setting) |
| Address byte | 1110 1100 = 0xEC (0x76, write) |
| 9th clock | SDA high: NACK |
| End | SDA low, SCL high, then SDA rises: STOP |

The SCI7 Simple-I2C driver therefore produces a correct START, address, clock
rate and STOP, and it reports the NACK correctly as -6. No device pulls SDA low
during the ACK slot. The fault is on the sensor side of the probe point:
module power or ground, the wire from the probe point to the module, a CSB
latched low at power-up, or a dead module. This capture covers only the address
phase; data-phase transfers remain unproven until a device ACKs.

Logs: `plans/261101-1810-bmp280-sci7-i2c-sample/artifacts/rebuild-261102/board-run/`.

After the user reconnected the module pins, both the same ELF and a rebuild that
also accepts BME280 ID 0x60 (SHA-256 `2d74ec6c4de7dffa0f0eca2a9c69610ebe735856662d6b91a156fa66b21ac98a`)
still returned `chip ID read failed: -6` at 0x76 and at 0x77. Logs:
`artifacts/rebuild-261102/board-run-reconnected/` and `artifacts/rebuild-261102b/board-run/`.

With VCC and CSB at 3.3 V and SDO at GND (expected address 0x76), the
`2d74ec6c…` image again returned `chip ID read failed: -6` at 0x76 and 0x77.
CR8-0 was found held in reset before this load. Logs:
`artifacts/rebuild-261102b/board-run-csb-3v3-sdo-gnd/`.

## Evidence to archive for a pass

- Module part and revision, wiring, CSB/SDO straps, and the pull-ups fitted.
- Parent, apps and NuttX revisions; ELF SHA-256; the load method.
- The full RTT transcript covering every acceptance row.
- Any analyzer capture.

Promote `port-status-nuttx.md` only from such a transcript, and only for
SCI7/BMP280 external transfers. That promotion does not cover timing or the
other SCI channels.

## Recovery

Stop the bridge before any load or GDB session. If the bridge exits 3, read
the bridge log and the probe owners before reloading with the guarded one-core
loader. Never blind-retry. To restore a prior profile, rebuild it and reload
its ELF.

## Software checkpoint

On 2026-11-01:

- `test/rzv2h-bmp280-sample-test.py` passed 24 tests:
  - compensation against the Bosch reference vector (25.08 degC,
    100653.25 Pa);
  - signed and unsigned trim decoding, the invalid-trim, marker, domain and
    overflow errors;
  - a host simulation of the real `bmp280_main.c`: wrong ID, NACK, timeouts,
    stale data, CLI rejection and cleanup;
  - must-fail mutations: NOSTOP removed, ID changed, big-endian trim, wrong
    offset, wrong `t_fine`;
  - static register, Kconfig and defconfig contracts.
- Also passing:
  - inventory (133 configs) and its test;
  - the sample runner and lab tests, which include the BMP280 oracle and its
    mutations;
  - the SCI-I2C runtime and mode tests;
  - the BMM150 contract test.

## References

- [Implementation plan](../../../plans/261101-1810-bmp280-sci7-i2c-sample/plan.md)
- [NuttX driver evidence tiers](../port-status-nuttx.md)
- PX4 driver: `src/drivers/barometer/bmp280/`
- Bosch BMP280 datasheet BST-BMP280-DS001

## Unresolved questions

- The module part, CSB/SDO straps and power are unrecorded.
- No passing hardware transcript exists yet.
- The archive build tool's lock-helper path is still broken.
