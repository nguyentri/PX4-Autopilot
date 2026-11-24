# Phase 8 audit: connectivity (CANFD, Ethernet, USB device), RA8P1 CM85

Tag: CON. This is a static audit only: nothing was built, configured, flashed or run on hardware.

## 1. Scope, core, baseline

- Core: CM85 (`evk-ra8p1`). RA8E1 (`fpb-ra8e1`) is checked for blast radius only.
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Path prefixes:
  - A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`
  - E = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1`
  - F = `.../fpb-ra8e1`
  - R = `refs/ra8p1/ek_ra8p1`. FSP samples are `R/can_fd/can_fd_ek_ra8p1_ep/e2studio`, `R/ethernet/ethernet_ek_ra8p1_ep/e2studio` and `R/usb_pcdc/usb_pcdc_ek_ra8p1_ep/e2studio`; below they are shortened to `<can_fd>`, `<ethernet>` and `<usb_pcdc>`.
- Modules:
  - A/ra_canfd.c (660 lines)
  - A/ra_ether.c (1571), A/ra_ether_rmac.c, A/ra_ether_phy.c, A/ra_ether_phy_{gpy111,dp83620,ics1894,ksz8041,ksz8091rnb}.c
  - A/ra_usbdev.c (1889) + A/ra8_usbdev.h
  - Board glue: E/src/ra8p1_canfd.c, ra8p1_ether.c, ra8p1_usb.c
  - Configs: E/configs/{canfd,ether,usb-pcdc}/defconfig
- ELF symbol layer: none of the three configs was built (user declined builds). The only clean builds are `adc-b` and `adc-b-hwtrigger`, which do not touch these drivers.

### Answers to the key questions

| Question | Answer |
|---|---|
| Does Ethernet use RMAC/ESWM or ETHERC/EDMAC? | ra_ether.c drives the **layer-3 switch (COMA/GWCA/ETHA/RMAC)**, the right IP. Kconfig help and the dependency still describe ETHERC/EDMAC (CON-17). |
| Does the PHY part and address match the EK? | Part GPY111 at address 0 matches `<ethernet>/ra_cfg/.../board_ethernet_phy.h:26-28` and configuration.xml:584-601. But the driver uses **port 0 and RMII**, while the EK wires **port 1 and RGMII** (CON-05). The PHY init layer is never reached (CON-06). |
| Is CM85 descriptor cache maintenance correct? | No. There is no clean/invalidate anywhere. The descriptors sit in an orphan `.dtcm_noinit` section, which lands in cacheable SRAM. DCACHE=y (CON-07). |
| Which USB controller? | **USBFS** (MSTP_USBFS, RA_ELC_USBFS_INT 0x09A). This matches the EK usb_pcdc sample (module 0, USB_SPEED_FS, P407 VBUS). The clock is wrong (CON-08). |

## 2. Trace matrix (CM85)

| Layer | Anchor | Status | FSP reference |
|---|---|---|---|
| Kconfig CANFD | A/Kconfig:1763-1767 (clock choice gated on nonexistent `RA_CAN`) | broken | `<can_fd>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:52-53 |
| Clock CANFD | A/hardware/ra8p1/ra_clock.c:326-331 `#if CONFIG_RA_CAN` | dead | same |
| CANFD driver | A/ra_canfd.c:162-660 | source-audited, FAIL | `<can_fd>`/ra/fsp/src/r_canfd/r_canfd.c |
| CANFD board | E/src/ra8p1_canfd.c (`/dev/can1`), E/src/ra8p1_bringup.c:349-352 | traced | `<can_fd>`/ra_gen/hal_data.c:7-17, :54, :67-71 |
| CANFD config | E/configs/canfd/defconfig:60, :97-99 | traced | — |
| Kconfig ETH | A/Kconfig:6084-6156, :191, :311 | drift | — |
| Clock ESW | A/hardware/ra8p1/ra_clock.c:406-426 | not set (no RA_ETHSW) | `<ethernet>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:69-70 |
| ETH driver | A/ra_ether.c:213-1571 | source-audited, FAIL | `<ethernet>`/ra/fsp/src/r_layer3_switch/r_layer3_switch.c, r_rmac/r_rmac.c |
| ETH RMAC/PHY | A/ra_ether_rmac.c, ra_ether_phy*.c | unreachable | r_rmac_phy/r_rmac_phy.c |
| ETH board | E/src/ra8p1_ether.c (`ra_ether_initialize(0)`), E/include/board.h:463-476 | mismatch | `<ethernet>`/ra_gen/common_data.c:34-37, :259-270 |
| Kconfig USB | A/Kconfig:4294-4326, ~1809, :2128 | traced | `<usb_pcdc>` bsp_clocks.h:25-44 |
| Clock USB | A/hardware/ra8p1/ra_clock.c:334-347, A/hardware/ra_clock.h:591-592 | wrong frequency | `<usb_pcdc>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:61-62 |
| USB driver | A/ra_usbdev.c:1199-1250 (hwinit), :1664-1760 (init), :305-410 (DMA) | source-audited | `<usb_pcdc>`/ra/fsp/src/r_usb_basic, ra_gen/hal_data.c:3151-3152 |
| USB board | E/src/ra8p1_usb.c (no pin mux), E/src/ra8p1_bringup.c:431-434 | gap | `<usb_pcdc>`/ra_gen/pin_data.c:124-125 |
| PX4 layer | boards/renesas/evk-ra8p1/default.px4board:92 (`UAVCAN=n`), :123; nsh defconfig has no CAN/ETH/USB | N/A | — |
| PX4 bootloader defconfig | boards/renesas/evk-ra8p1/nuttx-config/bootloader/defconfig:45-53, :111-114 (USBDEV+CDCACM, but no RA_USBFS/RA_USBDEV, and no bootloader px4board) | orphan | — |

## 3. Findings (by severity)

### CON-01 Critical (conf high): CANFD global init only touches unit 0, while the canfd config clocks only CANFD1, so boot hangs

- Core: CM85.
- Failure sequence:
  1. canfd defconfig:97-99 enables only CANFD1, so ra_canfd_initialize(1) calls ra_mstp_start(RA_MSTP_CANFD1) (A/ra_canfd.c:543).
  2. Global init then writes CFDGCTR(0) and busy-waits on CFDGSTS(0).GRSTSTS (A/ra_canfd.c:556-563). CANFD0 is still module-stopped, so reads return 0 and the loop spins forever inside board bringup.
  3. The loop has no timeout.
- The driver mixes per-unit and per-channel indexing:
  - RA8P1 has 2 CANFD units with 1 channel each (FSP bsp_feature.h:123-124; units at 0x40380000 and 0x40382000, and R_CANFD_CH_BASE stride 0x2000 at A/hardware/ra8p1/ra_canfd.h:42-43).
  - The driver uses CH_BASE(ch) only for CFDC. Global, RX FIFO (index ch), TX MB (ch*4..+3), TMIEC, TMTCSTS, AFL and GERFL all use unit 0 (A/ra_canfd.c:408, :417, :512-519, :556-610).
  - For ch=1, MB 4-7 lies beyond the unit's 4 TX MBs (core0.h:4666-5279 layout).
- Reference: FSP opens each unit independently through its own p_reg (`<can_fd>`/ra/fsp/src/r_canfd/r_canfd.c:300-460).
- Configs: evk-ra8p1:canfd. RA8E1: no config enables CANFD. The driver includes hardware/ra8p1/ra_canfd.h unconditionally, so selecting it on RA8E1 would give the wrong layout (latent).
- Remediation: derive all register bases from the unit (`priv->base`), and run global init per unit after that unit's MSTP is released. Add timeouts to every mode-wait loop.
- Classification: pre-existing.

### CON-02 Critical (conf medium-high): CANFD global and channel sleep never released, so the mode transitions cannot complete

- Failure sequence:
  - After reset, CANFD is in global sleep (GSLPR=1) and channel sleep (CSLPR=1).
  - The driver only edits the GMDC/CHMDC bits (A/ra_canfd.c:168-174, :236, :553-563, :603-610).
  - The wait for Global Operation at :610 (and the channel-communication wait at :236, `(STS&7)!=0`) cannot succeed while sleep is set, so it spins forever. This applies even on CANFD0.
- Reference: FSP's mode mask covers GSLPR together with GMDC (r_canfd.c:22) and clears CSLPR on the channel (r_canfd.c:1578).
- Configs: evk-ra8p1:canfd. RA8E1: latent.
- Remediation: clear GSLPR before global reset and CSLPR before channel reset, as FSP does.
- Classification: pre-existing.

### CON-03 High (conf high): CANFD bit-timing register field layout wrong, and timing assumes a 40 MHz clock that is never configured

- NCFG is written as `(0<<24)|(3<<16)|(63<<8)|15` (A/ra_canfd.c:212-222). The FSP field layout is NBRP@0, NSJW@10, NTSEG1@17, NTSEG2@25 (core0.h:65390-65396), so the programmed values are garbage: NBRP=15, plus overlapping bits.
- DCFG is written as DBRP<<24|DSJW<<16|DTSEG1<<8|DTSEG2. The FSP layout is DBRP@0, DTSEG1@8, DTSEG2@16, DSJW@24 (core0.h:65503-65509).
- FDCFG is written as FDOE alone (:225-226), which is FD-only mode; it is unclear that this is intended.
- The CANFD clock is never configured: A/hardware/ra8p1/ra_clock.c:326 is gated on `CONFIG_RA_CAN`, which no Kconfig defines. Kconfig:1763-1767 uses the same symbol, so the defconfig `RA_CANFDCLK_SOURCE_PLL1P` is dead.
- The FSP EK uses CANFDCLK = PLL2R/6 = 80 MHz, nominal 500k with brp1/tseg1 119/tseg2 40/sjw 4, data 2M with tseg1 29/tseg2 10 (`<can_fd>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:52-53; ra_gen/hal_data.c:7-17).
- Bitrate is hard-coded and ioctl returns -ENOTTY, so it cannot be changed at runtime.
- Configs: evk-ra8p1:canfd. RA8E1: shared driver. F's ra_clock.c:288 has the same dead `CONFIG_RA_CAN` gate.
- Remediation:
  - Replace `CONFIG_RA_CAN` with `CONFIG_RA_CANFD` in both chip ra_clock.c files and in Kconfig.
  - Compute NCFG/DCFG from the configured CANFDCLK and the requested bitrate, using the FSP shifts.
  - Write the timing registers only in channel reset.
- Classification: pre-existing.

### CON-04 High (conf high): CANFD AFL write-enable wrong; TX completion flag never cleared

- AFL write enable:
  - The driver writes `CFDGAFLECTR=1` (A/ra_canfd.c:584). That sets AFLPN=1 (page 1), not AFLDAE (bit 8).
  - So the rule writes are not enabled and target the wrong page, and no RX acceptance rules exist.
  - FSP sets AFLDAE and page 0 (r_canfd.c:381-391).
- TX ISR:
  - It writes `~(1<<i)` to CFDTMTCSTS (:408-417). That register is read-only status. FSP clears CFDTMSTS[n].TMTRF (r_canfd.c:1382-1409).
  - So the completion stays pending: an IRQ storm, or no can_txdone. It also handles only one MB per IRQ.
- Other gaps:
  - The RX ISR clamps DLC to 8 (:454-456), so FD payloads are truncated.
  - Send copies `dlc` bytes for DLC > 8 (:329-330) instead of can_dlc2bytes.
- Configs: evk-ra8p1:canfd. RA8E1: latent.
- Remediation: set AFLDAE with page 0; clear TMSTS.TMTRF per MB and loop over all pending MBs; use the dlc-to-bytes conversion on both paths.
- Classification: pre-existing.

### CON-05 High (conf high): Ethernet port 0 and RMII hard-coded, while the EK PHY is on port 1, RGMII

- Failure sequence:
  - arm_netinitialize calls `ra_ether_initialize(0)` (E/src/ra8p1_ether.c).
  - `phy_mode = RA_ETHER_PHY_RMII` and `phyaddr = 0` (A/ra_ether.c:1487-1490).
  - The board pins are RGMII1_* (E/include/board.h:463-476: TXD P304-P307, RXD P906-P909, clocks P308/P904).
  - So ETHA0/RMAC0 is configured for RMII while the PHY data lines sit on port 1. No frames can pass.
- MDIO is ET0_MDC/MDIO P415/P414, through RMAC0 MPSM (A/ra_ether.c:1266-1360). That is plausible: FSP also uses MDIO on ch0.
- The MAC is fixed 02:00:00:00:00:01 for every board.
- board_phy_config() / g_phy_config in E/src/ra8p1_ether.c is never consumed.
- Reference: FSP ether/PHY channel 1, RGMII (`<ethernet>`/ra_gen/common_data.c:34-37, :259-270).
- Configs: evk-ra8p1:ether. RA8E1: none. RA_ETHERNET is not gated on ETHSW/RA8P1 (A/Kconfig:6084-6094), so ra_ether.c (which includes ra8p1 headers) would not compile there.
- Remediation:
  - Pass port 1 from board glue.
  - Take phy_mode, phyaddr and the MAC (unique ID or Kconfig) from the board config.
  - Gate RA_ETHERNET on RA_HAVE_ETHSW.
- Classification: pre-existing.

### CON-06 High (conf high): PHY/RMAC layer unreachable, so no PHY reset, autoneg, RGMII delay or link state

- Call graph:
  - ra_rmac_open (A/ra_ether_rmac.c) has no caller.
  - ra_phy_open and ra_phy_start_autoneg are called only from ra_ether_rmac.c:262 and :344.
  - So ra_ether_phy.c and all ra_ether_phy_*.c never execute, including the GPY111 MIICTRL RGMII delay setup (ra_ether_phy_gpy111.c:89-139).
- ra_ifup sets GWCA/ETHA to operation without PHY or link setup. ra_ifdown clears only GWDIE0.
- ra_phy_interrupt writes the status into MMID0 (the disable register, A/ra_ether.c:1104). It masks itself and never calls netdev_carrier_on/off.
- Reference: FSP r_rmac open, then r_rmac_phy open and link-process polling (`<ethernet>`/ra/fsp/src/r_rmac/r_rmac.c, r_rmac_phy/r_rmac_phy.c).
- Configs: evk-ra8p1:ether. RA8E1: n/a.
- Remediation:
  - Call ra_rmac_open (or the PHY open and autoneg) from ifup.
  - Poll the link in a work queue; set the RMAC speed and duplex from the result; set the carrier state.
  - Fix the MMID0 write to an MMIS0 status clear.
- Classification: pre-existing.

### CON-07 High (conf medium-high): Ethernet descriptor chain wiring wrong, no TX doorbell, no cache maintenance

- Descriptor chain:
  - GWDCBAC1 is written as the txdesc data chain (A/ra_ether.c:717-727). It should be the LINKFIX descriptor table indexed by queue.
  - Queue 32 then indexes past the table.
  - Reference: r_layer3_switch.c:1435-1463, :507-576.
- TX: ra_transmit (:823-874) never writes GWTRC (FSP r_layer3_switch.c:780-815), so no TX starts.
- Init: the FWPBFC/DDE/GWARIRM steps are missing (FSP :300-340).
- Cache and placement:
  - Descriptors and buffers are in `.dtcm_noinit` (:224-254). The default linker script E/scripts/evk-ra8p1_non_ospi.ld has no such output section, so they become an orphan in cacheable SRAM.
  - The ether defconfig has DCACHE=y, while FSP runs with DCACHE off (bsp_mcu_family_cfg.h:430).
  - There is no up_clean/invalidate_dcache anywhere.
  - If DTCM were used, GWCA bus-master access to DTCM is unverified.
- RX:
  - When a descriptor is not FSINGLE/FEND, rxbuf stays NULL and is re-armed (:1013), so the next DMA writes to address 0.
  - Multi-descriptor frames are dropped.
- ISR context: ra_data_interrupt runs ra_receive and devif_poll from the ISR (:1060-1075, :1231), with no work-queue deferral (the NuttX net-driver contract).
- Configs: evk-ra8p1:ether. RA8E1: n/a.
- Remediation:
  - Build a LINKFIX table as FSP does, and ring GWTRC per queue.
  - Put descriptors in a non-cacheable MPU region or add clean/invalidate.
  - Defer RX/TX to the work queue.
  - Keep the old buffer on a non-final descriptor.
- Classification: pre-existing.

### CON-08 High (conf medium-high): USBCLK 200 MHz, not 48 MHz

- The Kconfig RA_USBCLK_SOURCE default resolves to PLL1P, because usb-pcdc defconfig:55 sets RA_CLOCK_PLL1P=y.
- No Kconfig symbol RA_USBCLK_DIV exists, so the header default DIV_5 applies (A/hardware/ra_clock.h:591-592).
- 1000 MHz / 5 = 200 MHz USBCLK (A/hardware/ra8p1/ra_clock.c:334-347). USBFS needs 48 MHz, so enumeration fails.
- The comment at A/ra_usbdev.c:1178-1180 claims "PLL2R (480MHz)/10 = 48MHz". That is what FSP does (`<usb_pcdc>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:61-62), but not what the code programs.
- This is static Kconfig inference; no .config was generated.
- Configs: evk-ra8p1:usb-pcdc. RA8E1: the RA8E1 clock tree differs; no config is affected.
- Remediation: default RA_USBCLK_SOURCE to PLL2R when RA_USBFS, and add a Kconfig divider defaulting to /10. Also, A/hardware/ra_clock.h:94 `DIV_32 (9)` duplicates DIV_10 (CON-19).
- Classification: pre-existing.

### CON-09 Medium (conf high): USB DMA path has no trigger, no cache maintenance and drops odd bytes; it is enabled by default in usb-pcdc

- `dma_cfg.elc_src = -1 /* TODO */` (A/ra_usbdev.c:356). With no USBFS_FIFO_0/1 (0x098/0x099) trigger, the transfer is software-started and not paced by FRDY.
- transfer_count = len/2 (:352), so the last byte of an odd-length packet is lost (CDC-ACM sends odd lengths constantly).
- There is no dcache clean/invalidate with ARMV8M_DCACHE=y.
- It blocks in nxsem_timedwait(1 s) (:400) from paths reachable in the USB ISR (:498-512, :602).
- Configs: usb-pcdc (RA_USBDEV_DMA=y, defconfig:139). RA8E1: latent.
- Remediation: disable RA_USBDEV_DMA in the defconfig until the DMA path has an ELC trigger, a byte tail, cache ops and non-blocking completion.
- Classification: pre-existing.

### CON-10 Medium (conf medium): USB VBUS pin P407 not muxed

- E/src/ra8p1_usb.c only documents P407/P410/P411; no GPIO configuration is done.
- FSP muxes P407 as USB_FS VBUS (`<usb_pcdc>`/ra_gen/pin_data.c:124-125).
- Without VBUS, VBINT/VBSTS (A/ra_usbdev.c:1065-1080) never report attach. The DP/DM pins are dedicated pins.
- ra8p1_usbpullup and ra8p1_usbsuspend are stubs.
- hwinit lacks the BUSWAIT setting (FSP r_usb_basic_cfg.h:115-116).
- Configs: usb-pcdc. RA8E1: n/a.
- Remediation: configure P407 USBFS_VBUS in board init, and set BUSWAIT as FSP does.
- Classification: pre-existing.

### CON-11 Medium (conf high): CAN example opens `/dev/can0`, but the board registers `/dev/can1`

- E/src/ra8p1_canfd.c registers `/dev/can1` for CANFD1.
- canfd defconfig:60 sets EXAMPLES_CAN_DEVPATH="/dev/can0", so the example fails to open.
- The FSP EK sample uses CANFD0 on P311/P312 (`<can_fd>`/ra_gen/pin_data.c:23-27, hal_data.c:67). The NuttX board.h CANFD0 pins match that.
- CANFD1 P908/P909 collide with RGMII1 RXD2/RXD3 (board.h:481-482 vs :463-476). That only matters if ether and canfd are combined.
- Configs: canfd. RA8E1: n/a.
- Remediation: switch the defconfig to CANFD0 (the EK sample), or set DEVPATH to /dev/can1.
- Classification: drift.

### CON-12 Medium (conf high): CANFD has no error, bus-off or error-frame handling

- The error ISR logs and writes 0 to ERFL and GERFL (A/ra_canfd.c:493-519).
- The CTR error-interrupt enables (EWIE/EPIE/BOEIE...) are never set, while FSP enables them (hal_data.c:54).
- There is no bus-off recovery and no CAN_ERRORS error frames, despite CONFIG_CAN_ERRORS.
- rxint/txint only toggle the NVIC; remoterequest returns 0.
- Configs: canfd. RA8E1: latent.
- Remediation: enable the channel error IRQs, map ERFL bits to CAN_ERROR frames, and handle the bus-off recovery mode.
- Classification: pre-existing.

### CON-13 Medium (conf medium): ESW clocks never configured in the ether config

- ESWCLK, ESWPHYCLK and ETHPHYCLK are gated on RA_ESWM, RA_ESWPHY and RA_ETHPHY (A/hardware/ra8p1/ra_clock.c:406-426).
- Those default y only with RA_ETHSW, which the ether defconfig does not set.
- FSP sets ESWCLK = PLL1P/4 and ESWPHYCLK = PLL1P/2 (`<ethernet>`/ra_cfg/fsp_cfg/bsp/bsp_clock_cfg.h:69-70).
- Configs: ether. RA8E1: n/a.
- Remediation: make RA_ETHERNET select RA_ETHSW (or RA_ESWM and RA_ESWPHY).
- Classification: drift.

### CON-14 Low: CMakeLists drift

- A/CMakeLists.txt:123-130 adds only ra_canfd.c and ra_ether.c.
- Make.defs:154-225 also adds rmac, phy, phy_* and usbdev.
- The CMake build of usb-pcdc would miss arm_usbinitialize and usbdev_register.
- RA8E1: same file. Classification: drift.

### CON-15 Low: dead Kconfig selects and defconfig lines

- RA_HAVE_ETHERC_GMII is selected (A/Kconfig:191, :311) but undefined.
- CONFIG_RA_DTCM and CONFIG_RA_ITCM are set in the defconfigs (usb-pcdc:33-34; PX4 bootloader defconfig:84-85) but are undefined.
- CONFIG_RA8P1_USB_CDC_CONSOLE=n uses a non-standard form.
- RA8E1: Kconfig shared, cosmetic. Classification: drift.

### CON-16 Low: Ethernet placeholders and comments

- The MPIC duplex bit is a placeholder (A/ra_ether.c:594-600).
- ra_phy_wait_ready uses a 1 ms timeout while its comment says 10 ms (:632-653).
- ra_ioctl returns -ENOTTY (:1250).
- Classification: pre-existing.

### CON-17 Low: RA_ETHERNET Kconfig help and dependency describe ETHERC/EDMAC

- A/Kconfig:6084-6094 depends on ETHERC_MII || RMII, and the help text says ETHERC/EDMAC. On RA8P1 the IP is ESWM/L3 switch.
- RA8E1: misleading; selecting it there breaks the build (see CON-05).
- Classification: drift.

### CON-18 validation gap: PX4 bootloader defconfig requests USB CDC-ACM with no RA USB device driver

- boards/renesas/evk-ra8p1/nuttx-config/bootloader/defconfig:45-53 and :111-114 enable USBDEV, CDCACM and USBDEV_DMA, but not RA_USBFS or RA_USBDEV.
- No bootloader px4board exists under boards/renesas/evk-ra8p1, so it is unbuilt and orphaned.
- RA8E1: n/a.
- Classification: validation gap.

### CON-19 Low: duplicate USB clock divider macro

- `RA_CLOCKS_USB_CLOCK_DIV_32 (9)` duplicates DIV_10 (A/hardware/ra_clock.h:94).
- RA8E1: shared header. Classification: pre-existing.

## 4. Verified-correct items

- RA8P1 Ethernet IP choice (L3 switch, GWCA/ETHA/RMAC register usage): verified by A/ra_ether.c:308-346, :663-747 against r_layer3_switch.c.
- EK PHY part GPY111 at address 0 and RGMII mode (as data): verified by `<ethernet>` board_ethernet_phy.h:26-28 and configuration.xml:584-601. The Kconfig default GPY111 on RA8P1 is at A/Kconfig:6118-6156.
- Ethernet interrupt events GWDI0 0x2A6, RMPI0 0x2B2 and RMPI1 0x2B3: verified by A/hardware/ra8p1/ra8p1_irq.h:429 and :441-442. FSP additionally uses EAEI0/1 error IRQs, which NuttX lacks.
- USB controller is USBFS (MSTP_USBFS, RA_ELC_USBFS_INT 0x09A), matching the EK sample (FS, module 0): verified by A/ra_usbdev.c:1699 and :1717, A/hardware/ra8p1/ra8p1_irq.h:237, and `<usb_pcdc>`/ra_gen/hal_data.c:3151-3152.
- USBFS base 0x40250000: verified by A/hardware/ra8p1/ra_usbfs.h:35 against FSP core0.h:64798.
- USBCLK source int map (PLL1P=5, PLL2R=10): verified by A/Kconfig:2128 against FSP bsp_clocks.h:25-44.
- CANFD0 board pins P312/P311: verified by E/include/board.h against `<can_fd>`/ra_gen/pin_data.c:23-27.
- USB pipe TYPE/DIR encoding in ra_epconfigure: verified by A/ra_usbdev.c:1270-1310 (TYPE bits 15:14, DIR bit 4).

## 5. Rejected, unsupported and dead code

- Dead code, unreachable:
  - A/ra_ether_rmac.c (ra_rmac_open has no caller).
  - A/ra_ether_phy.c.
  - All five A/ra_ether_phy_*.c.
- PHY parts with no EK user: DP83620, ICS1894, KSZ8041, KSZ8091RNB. KSZ8091RNB is the RA8E1 Kconfig default, but no RA8E1 config enables Ethernet. Only GPY111 has an EK user.
- Dead board code: E/src/ra8p1_ether.c `board_phy_config()` / `g_phy_config` (no caller).
- Dead config:
  - The `RA_CANFDCLK_SOURCE_*` lines (gated on the nonexistent RA_CAN).
  - The RA_DTCM and RA_ITCM lines.
- PX4 layer: N/A. UAVCAN=n (default.px4board:92); no PX4 driver consumes CAN, ETH or USB on evk-ra8p1.
- Not examined: usb_phid; USB HS (board.h:567-582 defines HS pins, but no driver exists).

## 6. Evidence tier and verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_canfd + board + canfd config | E1 | FAIL (CON-01, -02, -03, -04) |
| ra_ether + board + ether config | E1 | FAIL (CON-05, -06, -07) |
| ra_ether_rmac / ra_ether_phy / phy_* | E0 effective (unreachable) | FAIL (dead) |
| ra_usbdev + board + usb-pcdc config | E1 | FAIL (CON-08 clock; CON-09 and CON-10 likely also block enumeration) |

Phase overall: DONE_WITH_CONCERNS. The audit is complete, and all three drivers fail static review.

RA8E1 blast radius: no fpb-ra8e1 defconfig enables CANFD, ETHERNET or USBDEV, so there is no current impact. Shared drivers include ra8p1 hardware headers, so enabling them on RA8E1 would break the build or apply the wrong register layout. F's ra_clock.c:288 has the same dead `CONFIG_RA_CAN` gate.

## 7. Unresolved questions

1. Can the GWCA bus master reach CM85 DTCM? This decides whether `.dtcm_noinit` is a viable descriptor home once a linker section is added.
2. Is FD-only mode (FDCFG.FDOE) intended, or mixed classic/FD?
3. Which CANFD channel does the canfd config intend: CANFD1 (current) or CANFD0 (EK sample)?
4. The USBCLK source is inferred from Kconfig defaults. Confirm with a generated .config when builds are allowed.
5. Is the PX4 bootloader defconfig meant to be built? It has no px4board.
