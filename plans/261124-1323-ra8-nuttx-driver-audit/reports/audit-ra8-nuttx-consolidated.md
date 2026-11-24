# RA8 NuttX driver audit: consolidated report (RA8P1, EK-RA8P1)

Date 2026-11-24. Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.

The audit was static only. The user declined builds, and nothing was flashed or run on hardware. The references are the 88 EK-RA8P1 FSP samples, the dual-core DSP sample, and `R7KA8P1KF_core0.h` / `core1.h`.

## Outcome

On the EK-RA8P1, most drivers would not work as configured.
- **Static parity with FSP:** UART, the SDRAM init sequence, the ADC_B register map, the clock register layout and the event numbering (498 of 500) match.
- **Would fail as configured:**
  - Every bus except the UART: I2C, SPI, SCI-I2C, SCI-SPI and I3C.
  - CANFD, Ethernet and USB.
  - MRAM, OSPI, SDHI and MIPI-CSI.
  - AGT, CAC, GPT PWM and the CM33 startup path.
- **Evidence tier:** no driver is above E1 (source-audited). The CM85 foundation and ICU reach E2 through the two `adc-b` builds. `ra_mbed_crypto` is an empty E0 stub. Tiers were left unchanged in `docs/renesas/port-status-*.md`, which have no RA8 driver rows to demote.

## Phase reports and verdicts

| Phase | Report | Verdict | Findings |
|---|---|---|---|
| 1 Baseline | [audit-baseline-and-build-matrix.md](audit-baseline-and-build-matrix.md) | PASS_WITH_LIMITATIONS (2/30 built) | n/a |
| 2 Arch foundation | [audit-arch-foundation.md](audit-arch-foundation.md) | DONE_WITH_CONCERNS | ARCH-01..19 |
| 3 ICU/ELC/DTC/DMAC | [audit-icu-elc-dma.md](audit-icu-elc-dma.md) | DONE_WITH_CONCERNS | EVT-01..08 |
| 4 Serial/SPI/I2C/I3C | [audit-serial-spi-i2c-i3c.md](audit-serial-spi-i2c-i3c.md) | FAIL (UART: pass) | BUS-01..13 |
| 5 Timers/WDT/LPM | [audit-timers-watchdog-power.md](audit-timers-watchdog-power.md) | FAIL | TMR-01..15 |
| 6 ADC_B | [audit-adc-b.md](audit-adc-b.md) | DONE_WITH_CONCERNS | ADC-01..07 |
| 7 Memory/storage | [audit-memory-storage.md](audit-memory-storage.md) | MRAM/OSPI/SDHI FAIL; SDRAM concerns; linker PASS_WITH_LIMITATIONS | MEM-01..18 |
| 8 Connectivity | [audit-connectivity.md](audit-connectivity.md) | FAIL | CON-01..19 |
| 9 Camera/crypto | [audit-camera-crypto.md](audit-camera-crypto.md) | MIPI-CSI FAIL; crypto BLOCKED (empty stub) | CAM-01..10 |
| 10 Dual-core IPC | [audit-dual-core-ipc.md](audit-dual-core-ipc.md) | FAIL | IPC-01..13 |
| 11 PX4 HAL/boards | [audit-px4-hal-boards.md](audit-px4-hal-boards.md) | DONE_WITH_CONCERNS | PX4-01..11 |

## Ranked findings

The controller spot-checked the findings marked "verified" against the source before consolidating.

### Critical
| ID | Core | Finding | RA8E1 |
|---|---|---|---|
| CON-01 / CON-02 | CM85 | CANFD global init addresses unit 0 while only CANFD1 is clocked. Sleep is never released, and the mode waits have no timeout, so the `canfd` config hangs at boot. | no config enables it |
| TMR-05 (verified) | CM85 | AGT does a 16-bit write to AGTMR1 at odd offset 0x09 (`ra_agt.c:227`, `ra_agt.h:43`). This UsageFaults during bringup in the `agt` config. | no config enables it |
| BUS-01 | CM85 | RIIC, RSPI_B and I3C pins are never muxed by the driver or the board. The `board.h` macros for them are also wrong (BUS-06). | check `i2c-gy912` pin setup |

### High
| ID | Core | Finding | RA8E1 |
|---|---|---|---|
| ARCH-01 (verified) | both | IRQ pinsets copy their IRQ bits into the PFS output and direction bits (`ra_gpio.c:251`). `~(1 << R_PFS_PDR)` then clears bit 4 (the pull-up) instead of the direction bit (`ra_gpio.c:803`). SW1 is driven high. | yes, 8 configs |
| ARCH-02 / ARCH-03 / ARCH-04 / IPC-01 / IPC-02 | CM33 | CM33 bring-up has five defects:<br>• It re-runs the CPU0 clock init.<br>• The NuttX CM33 images link at CPU0 addresses.<br>• SysTick uses the CM85 clock, so ticks run 4x slow.<br>• Nothing releases CPU1.<br>• The per-core linker scripts are never used. | n/a |
| EVT-01 | both | The ELC peripheral (ELSR) index map is compacted, so every slot from 8 up is wrong. As a result the ADC trigger goes to the IOPORT1 slot. | shared enum, latent |
| EVT-02 (verified) | CM85 | DMAC "unit 1" does not exist on RA8P1. `R_DMA1_BASE` 0x4000AC00 is `R_DTC_BASE`, so the init writes DTCCR. Channels 10-17 are accepted. | gated by RA8P1_GROUP |
| ADC-01 / ADC-02 | CM85 | Neither `adc-b` image links the ADC-B driver; `/dev/adc0` is never registered. The hwtrigger path cannot work even when linked. | no |
| BUS-02 / BUS-03 / BUS-04 | both | RIIC reports success on NACK in interrupt mode. Its timeout counters wrap, so timeouts never fire. There is no repeated START. | yes, `i2c-gy912` |
| BUS-05 / BUS-11 | CM85 | The SCI simple-I2C driver does not work (bus speed never set, ACK check inverted). I3C is switched off by a missing Kconfig option and would not compile if switched on. | shared code |
| BUS-07 / BUS-08 | both | The RSPI_B baud rate is computed from the wrong clock. SCI-SPI's divisor is 4x too low. | yes, SPI configs |
| TMR-01 / TMR-02 | both | GPT PWM writes the active registers while buffers are enabled, then forces a transfer of the unwritten buffers. The polarity is inverted. | yes, `pwm` and `escs` |
| TMR-03 | CM85 | GPT4-9 share MSTPE27 on RA8_GEN2, but the driver uses per-channel bits. GPT5 (motor 2) is likely never clocked. | probably not |
| TMR-04 (verified) | CM85 | CAC passes the bitmask `R_MSTP_MSTPCRC_CAC` (= 1) as a module ID. This starts and stops the DMAC instead of the CAC. | no config enables it |
| PX4-01 (verified) / PX4-02 = TMR-11 | both | `hrt_init()` runs twice: `px4_init.cpp:159` and `evk-ra8p1/src/timer_config.cpp:159`. `hrt.c` hard-codes GPT0 for the clock and IRQs regardless of `HRT_TIMER`. | **yes, direct:** time likely frozen with `HRT_TIMER 1` |
| IPC-03 / IPC-04 | both | The IPC unit direction and receive IRQ are inverted compared with FSP. Four logical channels alias two hardware channels. | n/a |
| PX4-04 / PX4-05 = TMR-15 | both | The dual-core PX4 IO path is not wired end to end. Both cores claim GPT3/5/11/13, DMAC channels 0-3 and SCI5. | n/a |
| CON-03..08 | CM85 | Further CANFD, Ethernet and USB defects:<br>• CANFD bit-timing layout is wrong, and the CANFD clock is never set.<br>• Ethernet uses port 0 / RMII instead of the EK's port 1 / RGMII.<br>• The RMAC/PHY layer is unreachable.<br>• Descriptors have no cache maintenance.<br>• USBCLK is 200 MHz instead of 48 MHz. | no config enables it |
| MEM-01 / MEM-02 (verified) | CM85 | `RA_MRAM` depends on `ARCH_CHIP_RA8P1`, which is defined nowhere. Its partition map assumes 2 MB of MRAM; the device has 1 MB. | no |
| MEM-04 / MEM-05 | CM85 | OSPI uses the wrong unit and CS (the EK flash is unit 0 CS1 at 0x90000000). The memory-mapped command is not shifted, and the opcode is wrong. | shared, latent |
| MEM-07 / MEM-08 | CM85 | SDRAM A11/A12 (P510, P608) are never muxed. Timings are set for 100 MHz while SDCLK is 125 MHz. | no |
| MEM-11 / MEM-12 | CM85 | SDHI sends every short response as R1, so ACMD41 fails. The R2 response is not shifted. | no |
| CAM-01..03 | CM85 | The MIPI D-PHY is never initialised. The sensor sends YUV422 while CSI/VIN expect RGB888. The framebuffer is at 0x60000000, where there is no SDRAM. | no |

### Medium and Low (by theme)
- **Cache maintenance missing on CM85 DMA paths:** EVT-03 (DTC/DMAC), CON-07, CON-09 (USB DMA), CAM-04, MEM-06 (OSPI), IPC-08, ARCH-08 (CCR and M85 errata). All share one remediation pattern.
- **CMake vs Make.defs drift:** ARCH-12, EVT-04, TMR-14, CON-14, CAM-08, IPC-10, MEM-18. A CMake build would differ from the Make build.
- **Config hygiene:**
  - BUS-09: the `sci-spi` config uses SCI0 as both the console and SPI.
  - BUS-10: the `gps` config never enables SCI3.
  - CON-11: the CAN example opens `can0`, but the board registers `can1`.
  - PX4-03: TEL3 and RC are swapped.
  - IPC-12.
  - ARCH-05: a stray `*/` breaks any SCI4-console build.
- **Clock and power:** ARCH-06 (divider decode), ARCH-10 (drift from the FSP quickstart), TMR-08 (SOSC never started), TMR-09 (LPM can enter standby automatically), TMR-10 (WDT NMI mode).
- **Calibration and correctness:** ADC-03 and ADC-04; the PX4 HAL ADC copies the same calibration pattern.
- **Dead or unbuilt code:** ARCH-13 (`ra_flash.c` referenced but missing), ARCH-15 (`ra_sci_spi.c` added twice), CAM-10 (`ra_mbed_crypto` empty), IPC-07 (IPCC unbuildable), CON-06 (five PHY files unreachable), MEM-17 (dead linker scripts).

## Prior review C1-C3
All three are closed in source: `ra_poeg_register` exists, AGT uses `RA_PCLKB_FREQUENCY`, and `ra_adc.c` uses `R_ADC12_CH_BASE`. The same review's runtime claims are confirmed and extended: sci-i2c (BUS-05), ospi-b (MEM-04/05), agt (TMR-05/06/07) and i3c (BUS-11).

## RA8E1 (`fpb-ra8e1`) blast radius, direct only
- ARCH-01: SW1 IRQ pin (8 configs).
- BUS-02/03/04: RIIC (`i2c-gy912`).
- BUS-07: RSPI_B baud.
- TMR-01/02: GPT PWM (`pwm`, `escs`).
- PX4-01/02: HRT double init and GPT0 hard-code. Likely frozen PX4 time; this is RA8E1's top blocker if PX4 is expected to run.
- PX4-06: GPT write-protect key.
- EVT-03: cache maintenance.

## User decisions (2026-11-24)
These decisions change how some findings are classified and how they should be fixed:
1. **PX4 on RA8E1 is expected to run today.** PX4-01 and PX4-02 (TMR-11) are therefore Critical for `fpb-ra8e1`, because its PX4 time is likely frozen. They move to the front of the fix order.
2. **Dual-core PX4 (CM33 as the IO core) is an active goal.** These findings are defects, not deferrals: ARCH-02/03/04, IPC-01..04, PX4-04/05 (= TMR-15) and PX4-10. A GPT/DMAC/SCI ownership split between CM85 and CM33 is now a required design input; it has not been decided yet.
3. **CANFD follows the EK sample, using mixed classic and FD frames.**
   - CON-01 remediation: move the `canfd` config and the board glue to the sample's channel, CANFD0 (`refs/ra8p1/ek_ra8p1/can_fd/can_fd_ek_ra8p1_ep/e2studio/ra_gen/hal_data.c:67` `.channel = 0`), and clock and initialise that unit consistently.
   - CON-03/04 remediation: program both the nominal and the data bit timing. Leave the controller in mixed classic + FD mode, not FD-only.
   - The CON-11 device name follows the channel.
4. **Hardware crypto is out of scope.** CAM-10 (`ra_mbed_crypto` is an empty stub) is reclassified as an intentional deferral. The `crypto` config stays software-only mbedTLS.
5. **The skill was corrected.** `audit-ra8p1-px4-nuttx-port` now treats the sample's `bsp_feature.h` and `bsp_elc.h` as primary sources, and its collector prints the matching `BSP_FEATURE_*` and `ELC_EVENT_*` / `ELC_PERIPHERAL_*` lines.

## Suggested fix order (for a later `/ak-cook` plan; no fixes were made)
1. Shared and RA8E1-direct (RA8E1 PX4 must run): PX4-01/02 first, then ARCH-01, BUS-02/03/04, TMR-01/02.
2. RA8P1 boot breakers: TMR-05, CON-01/02, TMR-04, EVT-02.
3. Bus pin muxing and clocks: BUS-01, BUS-06, BUS-07, BUS-08.
4. CM33 bring-up as one work item: ARCH-02/03/04, IPC-01/02/03/04, PX4-04/05/10.
5. Per-peripheral fixes: ELC map, ADC, storage, connectivity, camera. Then fix CMake parity.
6. Build every config with `build_ra8p1.sh` plus `fpb-ra8e1`, then run bounded on-target tests to move past E1.

## Unresolved questions
1. What is the CM85/CM33 ownership split for GPT channels, DMAC channels and SCI ports? Dual-core PX4 is active, and PX4-04/05 cannot be fixed without it.
2. When does the CM85 release the CM33, and how are `ipc-cm33` / `wdt-cm33` and the PX4 `evk-ra8p1-io-cm33` image loaded? This bounds the fixes for ARCH-02/03 and IPC-01/02.
3. Hardware manual facts:
   - whether GPT4-9 share MSTPE27
   - which clock RSPI_B uses when BPEN=1
   - whether `ADCHCR.SGSEL` is a mask or an index
   - how `IPC_IRQ0` / `IPC_IRQ1` are routed per core
   - whether the CM33 can run from the 0x2010xxxx TCM alias
   - the SOSC reset state
   - whether WDT underflow can be taken as an IRQ
   - whether each core has its own ICU
   - whether the GWCA bus master can reach DTCM
4. Board facts:
   - the EK SDRAM part
   - whether P510/P608 are A11/A12
   - the M85 silicon revision
   - whether SCI7/SCI8 = TEL3/RC is the intended wiring
   - which analog pins are intended
5. Intent:
   - whether the MRAM params partition shares the 1 MB
   - whether to keep the FSP-style linker path
   - whether the PX4 bootloader is meant to be built
