# BMM150 SCI7 I2C Standalone Validation

**Date:** 2026-10-02  
**Board/core:** RDK-RZ/V2H, CR8-0  
**Config:** `rdk-rzv2h:bmm150`  
**Evidence:** host contract test passed; firmware build-clean; sensor hardware untested

## Scope and wiring

`bmm150` is a standalone NSH example (`apps/examples/bmm150`) that ports the
PX4 `BMM150.cpp` sequence to C over `/dev/i2c7` (`I2CIOC_TRANSFER`). It is the
first target gate for the SCI7 simple-I2C driver (`rzv_sci_i2c*.c`). It does
not start PX4 or register a uORB sensor.

| RDK pin | 40-pin header | Module signal | Software use |
|---|---|---|---|
| 3V3 | 1 | VCC / VIN | Sensor supply |
| P76 | 3 | SDA | RSCI7 SDA, AF1 |
| P77 | 5 | SCL | RSCI7 SCL, AF1 |
| GND | 6 | GND | Common ground |

The bus needs external 2.2–4.7 kΩ pull-ups to 3V3. Many breakouts include
them; confirm against the module schematic. Default address is 0x10 (SDO/CSB
straps select 0x10–0x13). Run `bmm150 -s` when the strap is unknown.

This standalone wiring is also the BMM150 portion of the fitted extension
reference: SCI7/P76/P77 at 0x10 is a shared bus with the proposed BMP390L
(0x77) and INA228 (0x45). The extension integration is not implemented in the
native NuttX/PX4 targets, so this bench remains a valid independent SCI7 gate;
do not retire it because the barometer or battery-monitor device is proposed.
Software integration can proceed from the reference source while physical
pull-up, module, and shared-bus qualification remains a later hardware gate.

## Build

```bash
platforms/nuttx/NuttX/build.sh bmm150
python3 test/rzv2h_bmm150_sample_contract_test.py
```

The config enables `RZV_SCI_I2C`, `RZV_SCI7_I2C`, `I2C_DRIVER`,
`I2C_RESET` and `EXAMPLES_BMM150`; SCI7 UART mode (`RZV_SCI7`) stays off.
NSH runs on RTT0. Building replaces the active NuttX configuration; rebuild
the prior profile with the same script when switching back.

## Run after an approved load

Reset, ELF loading and target-memory writes need explicit authorization.
No hardware operation was performed for this guide.

```bash
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 platforms/nuttx/NuttX/nuttx/nuttx
platforms/nuttx/Debug/nsh_console_exec.py --timeout 30 --log /tmp/bmm150-rtt.log \
  'ls /dev' 'bmm150 -s' 'bmm150 -n 20' 'bmm150 -f 100000 -n 10' \
  'bmm150 -a 0x14' 'bmm150'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

Syntax: `bmm150 [-b bus] [-a addr] [-f hz] [-n samples] [-s]`. Defaults are
bus 7, 0x10, 400000 Hz, 10 samples. Arguments are parsed strictly (decimal or
`0x` hex, no trailing text): bus 0..255, address 0x08..0x77 (reserved I2C
addresses rejected; `0x14` is accepted for the missing-device check), frequency
1..1000000 Hz, samples 1..1000. Invalid arguments fail before opening the bus.
`-s` prints `scan PASS` and exits 0 only if a BMM150 answered; it writes
POWER_CONTROL at each probed address because CHIP_ID reads 0 in suspend. All
messages in one transfer use the same frequency.

Sequence (matches PX4): power off/on with soft reset, poll CHIP_ID `0x32` and
sleep mode, self-test (OP_MODE bit0 then X/Y/Z LSB bit0), trim read (0x5D/0x62/0x68),
REPXY `0x17`/REPZ `0x52`/20 Hz normal mode, then 9-byte burst reads from 0x42
every 50 ms with repeated START. Output is fixed-point 0.01 µT plus `rhall`;
the last line is `bmm150: PASS` or `bmm150: FAIL`.

The console helper's exit status checks prompt/transport only. Read the
`PASS`/`FAIL` line in the transcript.

## Acceptance

| Check | Required result |
|---|---|
| Device node | `/dev/i2c7` present |
| Scan | 0x10 (or strapped address) reports `CHIP_ID 0x32 (BMM150)`; `scan PASS` |
| Identity/reset | No reset/identity error |
| Self-test | Passes (failure still samples but reports FAIL) |
| Samples | Requested count valid; stationary \|B\| roughly 25–65 µT; axes change when rotated |
| 100 kHz | `-f 100000` run passes |
| Missing device | `-a 0x14` fails boundedly with a NACK error, no hang |
| Invalid argument | e.g. `-a foo`, `-n 0` rejected before bus access |
| Recovery | Following default run passes |

Optional analyzer capture: repeated START between register write and read,
master NACK on the last read byte, SCL near 400 kHz.

## Evidence to archive

Board/module revision and wiring, pull-up values, parent/apps/NuttX
revisions, ELF SHA-256, approved load method, the full RTT transcript, and
any analyzer capture. A clean build or this host contract does not prove I2C
communication.

## Software checkpoint

On 2026-10-02:

- `python3 test/rzv2h_bmm150_sample_contract_test.py` passed 9 tests. They cover the defconfig selectors, the Kconfig dependency, PX4 register, bit-mask and overflow-sentinel parity, repeated-START use in code (not comments) and the P76/P77 board pins. A mutation check confirmed that removing `I2C_M_NOSTOP` or changing a mask fails the test.
- `build.sh bmm150` completed with zero warnings.
- The ELF contains `bmm150_main`, `rzv2h_sci_i2c_setup`, `sci_i2c_txi_isr`, `sci_i2c_tei_isr` and `nxsem_tickwait_uninterruptible`.
- Two regression builds passed: `hil-full` and the PX4 `renesas_rdk-rzv2h_default` target.
- Image after the review fixes: text 100056 bytes, `_SEGGER_RTT` at `0x081a2400`, ELF SHA-256:

```text
da651ccd893c82b2ef7d5d8e3f420ef99c6ac4b2bc693fa167cc7abe1034e2b2
```

## References

- [Implementation plan](../../plans/261002-1938-rzv2h-i2c-reaudit-bmm150-sample/plan.md)
- [I2C re-audit](../../plans/261002-1938-rzv2h-i2c-reaudit-bmm150-sample/reports/audit-261002-rzv2h-i2c-reaudit.md)
- [NuttX driver evidence tiers](port-status-nuttx.md)
- PX4 driver: `src/drivers/magnetometer/bosch/bmm150/`

## Unresolved questions

Module strap address, pull-up presence and a passing hardware transcript
remain unrecorded.
