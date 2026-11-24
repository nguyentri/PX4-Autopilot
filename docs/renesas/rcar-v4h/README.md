# R-Car V4H Cortex-R52 NuttX port (Sparrow Hawk)

NuttX NSH images for the R-Car V4H (R8A779G3) Cortex-R52 cores on the
Sparrow Hawk board. It runs AMP: each core gets its own image, and U-Boot
starts them with `rproc`. There is no PX4 target, no SMP and no Linux
alongside. Nothing in this port has run on a board yet; see
[port-status-nuttx.md](port-status-nuttx.md).

## Code

| What | Path (under `platforms/nuttx/NuttX/nuttx/`) |
|---|---|
| Armv8-R AArch32 core layer (EL2 entry, PMSAv8 MPU, caches, generic timer) | `arch/arm/src/armv8-r/`, `arch/arm/include/armv8-r/` |
| R-Car chip: GICv3 `rcar_irq`, tick, HSCIF, CPG/MSTP, PFC, GPIO, I2C, MSIOF SPI | `arch/arm/src/rcar/` (SoC addresses only in `hardware/*.h`) |
| Interrupt IDs | `arch/arm/include/rcar/rcarv4h_irq.h` |
| Board glue and configs | `boards/arm/rcar/sparrow_hawk/{src,configs}/` |
| Build script | `platforms/nuttx/NuttX/build_rcarv4h.sh` |
| Per-core ELF window allowlist | `platforms/nuttx/Debug/rcarv4h-cr52-elf-allowlists.json` |
| Host tests | `test/rcarv4h-cr52-elf-window-test.py`, `test/rcarv4h-cr52-pmsav8-mpu-encode-test.py` |

## Build

From the repository root:

```bash
platforms/nuttx/NuttX/build_rcarv4h.sh --list         # gpio i2c nsh nsh-cr52_1 spi-loopback
platforms/nuttx/NuttX/build_rcarv4h.sh nsh            # CR52-0, HSCIF1 console
platforms/nuttx/NuttX/build_rcarv4h.sh nsh-cr52_1     # CR52-1, HSCIF3 console
python3 test/rcarv4h-cr52-elf-window-test.py
python3 test/rcarv4h-cr52-pmsav8-mpu-encode-test.py
```

Output: `platforms/nuttx/NuttX/nuttx/nuttx` (ELF), `.bin`, `.hex`. After
each build the script checks that every `PT_LOAD` segment lies inside that
core's window. It prints `PASS`, then `RESULT=INSPECTION_ONLY`, because the
allowlist manifest is still `proposed`: no board load has authorized it.
Do a clean build after changing a defconfig, because `--no-clean` keeps the
old `.config`. Do not hand-run `tools/configure.sh` + `make`.

| Config | Core | Adds |
|---|---|---|
| `nsh` | CR52-0 | NSH on HSCIF1 |
| `nsh-cr52_1` | CR52-1 | NSH on HSCIF3 |
| `gpio` | CR52-0 | `/dev/gpio0` (CN7 pin 11 out), `/dev/gpio1` (CN7 pin 13, both-edge interrupt) |
| `i2c` | CR52-0 | `/dev/i2c3`, `/dev/i2c4`, `i2c` tool |
| `spi-loopback` | CR52-0 | `/dev/spi0`, `spi` tool, MSIOF0 loopback self-test at boot |

## Memory windows

Each image links at its own 3 MiB DRAM window. The EL1 MPU maps only that
window, the `0xE6000000` peripheral block and the GIC, so an access to
another core's window faults.

| Core | Window | Config |
|---|---|---|
| CR52-0 | `0x40100000`–`0x403FFFFF` | `RCARV4H_BUILD_CR52_0` |
| CR52-1 | `0x40400000`–`0x406FFFFF` | `RCARV4H_BUILD_CR52_1` |
| CR52-2 | `0x40700000`–`0x409FFFFF` (reserved, no image) | — |

`RCAR_ZERO_IMAGE_WINDOW` (default y) zeroes the window from `_sbss` to its
end before the caches are enabled. The SDK lists executable-RAM ECC
initialisation as open, and a cache line fill from ECC DRAM that was
never written can fault. The linker scripts align `_edata` and `_sbss` to
the 64-byte cache line, so the image load and the zeroing together write
every line of the window.

## Loading and start order (not yet run on a board)

This is the expected U-Boot sequence. The board pre-flight has not been
captured yet (no board available), so the exact `rproc` syntax and U-Boot's
own memory use are unverified.

```text
=> rproc init
=> <load nuttx.bin for CR52-0 to 0x40100000>   (tftp / fatload / loady)
=> rproc load 0 0x40100000 <size>
=> rproc start 0                                # wait for nsh> on HSCIF1
=> <load nuttx.bin for CR52-1 to 0x40400000>
=> rproc load 1 0x40400000 <size>
=> rproc start 1                                # wait for nsh> on HSCIF3
```

Rules that follow from shared hardware:

- **Start CR52-0 first.** CR52-0 resets and enables the shared GIC
  distributor. CR52-1 only waits for it, for up to `RCAR_GICD_WAIT_MS`
  (default 2000 ms), and then reports the timeout.
- **Restarting one core alone is unsupported.** A CR52-0 restart resets
  the distributor under a running CR52-1. Restart both cores, in order.
- **Shared read-modify-write registers** (CPG `MSTPCR*`, PFC) are written
  only at boot. Starting the cores one after another keeps those writes
  serialised.
- **A GPIO group belongs to one image.** `rcar_gpiowrite` changes `OUTDT`
  by read-modify-write at runtime, with interrupts masked on the calling
  core only, so two images driving pins of one group can lose updates.
- **`rcar_irq` ownership:** each core configures its own redistributor and
  routes its own SPIs. Every driver, the HSCIF consoles included, claims
  its SPI first and fails with `-EBUSY` if the other image has it enabled
  and routed to itself. All interrupts are Group 1, because the R52 has
  one security state. `rcar_irq_set_type` writes the shared `GICD_ICFGR`
  word only when the trigger changes, and refuses with `-EBUSY` to change
  an enabled interrupt. The trigger-type and priority calls are
  build-clean only.
- For a first sign of life, set `RCAR_EL2_MARKER` to write one character
  (`RCAR_EL2_MARKER_CHAR`, `!`) at EL2 before anything else runs. Progress
  letters `A`/`B`/`C` follow from `rcar_start.c`.

## Consoles and CN7 wiring

Both consoles run at 115200 8N1.

| Function | Signal | Location |
|---|---|---|
| CR52-0 console | HSCIF1 TX `GP0_14`, RX `GP0_15` | FTDI port B on CN4 (U-Boot leaves it set up) |
| CR52-1 console | HSCIF3 | CN7 pins 8 (TX) / 10 (RX) |
| GPIO loopback | `GP2_12` out / `GP2_05` interrupt | CN7 pin 11 → pin 13 (jumper) |
| I2C3 | SDA / SCL on GP8 | CN7 pins 3 / 5 |
| I2C4 | SDA / SCL on GP8 | CN7 pins 27 / 28 |
| MSIOF0 SPI | SCK / TXD / RXD / SYNC (CS0) / SS2 (CS1) on GP1 | CN7 pins 23 / 19 / 21 / 24 / 7 |

The CN7 signals pass through level shifters (TXS0108E for GPIO; the I2C
lines use TCA9517 repeaters with 4.7 kΩ pull-ups on both sides). CN7 pins
36 and 37 are unused. I2C5 carries the PMIC and has no Kconfig option on
purpose.

## Driver notes and limits

- **Tick:** EL1 physical generic timer (PPI 30) at the 16.666667 MHz
  system counter. EL2 writes `CNTFRQ` and `CNTHCTL = 3`.
- **GPIO interrupts:** `INTMSK` reads 1 for an enabled pin, and writing 0
  masks it (Linux `gpio-rcar.c`). The plan had the polarity backwards; the
  driver follows Linux.
- **I2C:** the Gen3+ clock registers (`ICCCR2`/`ICMPR`/`ICHPR`/`ICLPR`)
  from Linux `i2c-rcar.c`, with a 133.33 MHz S0D6 parent and SCL recovery
  through the `ICMCR` override.
- **MSIOF0 SPI:** PIO through the 256-word FIFOs, following the Linux
  `spi-sh-msiof.c` Gen4 flow. The rest of the Gen4 rules:
  - The device needs TX to receive, so a receive-only transfer clocks out
    0xff.
  - Modes 0–3 are supported, with 8–32-bit words.
  - The parent clock is `RCAR_MSIOF_CLK_HZ`, default 66.666 MHz (Renesas
    BSP value, not verified). The driver does not program `MSOCKCR`.
  - **Chip select is the hardware frame signal.** It is asserted for each
    frame of up to 256 words and released between frames and between
    calls, whatever `SPI_SELECT()` says. A device that needs CS held
    across exchanges needs a GPIO chip select.
  - The loopback self-test (jumper CN7 19 → 21) proves only the data path
    and clocking, not CS timing.
- **Pin tables** live in each driver (`rcar_i2c.c`, `rcar_spi.c`) and the
  board header, not in a separate pinmap file.
- **Not ported:**
  - The `0x18A00000` merged-interrupt mask block: it is R-Car X5H code,
    and the Renesas V4H memory map has no region there (contract section
    6).
  - INTC-EX, DMA, a CR52-2 image.
  - A debug probe: TRACE32 is deferred, and there is no J-Link or RTT.

## Renesas BSP data not used

The Renesas FreeRTOS CR52 BSP is the main reference for entry and GIC
sequences. Some of its data is wrong for V4H:

| BSP data | Problem | Used instead |
|---|---|---|
| `r_i2c` bases (`0xC06D0000`…) | Fall in PCIe1 memory on V4H | `r8a779g0.dtsi` (`0xE66D0000`, `0xE66D8000`) |
| `r_i2c` `ICCCR` values | Gen2 SCL divider | Gen3+ `ICCCR2`/`ICMPR`/`ICHPR`/`ICLPR` |
| `device_cfg.h` `SRCR` `0x2200`/`0x2280`; MSIOF fallback `0x9D8` | Do not match the `MSTPCR` `0x2D00` block | Linux Gen4 `SRCR` `0x2C00`, `SRSTCLR` `0x2C80` |

## References

- Delivery contract: [`plans/reports/brainstorm-261124-1321-rcar-v4h-cr52-sparrow-hawk-delivery-contract.md`](../../../plans/reports/brainstorm-261124-1321-rcar-v4h-cr52-sparrow-hawk-delivery-contract.md)
- Plan: [`plans/261124-0751-rcar-v4h-cr52-sparrow-hawk-nuttx-bsp/plan.md`](../../../plans/261124-0751-rcar-v4h-cr52-sparrow-hawk-nuttx-bsp/plan.md)
- Platform research: [`plans/reports/research-261124-1254-rcar-v4h-cr52-sparrow-hawk-nuttx-port.md`](../../../plans/reports/research-261124-1254-rcar-v4h-cr52-sparrow-hawk-nuttx-port.md)
- Entry sequence: [`plans/reports/research-261124-1312-rcar-v4h-cr52-real-entry-sequence.md`](../../../plans/reports/research-261124-1312-rcar-v4h-cr52-real-entry-sequence.md)
- Reference SDK: `/mnt/c/Workspace/00_sst_git/00_gen5_sdk/v4h_cr52/` (local only)
