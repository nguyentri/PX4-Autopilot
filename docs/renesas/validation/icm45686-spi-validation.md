# ICM-45686 SPI0 Standalone Validation

**Date:** 2026-11-01<br>
**Board/core:** RDK-RZ/V2H, CR8-0<br>
**Config:** `rdk-rzv2h:icm45686-dma-ssl-rtt`<br>
**Evidence:** host, build and one bounded on-target RTT run passed
([archived transcript](../evidence/icm45686-spi-rtt-261101.txt)). The physical
SSLA0/SCK waveform gate is open because no analyzer was available.

## Scope

`icm45686_test [count]` identifies one ICM-45686 on SPI0, resets and
configures it, drains `count` (1..1000, default 10) high-resolution 20-byte
FIFO packets, then stops the FIFO and powers the sensor down. It prints the
cached first/last raw sample in the sensor frame and one result line:

```text
ICM45686 result=<err> samples=<done>/<requested> bursts=<n> empty=<n> max_fifo=<n>
```

The image is a standalone NuttX diagnostic. It does not start PX4, run the
C++ ICM45686 driver, publish uORB topics or qualify the `dualcr8` profile.

| Item | Contract |
|---|---|
| Bus | SPI0 P90 MOSI, P91 MISO, P92 SCK, P93 hardware SSLA0; mode 3, 8-bit, 8 MHz request, achieved 2..24 MHz accepted |
| Transport | DMAC3 channels 48/49; one SSL assertion per exchange; every exchange ≤241 bytes |
| Identity | WHO_AM_I `0xe9`; mismatch returns `-ENODEV` before any register write |
| FIFO | count read twice, second wins; count ≥409 or INT1 FIFO_FULL fails the run; any invalid header fails the run |
| Deadlines | 1 s reset, 500 ms no-progress, fixed 2 s acquisition cap |
| Exclusions | Kconfig requires SPI0 DMA + hardware SSL and excludes the ICM20948 test and drone sensor extension; one sensor on P93 only |

Verify module power and logic levels against its schematic before wiring.
P94/P95 are unused by this profile.

## Host and build evidence

```bash
python3 test/rzv2h-icm45686-contract-test.py      # 16/16
platforms/nuttx/NuttX/build.sh icm45686-dma-ssl-rtt
```

The host test compiles the real board C bodies against a register-level
sensor model with a fake clock. Mutation spot checks (nibble swap, `>=409`
→ `>409`, first-count-wins, removed startup sleep, swapped INTF/DRIVE restore,
skipped RESET_DONE, accepted ODR-change packets) were all detected.
Regressions passed: ICM20948 contract 12, SPI instance 14, SCI-SPI mode 20,
DMAC runtime 19, drone profile 19. `checkpatch.sh` passed on the new sources.

| Build | sha256 (ELF) |
|---|---|
| `icm45686-dma-ssl-rtt` (tested image) | `a9d6bf0527b386b356aa26915ec492630cf1ec78e1d1ced833a5fb06472f2ecf` |
| `gy912-dma-ssl-rtt` (compatibility) | `3a3a3fc9b763e7559d7e3fc6e001e6296fa873294416511746e69234510effdd` |
| `renesas_rdk-rzv2h_simple` (compatibility) | `72830de0d776d923e970d5f9ed84d9e8ed7a03987e63250b72f49f219c7e5a79` |
| `renesas_rdk-rzv2h_dualcr8` (compatibility) | `46ae2910d9e78fc50e49fe95fb894dc78cf7b45b539e06168b6ae061a3513c85` |

Build-clean compatibility images are software evidence only.

## Hardware procedure

```bash
elf=platforms/nuttx/NuttX/nuttx/nuttx
python3 platforms/nuttx/Debug/jlink-debug-preflight.py "$elf"
export JLINK_SERIAL=$(python3 platforms/nuttx/Debug/jlink-debug-preflight.py --print-serial)
platforms/nuttx/Debug/rzv2h-ipc/rzv2h-load-one-core.sh cr8_0 "$elf"
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 "$elf"
platforms/nuttx/Debug/nsh_console_exec.py --timeout 60 --log icm45686-rtt.log \
  'uname -a' 'icm45686_test 1' 'icm45686_test 20' 'icm45686_test 20' \
  'icm45686_test 1000' 'icm45686_test' 'free'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

Stop any other probe owner first (one probe, one owner). This image has no
`echo` builtin, so `--marker` cannot be used; check each `result=` line
instead of the console exit status. Bridge exit 3 means diagnose and recover
with the guarded loader; do not retry blindly. Never attach the CM33.

Pass requires `result=0 samples=N/N` for every command, plausible raw data
(accel magnitude ≈16384 LSB/g at rest), usage text for invalid counts, and a
completed 1000-sample run.

## Observed result (2026-11-01)

Image `NuttX 0.0.0 d763971843-dirty Nov  1 2026 18:26:17`, sha256 above,
`_SEGGER_RTT` 0x081a2400. The guarded loader reported `VERIFY PASS`; the
bridge logged no reset markers.

| Command | Result | Bursts | Empty | max_fifo |
|---|---|---|---|---|
| `icm45686_test 1` | 1/1 | 1 | 1 | 12 |
| `icm45686_test 20` | 20/20 | 3 | 1 | 65 |
| `icm45686_test 20` | 20/20 | 7 | 1 | 11 |
| `icm45686_test 1000` | 1000/1000 | 207 | 39 | 108 |
| `icm45686_test` | 10/10 | 2 | 1 | 11 |
| `icm45686_test 20` (after usage cases) | 20/20 | 8 | 2 | 13 |

All results were `0`. Arguments `0`, `1001`, `abc` and `5 5` printed usage.
Accel ≈ (-6900, 11150, -9560) has magnitude ≈0.99 g; gyro stayed within about
±150 LSB (≈1 dps); temperature ≈790 raw (≈31 °C). `ts=0` is expected because
the sample does not enable SMC timestamps, matching PX4. No ODR-change first
packet was seen, so the strict invalid-packet policy stands. `free` after the
runs showed 5744 bytes used.

A second load of the same image (fresh guarded load, sensor in a new
orientation) repeated the matrix with `result=0` for 1/1, 20/20, 20/20,
1000/1000 (217 bursts, max_fifo 99) and 10/10; accel magnitude ≈0.995 g;
`0` printed usage and `free` stayed at 5744 bytes
([second transcript](../evidence/icm45686-spi-rtt-261101-run2.txt)).

## Open gates

- P93 SSLA0 and SCK waveform: one assertion per exchange, no frame >241
  bytes, achieved SCK. Not measured.
- Cold boot, long-duration and temperature stress: not run.
- PX4 driver/uORB path on this sensor: out of scope for this sample.
