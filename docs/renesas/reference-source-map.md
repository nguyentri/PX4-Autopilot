# RZ/V2H Reference Source Map

**Date:** 2026-08-09
**Status:** Canonical input map for driver porting and `firmware:audit`
**Scope:** RZ/V2H EVK CM33, CR8-0, and CR8-1 examples plus explicitly bounded fallback trees

Use this map before comparing a NuttX driver with Renesas example code. It
prevents a project for one core or peripheral IP from being treated as proof
for another.

## Reference precedence

For a target core, use evidence in this order:

1. Matching EVK project under `refs/rzv2h_evk/`.
2. Its `e2studio/configuration.xml` and non-generated source in `e2studio/src/`.
3. Its generated `e2studio/rzv_gen/{hal_data,pin_data,vector_data}.*` and
   `e2studio/rzv_cfg/fsp_cfg/` settings.
4. Its selected FSP implementation under `e2studio/rzv/fsp/src/r_*/`.
5. The integrated PX4/FreeRTOS tree under
   `refs/px4-freertos-posix-renesas-fsp/` for RDK application ownership and
   cross-driver configuration.
6. A legacy or different-core example only as labelled secondary evidence.

`Debug/` and `Release/` are derived artifacts. Do not use them as the source
contract when the non-generated project files exist. A CMSIS header proves a
register layout; it does not prove driver lifecycle, pins, clocks, or IRQ
routing. Build success and example presence are not target validation.

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
| `spi_b` | yes | yes | yes | Future SPI-B and DMAC-B parity | `r_spi_b.c`, `r_dmac_b.c`, cfgs, generated vector/pin data, `src/spi_ep.c` |
| `wdt` | yes | yes | yes | WDT and reset routing | `r_wdt.c`, GTM/INTC dependencies, cfgs, vectors, timer/IRQ setup |

The corpus contains 48 e² studio projects: 15 three-core families, two CM33
I3C variants, and one CM33 `preceding` project. Project metadata records FSP
3.0.0; preserve the project or content revision in future audit reports.

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

## Ethernet and PHY gap

No Ethernet/Ether-PHY EVK FSP example, `r_ether`, or `r_phy` exists under
`refs/rzv2h_evk/`. Keep using these legacy sources as secondary same-SoC/IP
evidence:

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
and DMA contract still needs CR8/CM33 authority and target evidence.

## Known reference gaps

| NuttX surface | Gap |
|---|---|
| SCIF/SCIFA | No application/FSP driver example; CMSIS/BSP and CA55 polling code only |
| Ethernet MAC/DMA | No per-core EVK FSP example; legacy CA55 project only |
| Ethernet PHY/RGMII | No per-core EVK FSP example; exact fitted PHY/strap/schematic authority required |
| RSPI (`rzv_spi.c`) | `spi_b` is different IP; continue using the dedicated RSPI source in `refs/rzv2h_gb_ether/drivers/rspi.c` as secondary evidence |
| SCI-B I2C/SPI modes | `sci_b_uart` proves UART mode only; use integrated FSP SCI-B mode sources and mode-specific target evidence |
| SDHI | No dedicated example in the current EVK corpus |

For a future `firmware:audit`, list these gaps in “What was not checked.” Do
not fill them by silently substituting a different IP block or core.
