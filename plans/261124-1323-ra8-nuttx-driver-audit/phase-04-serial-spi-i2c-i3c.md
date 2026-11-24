---
phase: 4
title: "Phase 4: SCI UART, SPI_B, SCI-SPI, IIC, SCI-I2C, I3C"
status: pending
priority: P1
effort: "1.5d"
dependencies: [3]
---

# Phase 4: Serial and bus drivers (CM85)

## Scope
- Modules: `ra_serial.c` (SCI_B UART), `ra_spi.c` (SPI_B), `ra_sci_spi.c`, `ra_i2c.c` (IIC master), `ra_i2c_slave.c`, `ra_sci_i2c.c`, `ra_i3c.c`
- Board glue: `ra8p1_i2c.c`, `ra8p1_sci_i2c.c`, `ra8p1_sci_spi.c`, `ra8p1_spi_loopback.c`, `ra8p1_i3c.c`
- Configs: `nsh`, `gps`, `i2c`, `sci-i2c`, `sci-spi`, `spi-loopback`, `i3c`
- FSP: `r_sci_b_uart` (`sci_uart`), `r_spi_b` (`spi`, the only carrier), `r_sci_b_spi` (`sci_spi`), `r_iic_master` (`iic_master`), `r_sci_b_i2c` (`sci_i2c_master`), `r_i3c` (`i3c_master`; `i3c_slave` for target mode). No `r_iic_slave` module is in the archive; check `ek_ra8p1/iic_slave` before saying so in the report.

## Tasks & Steps
1. Check baud and bit-rate divisor math against the real kernel clock from phase 2, including the bounds and the error at the configured rates.
2. Check mode, word width, bit order, FIFO thresholds and the order in which status flags are cleared. Compare TE/RE and interrupt enable ordering with FSP.
3. I2C: repeated START, NOSTART/NOSTOP, NACK handling, bus recovery and timeouts. SCI-I2C: check the RZ/V2H TDREC/TXI false-NACK pattern; the same SCI_B IP may show it.
4. SPI: CS ownership, the DTC/DMA path vs polled transfers, and exchange versus exchange-with-cache maintenance.
5. I3C: DAA, CCC handling, IBI, and the ownership of the I3C/IIC shared pins.
6. Check `board.h` pins and channels against the EK `pin_data.c`. Map the PX4 `ttyS*` names to SCI channels; the PX4 side moves to phase 11.
7. Check that the NSH RTT console is unaffected when SCI is enabled (port-status note on the full up-buffer).

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-serial-spi-i2c-i3c.md`. Loopback configs do not count as functional evidence.
