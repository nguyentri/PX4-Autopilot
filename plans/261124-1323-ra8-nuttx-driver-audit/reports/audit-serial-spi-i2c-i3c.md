# RA8P1 NuttX audit — Phase 4, CM85, tag BUS (serial / SPI / I2C / I3C)

Date: 2026-11-24. Auditor: static read-only subagent.

## 1. Scope, core, baseline

- Core: CM85 (evk-ra8p1). Shared ra8 arch code also feeds RA8E1 (fpb-ra8e1).
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Path prefixes:
  - A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`
  - E = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1`
  - F = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/fpb-ra8e1`
  - R = `refs/ra8p1/ek_ra8p1/<x>/<x>_ek_ra8p1_ep/e2studio`
- Drivers: ra_serial, ra_spi, ra_sci_spi, ra_i2c, ra_i2c_slave (brief), ra_sci_i2c, ra_i3c.
- Board glue: ra8p1_i2c.c, ra8p1_sci_i2c.c, ra8p1_sci_spi.c, ra8p1_spi_loopback.c, ra8p1_i3c.c.
- Configs: nsh, gps, i2c, sci-i2c, sci-spi, spi-loopback, i3c.
- Build evidence: none of the in-scope configs was built ("not built (user declined builds)"). Only adc-b and adc-b-hwtrigger built clean, and they are out of scope.
- Method: static comparison against the FSP 6.x samples in `refs/ra8p1` (configuration.xml, ra_gen/pin_data.c, hal_data.c, the r_* driver sources) and against `R7KA8P1KF_core0.h`. No hardware, no build. Loopback demos are not counted as functional evidence.

## 2. Trace matrix (CM85)

| Layer | Anchor | Status | FSP sample |
|---|---|---|---|
| SCI UART pins (console SCI0 P602/P603) | E/include/board.h; A/ra_start.c:442-488 | OK; console only | R=sci_uart pin_data.c |
| SCI UART pins (non-console) | A/ra_serial.c (no ra_gpioconfig) | MISSING mux | sci_uart |
| SCI UART baud | A/ra_serial.c:1362-1460 (table + search, SCICLK) | Plausible, matches FSP algorithm shape | r_sci_b_uart.c |
| SCI UART enable | A/ra_serial.c:1698-1707 (TE+RE, unbounded RIST wait) | Minor | r_sci_b_uart.c |
| ttyS mapping | A/ra_serial.c:203-224 (console = ttyS0) | OK | n/a |
| SCI SPI pins P601/602/603 | E/include/board.h; E/src/ra8p1_sci_spi.c | OK pins; conflicts with SCI0 UART in sci-spi config | R=sci_spi |
| SCI SPI bitrate | A/ra_sci_spi.c:591-690, 1545-1580 | WRONG divisor and clock source | r_sci_b_spi.c:474-515, 590 |
| RSPI_B pins | E/include/board.h:125-128 | WRONG macros, never muxed | R=spi pin_data.c |
| RSPI_B clock | A/ra_spi.c:1635-1727 vs 2264-2265 | MISMATCH (BPEN) | r_spi_b.c:545, r_spi_b.h:99-102 |
| RIIC pins | E/include/board.h:302-303, 310-311 | WRONG macros, never muxed | R=iic_master, iic_slave |
| RIIC bitrate | A/ra_i2c.c:403-525 | Approx (ignores tr/tf) | iic_master hal_data.c (CKS4 BRL17 BRH16) |
| RIIC NACK/stop/restart | A/ra_i2c.c:667-721, 1041, 1418, 1795-1815 | BROKEN | r_iic_master.c |
| RIIC board glue | E/src/ra8p1_i2c.c | No I2C2 case (M3 still open) | n/a |
| SCI I2C | A/ra_sci_i2c.c | Non-functional statically | r_sci_b_i2c.c |
| SCI I2C board glue | E/src/ra8p1_sci_i2c.c | H1 fixed (case 2 present) | n/a |
| I3C | A/ra_i3c.c; E/src/ra8p1_i3c.c | Inert (H4 still open), would not compile | r_i3c.c |
| RTT console | all configs SYSLOG_RTT; nsh SERIAL_RTT0 + SEGGER_SYSVIEW | Independent of SCI; channel-sharing note | n/a |

## 3. Findings

### BUS-01 — RIIC, RSPI_B and I3C pins are never multiplexed
- Severity: Critical. Confidence: High. Core: CM85 (shared code).
- Failure sequence:
  1. With RA_I2Cn, RA_SPIn or I3C enabled, the driver brings up the IP block.
  2. The port pins stay GPIO/Hi-Z.
  3. There is no SCL/SDA/SCK on the bus, so every transfer times out or reads idle levels. Address-NACK is also never seen (see BUS-02).
- Impl:
  - There is no `ra_gpioconfig` in A/ra_i2c.c, A/ra_spi.c, A/ra_i3c.c, E/src/ra8p1_i2c.c, E/src/ra8p1_spi_loopback.c or E/src/ra8p1_i3c.c.
  - The GPIO_I2C*/GPIO_SPI0*/GPIO_I3C* macros in E/include/board.h are unused.
  - A/ra_start.c:442-488 `ra_earlyserialinit` muxes only the console SCI.
  - Non-console SCI UARTs are not muxed either (A/ra_serial.c has no gpioconfig).
- Ref: R=iic_master/ra_gen/pin_data.c (p511 sda1, p512 scl1), R=spi/ra_gen/pin_data.c (spi0 P700-702, spi1 P100-102), R=i3c pin_data.c (p400 scl0, p401 sda0); in FSP, `R_IOPORT_Open` applies all of them.
- Affected: RA8P1 i2c, spi-loopback, i3c and gps (UART3, once enabled).
- RA8E1 blast radius: F/src/gy912.c:1276-1305 muxes SPI1 itself, so spi-gy912 is safe. Check whether F i2c-gy912 (RA_I2C0/I2C1) has its own mux; the arch driver does not provide one.
- Remediation: mux pins in board bringup (the ra8p1_*_initialize helpers) from correct board.h macros, after BUS-06 is fixed. Alternatively, add a per-channel pin table to the arch drivers the way ra_sci_i2c already does.
- Classification: Defect, board integration.

### BUS-02 — RIIC interrupt mode reports success on address/data NACK
- Severity: High. Confidence: High. Core: shared.
- Failure sequence:
  1. A slave is absent.
  2. ERI fires, and A/ra_i2c.c:1795-1815 sets `priv->status`.
  3. `ra_i2c_wait_event` (1041) returns only the nxsem_tickwait result.
  4. `priv->status` is never read (it is only written at 975/982/1803).
  5. Transfer returns OK. i2cdetect shows every address and reads return garbage.
- Impl: A/ra_i2c.c:1041, 1795-1815, 975, 982. RXI/TXI/TEI ISRs only post the semaphore.
- Ref: r_iic_master.c error path; NACK → `IIC_MASTER_EVENT_ABORTED` and a STOP is issued.
- Affected: RA8P1 i2c config (I2C_POLLED is unset everywhere).
- RA8E1 blast radius: i2c-gy912 (RA_I2C0, RA_I2C1), with the same false-positive behaviour.
- Remediation: in ERI, latch NACKF/ALF/TMOF into `priv->status`. In wait_event, return -ENXIO/-EIO when status reports an error, issue a STOP and clear the flags.
- Classification: Defect, driver.

### BUS-03 — RIIC timeout loops wrap and report success on timeout
- Severity: Medium. Confidence: High. Core: shared.
- Failure sequence:
  1. `while (cond && timeout--)` on uint32 leaves timeout at UINT32_MAX after expiry.
  2. In `ra_i2c_start` (667-679), the `timeout == 0` check never fires, so it sets ST on a busy bus.
  3. `ra_i2c_stop` (702-721) returns `(timeout>0)?OK:-ETIMEDOUT`, which is OK on timeout.
- Ref: r_iic_master.c uses a bounded `timeout_count` with an explicit error.
- Affected: RA8P1 i2c. RA8E1 blast radius: i2c-gy912.
- Remediation: `while (cond) { if (timeout-- == 0) return -ETIMEDOUT; }`.
- Classification: Defect.

### BUS-04 — RIIC: no repeated START, no I2C_M_NOSTART, weak bus recovery, empty init
- Severity: Medium. Confidence: High. Core: shared.
- Failure sequence:
  1. A write-then-read is sent as STOP+START (STOP after each msg unless NOSTOP, A/ra_i2c.c:1418). Devices that need Sr (many sensors with register pointers) can lose the pointer.
  2. With NOSTOP, the next start waits on BBSY and then (BUS-03) sets ST on a busy bus. RS is only used on the 10-bit path.
  3. `I2C_M_NOSTART` is ignored.
  4. `ra_i2c_reset` (1463-1487) only toggles ICE: no 9-clock SCL clock-out and no IICRST reinit.
  5. `ra_i2c_init` (1508-1511) is an empty stub; the ICCR1/ICFER macros at 1497-1506 are unused.
- Ref: r_iic_master.c restart (`ICCR2.RS`) and the `R_IIC_MASTER_Abort` / reset sequence.
- Affected: RA8P1 i2c. RA8E1 blast radius: i2c-gy912 (GY-912 sensors use write+read).
- Remediation: when the next msg has no NOSTOP/STOP, issue RS after TEND; honour NOSTART; implement a clock-out bus reset plus IICRST.
- Classification: Defect / gap.

### BUS-05 — SCI simple-I2C driver is non-functional
- Severity: High. Confidence: High (static). Core: shared code; only RA8P1 enables it.
- Failure sequence:
  1. `setfrequency` returns early because init stored the same frequency first (A/ra_sci_i2c.c:555, 493).
  2. Register writes are also gated on `initialized` (516).
  3. As a result CCR2 stays at reset (~14.6 kHz) and IICDL=0. The CESR wait at 522 has no timeout.
  4. Even when written, the clock math is wrong: divisor 64 at cks=0 (401), `64<<(2cks-1)` (405), and inverted MDDR (425). 100 kHz requests give ~207 kHz.
  5. TXI ACK polarity is inverted (891) vs FSP r_sci_b_i2c.c:914.
  6. ICR SDAS/SCLS start/restart/stop sequencing (01/00 output-select states) is missing (562/598/612/626) vs FSP 62, 812, 926, 984, 1005, 1010, 1318, 1345, 1370-1385.
  7. Repeated START is broken (1194/1199/862).
  8. CCR0 is written at once with no CESR wait (1177) vs FSP 792-799.
  9. TDREC is never cleared. The RZ/V2H TDREC/TXI fake-NACK pattern is therefore not present, but TX-complete detection is equally unvalidated.
- Ref: R=sci_i2c/ra/fsp/src/r_sci_b_i2c/r_sci_b_i2c.c (lines above).
- Affected: RA8P1 sci-i2c. RA8E1 blast radius: none (no F config enables SCI I2C), but the shared source is present.
- Remediation:
  - Port the FSP state machine: start = ICR SDAS/SCLS 01 → 00 then STI; restart = RSTAREQ; stop = SDAS 01 → 11 after STPF.
  - ACK when ICR.IICACKR==0.
  - Compute the bitrate with the FSP formula and write it unconditionally in init.
  - Bound all CESR waits.
- Classification: Defect, driver rewrite-class.

### BUS-06 — board.h RIIC / I3C / RSPI pin macros point to wrong pins
- Severity: Medium (latent while BUS-01 holds; becomes High once mux is added). Confidence: High.
- Impl, E/include/board.h:
  - 302-303 I2C0 uses SCL0_B_1/SDA0_B_1 = P408/P407; the comments say P400/P401. FSP iic_slave uses P410/P409 (SCL0_A_2/SDA0_A_2).
  - 310-311 I2C1 SDA = SDA1_B_1 (P204). It should be P511 (SDA1_A_2); SCL P512 is correct.
  - 304-305 I3C SDA = GPIO_SDA0_B_1 (P407, IIC function). It should be P401 I3C_SDA0. The pinmap lacks an I3C_SDA0 macro.
  - 125-128 SPI0:
    - RSPCKA_B_1 is P610, not P601.
    - GPIO_MOSI0_B_2 is undefined in A/hardware/ra8p1/ra_pinmap.h.
    - SSLB0_A_1 is P103, not P604.
    - P601-P604 on Pmod2 are the SPI1 (RSPCKB/MISOB/MOSIB/SSLB0) function per board.csv.
- `GPIO_SCI0_I2C_SDA/SCL` are undefined, so E/src/ra8p1_sci_i2c.c:160-161 fails to compile with RA_SCI0_I2C.
- Pinmap naming is inconsistent: "MISO0_B_1" = P602 is SPI1 MISOB.
- Ref: R=iic_master, iic_slave, i3c, spi ra_gen/pin_data.c; E board.csv.
- Affected: RA8P1 only (board.h). RA8E1: none (own board.h). The pinmap is ra8p1-specific.
- Remediation: re-derive the macros from FSP pin_data.c / board.csv; add the I3C_SDA0 and SCI0 I2C macros; rename the pinmap SPI1 entries.
- Classification: Defect, board data.

### BUS-07 — RSPI_B baud computed from SPICLK while SPCR.BPEN=1 selects PCLK
- Severity: Medium-High. Confidence: Medium-High.
- Failure sequence:
  1. Init sets `SPCR.BPEN` (A/ra_spi.c:2264-2265).
  2. Per FSP, `SPI_B_CLOCK_SOURCE_SCISPICLK=0, PCLK=1` and `spcr |= clock_source << BPEN_Pos` (r_spi_b.h:99-102, r_spi_b.c:545), so BPEN=1 means PCLK.
  3. `ra_spi_setfrequency` (1635-1727) uses `RA_PCLK_SPICLK` (PLL1Q 333 MHz /4 per A/hardware/ra8p1/ra_clock.h:580/952, or PLL1P per the spi-loopback defconfig).
  4. The actual SCK = PCLK/(2(SPBR+1)·2^BRDV) differs from the request by the clock ratio.
- The FSP sample's spbr=62 → 992063 Hz implies 125 MHz, i.e. PCLKA.
- Ref: R=spi/ra/fsp/src/r_spi_b/r_spi_b.c:545 and the bitrate calc.
- Affected: RA8P1 spi-loopback. Loopback hides the wrong rate.
- RA8E1 blast radius: spi-gy912, spi-loopback and spi-masterslave share A/ra_spi.c. The rate is wrong by the RA8E1 SPICLK/PCLKA ratio (A/hardware/ra8e1/ra_clock.h:495/532, PLL1P/4). This may be why the GY-912 SPI works only at some rates; verify.
- Remediation: either clear BPEN and keep SPICLK, or keep BPEN and compute from the PCLK used by FSP (`BSP_FEATURE_SPI_CLK` → PCLKA). Pick one per FSP and record it in a comment.
- Classification: Defect, clocking.

### BUS-08 — SCI simple-SPI bitrate divisor 4x low and wrong clock source
- Severity: Medium. Confidence: High.
- Failure sequence:
  1. Port divisor (A/ra_sci_spi.c:629-645) is 1 for n=0 without BGDM, and `2*2^(2n-1)` otherwise.
  2. FSP uses `2^(2(cks+1)-bgdm)` (r_sci_b_spi.c:503), so the port divisor is 4x too small. A 1 MHz request yields ~4 MHz SCK.
  3. The port always computes from PCLKA (`use_scispiclk=false`, 723/1545/1561) but never sets CCR3.BPEN, so the hardware clocks from SCISPICLK (FSP enum 0 = SCISPICLK, r_sci_b_spi.h:42-43, r_sci_b_spi.c:590).
  4. `actual_frequency` (1580) reports the wrong value.
- FSP sample: cks=1, brr=149, SCISPICLK 120 MHz → 50 kHz.
- Affected: RA8P1 sci-spi. RA8E1: none (no SCI SPI config).
- Remediation: use the FSP formula; pick a source and set CCR3.BPEN consistently.
- Classification: Defect.

### BUS-09 — sci-spi config: SCI0 used as UART console and as simple SPI on the same pins
- Severity: Medium. Confidence: High.
- Impl: E/configs/sci-spi/defconfig sets RA_SCI0_UART, the SCI0 serial console and RA_SCI0_SPI. Kconfig help (A/Kconfig:3825-3831) says these "cannot be used simultaneously", but there is no `depends on !RA_SCI0_UART`.
- P602/P603 are both RXD0/TXD0 and SPI MISO/MOSI.
- Affected: RA8P1 sci-spi. RA8E1: none.
- Remediation: drop the SCI0 UART (console is RTT) or move SCI SPI; add Kconfig exclusion `depends on !RA_SCIn_UART && !RA_SCIn_I2C`.
- Classification: Config defect.

### BUS-10 — gps config never enables the SCI3 UART
- Severity: Medium. Confidence: High.
- Impl: E/configs/gps/defconfig:104-113:
  - `RA_SCI3_RXDMA/TXDMA` depend on `RA_SCI3_UART && RA_DMAC` (A/Kconfig:2973-2976), but `RA_SCI3_UART` is absent.
  - `RA_UART3_GPS` has no Kconfig definition.
  - `UART3_RX/TX_BUFFER_SIZE` are not NuttX symbols; the real ones are `UART3_RXBUFSIZE/TXBUFSIZE` (drivers/serial/Kconfig-uart:275/282).
  - olddefconfig drops all of them, so there is no GPS ttyS.
  - SCI0 lines are duplicated.
- Affected: RA8P1 gps. RA8E1: none.
- Remediation: add `CONFIG_RA_SCI3_UART=y`, the real buffer symbols and the pin mux (BUS-01); remove the dead symbols.
- Classification: Config defect.

### BUS-11 — I3C driver inert and would not compile if enabled (H4 confirmed)
- Severity: High (feature absent). Confidence: High.
- Impl:
  - `CONFIG_RA_I3C0` has no Kconfig definition, so A/ra_i3c.c returns -ENODEV (612/651/682).
  - `RA_MSTP_I3C0` (171) and the `RA_ELC_I3C0_*` names (173-178) do not exist, so enabling it fails to compile.
  - Protocol vs FSP r_i3c.c:253-273:
    - init writes PRTS=1 (516) instead of the RSTCTL sequence with PRTS=0.
    - STDBR/EXTBR are 0.
    - No DAT, ENTDAA, CCC or IBI.
    - Fake command word; RX reads NTDTBP0.
  - E/src/ra8p1_i3c.c:52, 68-124 is demo glue only.
- Affected: RA8P1 i3c. RA8E1: none.
- Remediation: rewrite against r_i3c.c (reset, bitrate, DAT/DCT, ENTDAA, CCC queue, IBI), or remove the config until it can be done.
- Classification: Stub presented as driver.

### BUS-12 — RIIC board glue lacks an I2C2 case (M3 confirmed)
- Severity: Low. Confidence: High.
- Impl: E/src/ra8p1_i2c.c has only `case 0/1`, so `default: Invalid bus` while bringup carries an I2C2 branch. Comments claim I2C1 is on P205/P206, which disagrees with board.h and FSP.
- Affected: RA8P1 only.
- Remediation: add case 2 or drop the bringup branch; fix the comments.
- Classification: Defect, minor.

### BUS-13 — minor items
- RIIC bitrate (A/ra_i2c.c:403-505): `fIIC/(BRH+BRL+2)` ignores tr/tf and the noise filter. 100 kHz gives ~88-97 kHz vs FSP CKS4 BRL17 BRH16 = 97.8 kHz. Low. RA8E1: same.
- `ra_i2c_start` writes MST|TRS before ST (681). Normally this needs ICMR1.MTWP. Low, likely harmless.
- A/ra_start.c:465-466: a stray `*/` under the SCI4_SERIAL_CONSOLE branch is a compile error if SCI4 is the console. Low. Shared: RA8E1 too if it uses an SCI4 console (it uses SCI2, so latent).
- A/ra_serial.c:1704: unbounded wait on CESR.RIST. FSP also polls; Low.
- `ra_spi_select` is weak (A/ra_spi.c:2571) and RA8P1 has no override. There is no CS assertion unless SSL hardware CS is used (ssl_select defaults to 0). Low/Medium; affects only off-board devices.
- nsh enables SERIAL_RTT0 + SEGGER_SYSVIEW, which may share RTT channel 0 with the console. Note it; verify the SysView channel number.
- SCI-I2C Kconfig help still says `/dev/i2cn`, while board glue registers `/dev/i2c(3+bus)`. Doc only.

## 4. Verified correct

- Console SCI0 UART pins P602/P603 match the FSP sci_uart sample; the console is muxed early (A/ra_start.c).
- SCI2 simple-I2C pins P802 SCL / P801 SDA match FSP (SW4 note).
- SCI0 simple-SPI pins P601/602/603 match FSP sci_spi.
- H1 fixed: E/src/ra8p1_sci_i2c.c handles bus 2 and registers the device.
- RIIC clock getter returns PCLKB (correct for RA8P1). Reserved ICBRL/ICBRH bits are set (523-525).
- SCI-I2C bus-reset clock-out (10 SCL toggles) and the RXI RDR read are correct.
- SCI UART baud search follows the FSP r_sci_b_uart algorithm (table, then BRR/ABCS search, 1.5% bound). FIFO is reset before the trigger is set. Flags are cleared before TE/RE.
- ttyS mapping: the console SCI becomes ttyS0 (A/ra_serial.c:203-224).
- RTT console (SYSLOG_RTT in every config) is independent of the SCI state, so SCI faults cannot silence the console.
- SPI DMA paths call up_clean_dcache before TX (739/741/1122) and up_invalidate_dcache after RX (1019/1333). Line-alignment of caller buffers was not verified (see §7).

## 5. Rejected paths and dead code

- Rejected: "RIIC uses IICCKCR clock". RA8P1 has only I3CCKCR; the IICCKCR block at A/hardware/ra8p1/ra_clock.c:366 is dead code for RA8P1.
- Rejected (retracted): "SCI-I2C RXI never reads RDR". A grep filter artefact; RDR is read.
- Rejected: TDREC/TXI fake-NACK (RZ/V2H lesson). The port never clears TDREC, so that sequence cannot occur. The driver is broken for other reasons (BUS-05).
- Dead: SCI-I2C polled mode (no config enables it, non-functional); ICCR1/ICFER macros in A/ra_i2c.c:1497-1506; RA_UART3_GPS / UART3_*_BUFFER_SIZE in the gps defconfig; the GPIO_I2C*/SPI0*/I3C* board.h macros (unused).
- Out of scope: SCI10/SCI11 ELC events.

## 6. Evidence tier and verdict per driver

| Driver | Tier | Verdict |
|---|---|---|
| ra_serial (console) | E1 source-audited | Usable; non-console channels unmuxed |
| ra_serial (gps SCI3) | E0 | Not enabled by config |
| ra_spi (RSPI_B) | E1 | Not functional on RA8P1 (no mux, wrong macros); clock mismatch shared with RA8E1 |
| ra_sci_spi | E1 | Wrong SCK rate (4x plus source); config pin conflict |
| ra_i2c (RIIC) | E1 | Not functional on RA8P1 (no mux); NACK blind, timeouts wrap, no Sr (also RA8E1) |
| ra_i2c_slave | E0 | Brief look only; same pin-mux gap; not audited in depth |
| ra_sci_i2c | E1 | Non-functional (clock never programmed, ACK inverted, ICR sequencing missing) |
| ra_i3c | E0 | Inert stub; does not compile if enabled |

No driver reaches E2/E3: there are no builds of the in-scope configs and no board transcript.

## 7. Unresolved questions

1. Which PCLK does RSPI_B use with BPEN=1 on RA8P1: PCLKA (125 MHz implied by the FSP spbr=62 → 992 kHz) or another domain? Needs the HW manual.
2. Does F (RA8E1) i2c-gy912 mux the RIIC pins in board code? If not, BUS-01 applies to RA8E1 too.
3. Do RA8E1 GY-912 SPI rates already compensate for the BPEN mismatch empirically?
4. SEGGER SysView RTT channel in nsh: does it collide with SERIAL_RTT0 / SYSLOG_RTT channel 0?
5. SPI DMA buffer cache-line alignment requirements for callers (32-byte M85 D-cache) were not verified.
6. ra_i2c_slave was not audited in depth.
