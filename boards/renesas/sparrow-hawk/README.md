# Renesas R-Car V4H Sparrow Hawk: PX4 on CR52-0

PX4 on Cortex-R52 core 0 of the R-Car V4H (R8A779G3). Build-clean only: it
has not run on a board yet. Status: `docs/renesas/rcar-v4h/port-status-px4-hal.md`.

| Target | Contents |
|---|---|
| `renesas_sparrow-hawk_sih` | SIH quad (airframe 1100), MAVLink on HSCIF3. Use this one. |
| `renesas_sparrow-hawk_default` | Base set without sensor or actuator drivers (CN7 sensors not chosen yet) |

## Build

```bash
./build.sh renesas_sparrow-hawk_sih              # clean build
./build.sh --no-clean renesas_sparrow-hawk_sih   # iterate (defconfig edits need a clean build)
```

Output: `build/renesas_sparrow-hawk_sih/renesas_sparrow-hawk_sih.{elf,bin}`.
The post-build check fails the build if any `PT_LOAD` segment leaves the
9 MiB window `0x40100000`–`0x409FFFFF` (`R8A779G3_CR52_0_PX4`).

## Load (U-Boot rproc, not yet run on a board)

```text
=> rproc init
=> <load renesas_sparrow-hawk_sih.bin to 0x40100000>   (tftp / fatload / loady)
=> rproc load 0 0x40100000 <size>
=> rproc start 0
```

Do not start CR52-1: its NuttX window `0x40400000`–`0x406FFFFF` lies inside
the PX4 image window.

## Serial ports

| Port | Device | Location | Use |
|---|---|---|---|
| HSCIF1 | `/dev/console`, `/dev/ttyS0` | FTDI on CN4 | NSH and boot log, 115200 |
| HSCIF3 | `/dev/ttyS1` (TELEM1) | CN7 pins 8 (TX) / 10 (RX), 3.3 V | MAVLink, fixed at 115200 |

The HSCIF driver cannot change the baud at run time, so `SER_TEL1_BAUD` has
no effect. Parameters live on TMPFS at `/fs` and are lost at every reset.
No debug probe is available: the HSCIF1 log is the only diagnostic.
