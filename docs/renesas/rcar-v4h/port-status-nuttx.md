# R-Car V4H CR52 NuttX port status

The tiers are defined in [the RZ/V2H port status](../port-status-nuttx.md):
stub → source-audited → build-clean → bounded on-target → production. A
clean build or a host test is not on-target proof. No driver here has a
board transcript, because no board was available for this delivery
(2026-11-24).

Build evidence (2026-11-24): `build_rcarv4h.sh` exits 0 for `nsh`,
`nsh-cr52_1`, `gpio`, `i2c` and `spi-loopback` after clean builds, and the
window check passes for every ELF. The CR52-1 ELF sits at `0x40400000` and
all the others at `0x40100000`. `test/rcarv4h-cr52-elf-window-test.py` and
`test/rcarv4h-cr52-pmsav8-mpu-encode-test.py` pass. The RZ/V2H `nsh-rtt`
regression build passes too.

| Driver | Source | Tier | Config | Transcript | Open on target |
|---|---|---|---|---|---|
| Armv8-R entry (EL2 → EL1, HVBAR, CNTFRQ/CNTHCTL, SRE) | `armv8-r/arm_head.S`, `rcar/rcar_start.c` | build-clean | all | — | `rproc start` entry, EL1 `ICC_SRE` readback, ECC window zeroing |
| PMSAv8 EL1 MPU | `armv8-r/arm_mpu.c`, `rcar/rcar_mpu_regions.c` | build-clean | all | — (host encode test only) | `MPUIR.DREGION` on silicon, fault on another core's window |
| Caches | `armv8-r/arm_cache.c`, `cp15_*.S` | build-clean | all | — | Enable with the MPU map, coherency with U-Boot loads |
| `rcar_irq` (GICv3 distributor/redistributor, SPI routing) | `rcar/rcar_irq.c` | build-clean | all | — | Distributor ownership with two cores running, CR52-1 wait; trigger and priority calls unexercised |
| Tick (EL1 physical timer, PPI 30) | `rcar/rcar_timerisr.c`, `armv8-r/arm_timer.c` | build-clean | all | — | `sleep 5` against a host clock, `uptime` |
| HSCIF1 (CR52-0 console) | `rcar/rcar_serial.c`, `rcar_lowputc.c` | build-clean | `nsh` | — | TX/RX interrupts, interactive NSH at 115200 |
| HSCIF3 (CR52-1 console, CN7 8/10) | `rcar/rcar_serial.c`, `rcar_pfc.c` | build-clean | `nsh-cr52_1` | — | Pin function, NSH with CR52-0 running |
| CPG/MSTP and module reset | `rcar/rcar_clock.c` | build-clean | all | — | `MSTPSR` polling, Gen4 `SRCR`/`SRSTCLR` offsets |
| GPIO (CN7 11 → 13) | `rcar/rcar_gpio.c`, board `rcarv4h_gpio.c` | build-clean | `gpio` | — | Output level, input readback |
| GPIO pin interrupts | `rcar/rcar_gpio.c` | build-clean | `gpio` | — | Both-edge interrupt, `INTMSK` polarity |
| I2C3 (CN7 3/5) | `rcar/rcar_i2c.c`, board `rcarv4h_i2c.c` | build-clean | `i2c` | — | `i2c dev` scan, SCL rate, bus recovery |
| I2C4 (CN7 27/28) | `rcar/rcar_i2c.c` | build-clean | `i2c` | — | As I2C3 |
| MSIOF0 SPI (CN7 19/21/23/24/7) | `rcar/rcar_spi.c`, board `rcarv4h_spi.c` | build-clean | `spi-loopback` | — | Loopback self-test with jumper 19 → 21, actual SCK rate (MSO parent clock assumed 66.666 MHz), CS timing on a scope |

Board pre-flight (U-Boot `bdinfo`/`rproc` capture, a known-good Renesas
demo at `0x40100000`, DRAM ECC state) is blocked with no board. Capture it
before the first NuttX load, and store transcripts in this folder.
