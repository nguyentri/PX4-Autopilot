---
phase: 11
title: "Phase 11: PX4 HAL and boards"
status: pending
priority: P1
effort: "1d"
dependencies: [3, 4, 5]
---

# Phase 11: PX4 HAL and PX4 board integration

## Scope
- HAL: `platforms/nuttx/src/px4/renesas/ra8/` (adc, board_critmon, board_hw_info, board_reset, dshot, hrt, io_pins, led_pwm, micro_hal, spi, tone_alarm, version; `cpuload/` exists but is not added). `renesas/ra8p1/` is not linked; confirm that.
- Boards: `boards/renesas/evk-ra8p1/` (`{default,dshot,test}.px4board`, src/, init/, Kconfig, manifest.xml, nuttx-config/, px4io_cm85/) and `boards/renesas/evk-ra8p1-io-cm33/` (px4io_ipc/, src/, nuttx-config/)
- Mapping: `platforms/nuttx/cmake/px4_impl_os.cmake` (`ARCH_CHIP_R7KA8P1KFLCAC` → `ra8`)

## Tasks & Steps
1. HRT: which of the `hrt` sources is compiled, its GPT channel, rearm and the ISR-vs-cancel race. Cross-check with the phase-5 ownership table.
2. PWM/DShot: `timer_config.cpp` on CM85 and CM33 vs the GPT ownership table (the baseline theme "duplicated motor-output ownership").
3. SPI/I2C: bus tables, chip selects and DRDY in `spi.cpp`, `i2c.cpp` and `board_config.h` vs `manifest.xml`, the EK `pin_data.c` and the phase-4 findings.
4. Serial: TEL/GPS/RC `ttyS*` in the `.px4board` files vs the SCI channels and pins.
5. CM33 IO board: `MODULES_PX4IOFIRMWARE`, the `px4io_ipc` `add_subdirectory`, and consistency with the phase-10 IPC addresses.
6. Init order: `init.c`, `board_common.c` and `init/rc.board_*`. Check the escaped-prompt issue in `evk-ra8p1/Kconfig` and whether that Kconfig is sourced. Note that `default_bk.px4board` and `init_bk/` are leftovers.
7. Apply the RA8E1 blast radius to every HAL finding (the `fpb-ra8e1` consumers).

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-px4-hal-boards.md`
