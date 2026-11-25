# R-Car V4H CR52 PX4 HAL status (Sparrow Hawk)

PX4 on Cortex-R52 core 0 (CR52-0) of the R-Car V4H on Sparrow Hawk. Tiers
follow the RZ/V [PX4 HAL matrix](../port-status-px4-hal.md): stub, build-clean,
bounded on-target, validated. **Nothing here has run on a board** (no board
yet), so build-clean is the highest tier reached. NuttX driver tiers are in
[port-status-nuttx.md](port-status-nuttx.md).

Evidence (2026-11-25): `./build.sh renesas_sparrow-hawk_sih` exits 0 from a
clean tree and again with `--no-clean`. The ELF has one `PT_LOAD` at
`0x40100000`, filesz `0x158a80`, memsz `0x15e920` (1435936 B, 15.2 % of the
9 MiB window). The post-build window check prints `PASS` against
`R8A779G3_CR52_0_PX4`. `nm` shows `hrt_absolute_time`, `simulator_sih_main`,
`mavlink_main`, `ekf2_main` and `commander_main`, and no `SEGGER` symbol.
`./build.sh renesas_sparrow-hawk_default` exits 0 too: 1355040 B (14.4 %),
window check `PASS`.

| Piece | Path | Tier | Notes |
|---|---|---|---|
| Memory window | `boards/arm/rcar/sparrow_hawk/scripts/sparrow_hawk_cr52_0_px4.ld` (NuttX), `RCARV4H_PX4_SINGLE_CORE_WINDOW` | build-clean | 9 MiB `0x40100000`–`0x409FFFFF`; CR52-1 must not start. Host test `test/rcarv4h-cr52-elf-window-test.py` |
| EL2 timer set-up | `arch/arm/src/armv8-r/arm_head.S` (NuttX) | build-clean | `CNTVOFF = 0`, so `CNTVCT` equals the physical count |
| Toolchain | `platforms/nuttx/cmake/Platform/Generic-arm-none-eabi-gcc-cortex-r52.cmake` | build-clean | Same ABI as NuttX (`-mcpu=cortex-r52 -mfpu=neon-fp-armv8 -mfloat-abi=hard`; object build attributes compared). Adds `-fno-tree-vectorize`: GCC 13.2 stops with "unrecognizable insn" when it vectorizes EKF2 for NEON |
| HRT | `platforms/nuttx/src/px4/renesas/rcar/hrt/` | build-clean | EL1 virtual timer: `CNTVCT` free-run, `CNTV_CVAL` compare on PPI 27; reads `CNTFRQ`. Host test `test/rcarv4h-cr52-virtual-timer-encode-test.py` (conversion and ceiling) |
| micro_hal | `platforms/nuttx/src/px4/renesas/rcar/include/px4_arch/micro_hal.h` | stub | No PX4 GPIO, I2C or SPI yet; GPIO calls return `-ENOSYS` |
| board_reset | `platforms/nuttx/src/px4/renesas/rcar/board_reset/` | stub | `BOARD_HAS_NO_RESET`: CR52 cannot reset itself or the SoC |
| board_critmon, version, hw_info | `platforms/nuttx/src/px4/renesas/rcar/{board_critmon,version,board_hw_info}/` | build-clean | `PX4_SOC_ARCH_ID_RCARV4H` (`0x000D`); fixed UUID `RCARV4HCR520000` |
| Board target | `boards/renesas/sparrow-hawk/` (`sih`, `default`) | build-clean | NSH on HSCIF1, MAVLink TELEM1 on HSCIF3; parameters on TMPFS `/fs` (lost at reset) |
| SIH | `boards/renesas/sparrow-hawk/sih.px4board` | build-clean | Airframe 1100; waits for the board run |
| Real sensors (CN7) | — | not started | Needs the sensor part list |
| PWM/DShot outputs | — | not started | No V4H timer-output driver |

## Known limits

- **MAVLink baud is fixed at 115200.** The HSCIF driver has no termios baud
  change, so `SER_TEL1_BAUD` has no effect.
- **NuttX armv8-r FPU option trap (upstream, latent).** With `ARM_DPFPU32=n`
  on a core that has 32 D registers, `irq.h` places `REG_FPSCR` after 32 D
  registers but `arm_vectors.S` saves it after 16. This port keeps NEON
  (`ARM_DPFPU32=y`), which avoids it; do not switch to `fpv5-d16` without
  fixing it.
- No `up_backtrace` (armv8-r builds in ARM mode without frame pointers), so
  `SCHED_BACKTRACE` is off.
- No debug probe: diagnose from the HSCIF1 log only.
