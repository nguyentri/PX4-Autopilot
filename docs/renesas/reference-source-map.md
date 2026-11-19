# RZ/V2H Reference Source Map

**Date:** 2026-10-24
**Status:** Canonical input map for driver porting and `firmware:audit`
**Scope:** RDK drone integration and core-matched RZ/V2H EVK IP examples

Use this map before comparing a NuttX driver with Renesas example code. It
prevents a project for one core or peripheral IP from being treated as proof
for another.

## Reference precedence

For register coordinates, use the matching-core CMSIS I/O headers when they
are present: bases, channel domains, offsets, widths and fields. Use the HWM
where those headers are absent. Record disagreements instead of combining
layouts from different authorities. This precedence is the maintainer's
explicit choice; a matching layout does not prove physical operation.

For peripheral IP behavior on a target core, use evidence in this order:

1. Matching EVK project under `refs/rzv2h_evk/`.
2. Its `e2studio/configuration.xml` and non-generated source in `e2studio/src/`.
3. Its generated `e2studio/rzv_gen/{hal_data,pin_data,vector_data}.*` and
   `e2studio/rzv_cfg/fsp_cfg/` settings.
4. Its selected FSP implementation under `e2studio/rzv/fsp/src/r_*/`.
5. The integrated PX4/FreeRTOS tree under
   `refs/rzv2h_drone_px4-dev/` for RDK application ownership and
   cross-driver configuration.
6. A legacy or different-core example only as labelled secondary evidence.

`Debug/` and `Release/` are derived artifacts. Do not use them as the source
contract when the non-generated project files exist. A CMSIS header proves a
register layout; it does not prove driver lifecycle, pins, clocks, or IRQ
routing. Build success and example presence are not target validation.

**Board boundary (EVK ≠ RDK):** `refs/rzv2h_evk/` targets the Renesas
**EVK** board. Its `pin_data.c`, connector, and transceiver choices are not
evidence for the **RDK-RZ/V2H** board this port runs on. Use EVK projects for
IP behavior (registers, clocks, ELC/IRQ, driver lifecycle) only. RDK pin
ownership for software integration comes from the selected `RDK` pin set in
`refs/rzv2h_drone_px4-dev/configuration.xml`, its `docs/HARDWARE.md`, and the
pinned PX4 board/startup sources. Generated RDK pin data and the matching
schematic corroborate that mapping for physical qualification; they are not
prerequisites for configurable source changes, host tests, or builds. Pins
outside those sources (e.g. CAN/ADC) still need separate RDK electrical
authority before hardware use. Chip-level pin functions per PSEL:
`refs/rzv2h_scripts/rzv2h_pin_mapping.csv`.

### Current RDK reference availability

The local `refs/rzv2h_drone_px4-dev/` export matches public parent commit
`ea03689163229f3f5982a579e79e264598547b7b`. Its PX4 and XRCE Agent dependencies
are recovered at their exact gitlink revisions; see the
[recovery record](../../plans/261011-2017-rzv2h-drone-reference-port/reports/execution-session-01.md).
PX4 board sources live under `px4/boards/renesas/rzv/src/{board,hal,shim,services}/`;
startup is `px4/boards/renesas/rzv/init/rcS`.

`rzv_gen/pin_data.c` and `rzv/fsp/src/` are **absent** from this snapshot;
the reference README describes generation/population with e2studio/FSP.
References to those paths describe expected generated inputs, not files
available for a current source audit. Use the available pinned board backends
and selected XML, plus explicitly labelled core-matched IP references.
The sensor-extension schematic
SCH-20260713 is also absent. Software integration proceeds using the selected
XML, hardware guide, and board sources, with configurable wiring and a
default-off extension profile. Obtain generated output and confirm fitted
board routing during target validation. Existing GY912/simple wiring remains
separate: P94 is their DRDY/button input and the extension's second CS output.
Do not substitute EVK pins or apply the extension mapping globally.
The XML's only active/selected pin set is `RDK`, selecting P93/P94/P95 as
SSLA0/1/2. P36 SSLA2 belongs to inactive `RZV2H-IMDT.pincfg`; it is not the active
RDK alternative. This resolves the software mapping; it does not prove physical
extension routing. See [pin ownership](./pinmap.md#px4-configuration-profiles) for
the current native and planned extension profiles.

The reference hardware guide names ICM-45686, while comments in its SPI table
name ICM-45688 using the same `icm45686` driver. Keep the driver selection for
software work and verify fitted part identity at bring-up. Likewise, reference
`init/rcS` starts SiK telemetry at 115200, whereas its hardware guide and the
native default use 57600; select baud explicitly for the fitted radio.

## Core path convention

Most examples use this exact layout:

```text
refs/rzv2h_evk/<driver>/<driver>_rzv2h_evk_cm33_ep/e2studio
refs/rzv2h_evk/<driver>/<driver>_rzv2h_evk_cr8_0_ep/e2studio
refs/rzv2h_evk/<driver>/<driver>_rzv2h_evk_cr8_1_ep/e2studio
```

Always select the project matching the audited core. CR8-0 and CR8-1 can
share FSP source while still differing in `configuration.xml`, generated BSP
core selection, vectors, memory, or startup.

## Generated SVD

`rzv2h.svd` is generated by `generate-rzv2h-svd.py` from the CR8 branch of
`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H.h`
(`R9A09G057H/cr/iodefine.h` and its `iodefines/`, including `cr8/`). Offsets
and sizes follow the C layout of each `R_*_Type`; bit fields come from the
`*_b` views and are cross-checked against `iobitmasks/`.
Interrupts (478 GIC SPIs, CMSIS `IRQn` numbering, so the NuttX IRQ is the
value + 32) come from the CR8 `IRQn_Type` enum in
`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/mcu/rzv2h/cr/bsp_irq_id.h` and sit on the
peripheral that raises them. Routing interrupts (NMI, `IRQn` pins, ICU and
`SELn` IRQSEL slots) sit on `R_INTC`; core and GIC events sit on `R_INTC_GIC`.
`<cpu>` takes the CR8 MPU/FPU/priority macros of `R9A09G057H.h`. Its name is
`other` because the CMSIS-SVD 1.3 schema has no Cortex-R names. The revision
`r0p3` comes from MIDR `0x410FC183`, read on the RDK CR8-0 on 2026-11-09.
`test/rzv2h-svd-generator-test.py` compiles the headers and checks every
register offset, size, base address, field mask and interrupt number. The
`Source/` startup and system files carry no register data.

Known FSP 4.2.0 header issues the generator reports:

- I3C `DATBAS1`-`DATBAS7` and `EXDATBAS`: the header uses an 8-byte stride and
  `EXDATBAS` at `0x2A0`. The hardware manual, the FSP 3.0.0 EVK headers and
  `rzv_i3c.h` use `0x224 + 4 * n` and `0x310`, so the generator's `ERRATA`
  table emits those offsets (`--no-errata` emits the header layout).
- GPIO `IEN2B_L`/`IEN2B_H`: the header puts both in one union at `0x1878`, so
  H overlaps L. Every other per-port GPIO family places port 2B at family base
  + `0x138`, and `rzv_gpio.h` uses `0x1938`/`0x193C`, so `ERRATA` emits those
  offsets. The hardware manual (Table 4.2-16) confirms `PFC_IEN_2B` at
  `1958h`/`195Ch` from the `0x10410000` PFC base, which is `0x1938`/`0x193C`
  from the FSP `0x10410020` base.
- `R_CANFD_Type` is laid out as `0x1C000` bytes (`CFDTM[384]` of `0x80`) while
  its `Size =` comment says `0x14000`; the SVD follows the layout.
- `R_SCI_B0_RDR_BY_RDAT_Pos/_Msk` (28 / `0x10000000`) contradict the
  `RDR_BY_b.RDAT` bit field `[7..0]`; the SVD follows the bit field.
- `bsp_irq_id.h` comments give the wrong IRQ number for `SCI0_BFD` (118, enum
  119) and for `MHU_RSPn_S` (they repeat the `MSGn_S` numbers). The SVD uses
  the enum values.

## EVK example inventory

| Reference family | CM33 | CR8-0 | CR8-1 | Primary NuttX audit surface | Read first |
|---|---:|---:|---:|---|---|
| `adc_e` | yes | yes | yes | ADC_E | `r_adc_e.c`, ADC cfg, generated HAL/vector/pin data, `src/adc_ep.c` |
| `can_fd` | yes | yes | yes | CAN-FD | `r_canfd.c`, CAN cfg, generated HAL/vector/pin data, `src/can_fd_ep.c` |
| `elc` | yes | yes | yes | ELC and trigger routing | `r_elc.c`, `r_gpt.c`, generated vectors, application `hal_entry.c`/`elc_ep.h` |
| `freertos` | yes | yes | yes | OS/tick example only | task config and GTM tick source; not a peripheral authority |
| `gpt` | yes | yes | yes | GPT/PWM | `r_gpt.c`, GPT cfg, generated HAL/vector/pin data, `src/gpt_timer.c` |
| `gpt_input_capture` | yes | yes | yes | GPT capture | `r_gpt.c`, generated configuration, application `hal_entry.c` |
| `gtm` | yes | yes | yes | GTM and HRT timer basis | `r_gtm.c`, GTM cfg, generated vectors, `src/gtm_ep.c` |
| `i3c_b` master | yes | no | no | Future I3C-B master | `r_i3c_b.c`, generated config, CM33 boot prerequisites |
| `i3c_b` slave | yes | no | no | Future I3C-B slave | `r_i3c_b.c`, generated config and vectors |
| `intc_irq` | yes | yes | yes | ICU external IRQ | `r_intc_irq.c`, cfg, generated vectors, `src/intc_irq_ep.c` |
| `intc_tint` | yes | yes | yes | ICU TINT | `r_intc_tint.c`, cfg, generated vectors, `src/intc_tint_ep.c` |
| `poeg` | yes | yes | yes | POEG/GPT output safety | `r_poeg.c`, `r_gpt.c`, generated vector/pin data, `src/poeg_ep.c` |
| `preceding` | yes | no | no | Multicore boot prerequisites | CM33 CA55/CR8 load/start, PLL, power, XSPI, and PMIC code |
| `riic_master` | yes | yes | yes | Native RIIC master | `r_riic_master.c`, cfg, generated vector/pin data, `src/i2c_sensor.c` |
| `riic_slave` | yes | yes | yes | RIIC slave/future coverage | `r_riic_slave.c`, `r_riic_master.c`, both cfgs, `src/i2c_slave.c` |
| `sci_b_uart` | yes | yes | yes | SCI-B serial and lowputc | `r_sci_b_uart.c`, UART cfg, generated vector/pin data, `src/uart_ep.c` |
| `spi_b` | yes | yes | yes | Native SPI-B and DMAC-B parity | `r_spi_b.c`, `r_dmac_b.c`, cfgs, generated vector/pin data, `src/spi_ep.c` |
| `wdt` | yes | yes | yes | WDT and reset routing | `r_wdt.c`, GTM/INTC dependencies, cfgs, vectors, timer/IRQ setup |

Project metadata records FSP 3.0.0; preserve the project or content revision
in audit reports. The table maps reference choices rather than tracking corpus
size.

## UART distinction

`sci_b_uart` is SCI-B, not SCIF/SCIFA. Its three projects configure SCI-B
channel 0 and provide a complete FSP driver plus generated configuration.
They are primary evidence for `rzv_serial.c` and SCI-B portions of
`rzv_lowputc.c`.

No SCIF/SCIFA application example or `r_scif`/`r_scifa` FSP driver exists in
the EVK corpus. For `rzv_scif.c`, use the matching-core R9A09G057H CMSIS/BSP
files inside an EVK project for register, clock, reset, module-stop, and ELC
evidence only. Representative CR8-0 files are:

```text
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/cr/iodefines/scifa_iodefine.h
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/iobitmasks/scifa_iobitmask.h
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/mcu/rzv2h/bsp_override.h
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/mcu/all/bsp_module_stop.h
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/mcu/rzv2h/cr/bsp_feature.h
refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/rzv/fsp/src/bsp/mcu/rzv2h/bsp_elc.h
```

`refs/rzv2h_gb_ether/drivers/uartc.c` and `uart.h` are secondary CA55
support-code evidence. They do not establish CR8/CM33 SCIFA pins or lifecycle.

## Ethernet and PHY authority

No Ethernet/Ether-PHY EVK example project exists under `refs/rzv2h_evk/`.
The primary GBETH behaviour authority is the FSP 4.2 driver pair
`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/r_gmac_b/` (MAC/MTL/DMA init, ordered stop,
descriptor tail, interrupt set) and `r_ether_phy/` (MDIO, reset, autoneg and
the KSZ9131 TX DLL sequence: MMD 2 register 77, clear bit 12, pulse bit 13).
Register offsets and bit fields come from the CMSIS
`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/cm/iodefines/gbeth_iodefine.h`
(`R_GBETH_Type`); the generated `rzv2h.svd` carries the same layout as
`R_GBETH0`/`R_GBETH1` (from the CR8 header copy). The
[CMSIS bit-definition regression](../../test/rzv2h-ether-gbeth-cmsis-register-definitions-test.py)
checks every driver offset, bit, shift and mask macro against that header.

RDK PHY evidence: `refs/rzv2h_drone_px4-dev/r9a09g057h4-rdk-ver1-disabled-spi-gpt-serial-i2c-canfd.dtb`
enables only `ethernet@15C30000` (GBETH0, `phy-mode = rgmii-id`) with PHY
`ethernet-phy-id0022.1640` (KSZ9131) at MDIO address 0 and
`rxc/txc-skew-psec = 1400`; GBETH1 is disabled. NuttX enables the KSZ9131 TX
DLL (ID-gated) and leaves the pad skews at PHY defaults; RGMII timing still
needs a board transcript.

The following legacy CA55 sources remain secondary same-SoC/IP evidence:

```text
refs/rzv2h_gb_ether/plat/ether/EtherMain.c
refs/rzv2h_gb_ether/plat/ether/r_ether.c
refs/rzv2h_gb_ether/plat/ether/r_phy.c
refs/rzv2h_gb_ether/plat/include/ether_register.h
refs/rzv2h_gb_ether/plat/include/r_ether.h
refs/rzv2h_gb_ether/plat/include/r_phy.h
refs/rzv2h_gb_ether/include/rzv2h_irq.h
```

That project targets Cortex-A55/AArch64, not CM33 or CR8. It can inform the
GBETH register sequence, PHY-specific programming, clocks, pads, and event
numbers, but every core-local address view, cache/MPU rule, IRQ route, reset,
and DMA contract still needs CR8/CM33 authority and target evidence. The
[Ethernet production-C regressions](../../test/rzv2h-ether-runtime-test.py)
check register and lifecycle contracts; CR8 IRQ selectors remain422/437.
Both GBETH units have independent source support and selectable registration
profiles. The [two-port regression](../../test/rzv2h-ether-two-port-runtime-test.py)
supersedes the earlier blanket MAC1 denial. Board pad/parent-clock handoff,
fitted PHYs and connected traffic still require physical qualification.

The hardware manual Rev.1.40 p595 defines `PHY_INTF_TYPE` as MII=0/RGMII=1;
`MAC_SPEED` is read-only. The supplied ADC-E CR8-0, CR8-1 and CM33 CMSIS
`R_CPG_Type` places `CPG_CSDIV0/1` at `0x4f0/0x4f4`. NuttX follows those
I/O-header offsets under the precedence above; the strict reference regression
compares all three layouts, full CSDIV addresses and per-MAC SYSC coordinates.
The manual pp669–670, the supplied `r_ether.c` sequence and Renesas's
[Linux CPG definitions](https://raw.githubusercontent.com/torvalds/linux/master/drivers/clk/renesas/rzv2h-cpg.h)
use `0x500/0x504` from the block origin `0x10420000`. The I/O headers use
base `0x10420010`; both descriptions therefore identify CR8 addresses
`0x10420500/0x10420504` (CM33 secure `0x40420500/0x40420504`). There is no
absolute-address disagreement. The earlier conflict report compared offsets
without their origins; adding HWM offsets directly to the I/O-header base was
incorrect. Current NuttX addresses follow the I/O headers and agree with the
manual/reference. Physical clock/link qualification remains separate. See the
[current status and validation](port-status-nuttx.md).

## SCI-B mode authority

The supplied FSP corpus has no SCI-B SPI or simple-I2C implementation. Use the
official [RZ/V2H hardware manual](https://www.renesas.com/en/document/mah/rzv2h-group-users-manual-hardware?r=25471761),
R01UH1032EJ0140 Rev.1.40, July31,2026, for these modes. Section7.3 covers all
ten channels, including mode eligibility, baud and pulse widths, initialization,
FIFO/interrupt behavior and stop/error ordering. The exact PDF digest and
section/page map were recorded during the2026-10-24 source audit. The pinned
PDF SHA256 is `2ef1f64ef87f033b4cd2de12c485f34b9d766a53d2aa0bb2ad152a7d1647cf8f`.
Mode eligibility is covered by Tables7.3-1/2/4 (pp2589–2594); baud/modulation
by Tables7.3-8/9/15/19/21 (pp2611–2615) and §7.3.10 (p2759); initialization
and transition by §§7.3.7.4/7.3.9.5/7.3.18.13–15 (pp2729–2730/2757/2783);
interrupt/error ordering by §§7.3.17.2/4/7.3.18.4/7/8 (pp2769–2772/2779/2781).
The [SPI](../../test/rzv2h-sci-spi-mode-runtime-test.py) and
[I2C](../../test/rzv2h-sci-i2c-mode-runtime-test.py) regressions check the
implemented behavior without claiming external timing qualification.
CMSIS/BSP remains the local register/clock/IRQ coordinate cross-check; UART
FSP does not establish SPI/I2C behavior. RDK routes and electrical timing require
their own physical qualification.

## Known reference gaps

| NuttX surface | Gap |
|---|---|
| SCIF/SCIFA | No application/FSP driver example; CMSIS/BSP and CA55 polling code only |
| Ethernet MAC/DMA | No per-core EVK example project; FSP 4.2 `r_gmac_b` + CMSIS `gbeth_iodefine.h` are primary, legacy CA55 project secondary |
| Ethernet PHY/RGMII | FSP 4.2 `r_ether_phy` KSZ9131 sequence + RDK DTB (KSZ9131, `rgmii-id`, addr 0); pad skews, straps and link timing need physical qualification |
| Native SPI (`rzv_spi.c`) | CR8 `spi_b` FSP uses the same bases/register bank and `FSP_IP_RSPI` lifecycle. Use `r_spi_b.c` and its core-matched BSP as primary behavior authority; the legacy `drivers/rspi.c` is secondary. RDK pins remain independent. |
| SCI-B I2C/SPI modes | All ten CMSIS instances share the SCI-B layout (`0x3ff` channel mask). Mode-specific FSP is absent; the official hardware manual above supplies behavioral authority. Its source audit and regression evidence are distinct from RDK route, waveform and physical qualification. |
| SDHI | No dedicated example in the current EVK corpus |

For a future `firmware:audit`, list these gaps in “What was not checked.” Do
not fill them by silently substituting a different IP block or core.
