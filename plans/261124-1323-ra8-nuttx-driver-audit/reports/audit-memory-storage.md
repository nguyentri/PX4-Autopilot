# Audit: memory and storage (MRAM, OSPI_B, SDRAM, SDHI, linker) — RA8P1 CM85

## 1. Scope, core, baseline

- Core: CM85 (EK-RA8P1 / `evk-ra8p1`). Static audit only; nothing built, run or flashed.
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Prefixes: A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`, E = `.../boards/arm/ra8/evk-ra8p1`, F = `.../fpb-ra8e1`.
- FSP refs: `refs/ra8p1/ek_ra8p1/{mram,ospi_b,sdram,sdhi}/*_ek_ra8p1_ep/e2studio/`.
- Configs: `mram`, `ospi-b`, `sdram`, `sdhi`. ELF layer: not built (user declined builds) for all four.
- RA8E1: F has no defconfig enabling `RA_MRAM`, `RA_OSPI`, `RA_SDRAM`, `RA_SDHI` (grep of `F/configs/*/defconfig`, 0 hits). RA8E1 Kconfig selects `RA_HAVE_OSPI` only (A/Kconfig:48); SDHI/SDRAM are RA8P1-only (Kconfig:203, 277, 323, 397).

## 2. Trace matrix (CM85)

| Driver | Kconfig | Make.defs / CMake | Board glue / bringup | Status | FSP sample |
|---|---|---|---|---|---|
| ra_mram | `RA_MRAM` depends on undefined `ARCH_CHIP_RA8P1` (A/Kconfig:6263-6267) | Make.defs:145; CMake missing; board `ra8p1_mram.c` absent from E/src/CMakeLists.txt | bringup:338 (dead) | never compiled | `mram/` |
| ra_ospi_b | `RA_OSPI` OK | Make.defs:115; **A/CMakeLists.txt missing**; E CMake missing `ra8p1_ospi_b.c`, `ra8p1_ospi_test.c` | E/src/ra8p1_ospi_b.c:63,82 | compiles (Make), wrong CS | `ospi_b/` |
| ra_sdram | `RA_SDRAM` OK | Make + CMake OK; E/src/Makefile:150-151 | bringup:153-166 | compiles, marginal | `sdram/` |
| ra_sdhi | `RA_SDHI`, `RA_SDHI0` OK | Make.defs:52, CMake:54; E/src/Makefile:96, CMake:42 | bringup:363-373 | compiles (DMA off), card init broken | `sdhi/` |
| linker | `RA_FSP_LINKER_STYPE` unset → `evk-ra8p1_non_ospi.ld` (E/scripts/Make.defs:33-39) | n/a | n/a | active script consistent | n/a |

## 3. Findings

### MEM-01 High (high conf): `RA_MRAM` depends on an undefined symbol, so MRAM is never built
- Core CM85. Failure: `depends on ARCH_CHIP_RA8P1` (A/Kconfig:6263-6267) names a symbol defined nowhere (the chip group is `RA8P1_GROUP`, Kconfig:449) → evaluates n → `mram` defconfig's `CONFIG_RA_MRAM=y` dropped at olddefconfig → `ra_mram.c`, `E/src/ra8p1_mram.c` not compiled → bringup MRAM block (ra8p1_bringup.c:338) dead → `mram` config ships without the feature it is named for.
- Ref: FSP `mram/` sample uses `r_mram` unconditionally.
- Configs: `mram`. RA8E1: none (symbol gate unrelated to F).
- Remediation: `depends on RA8P1_GROUP` (or `RA_HAVE_MRAM`); add `ra_mram.c` to A/CMakeLists.txt and `ra8p1_mram.c` to E/src/CMakeLists.txt. Fix MEM-02/03 first: enabling as-is exposes them.
- Class: pre-existing.

### MEM-02 High (high conf, latent until MEM-01 fixed): MRAM partition map exceeds the 1 MB device and overlaps the running image
- Failure: `RA_MRAM_CODE_SIZE 0x00200000` and `RA_MRAM_DATA_START 0x021F0000` (A/ra_mram.h:50-60) assume 2 MB; the device has 1 MB (FSP `bsp_mcu_device_pn_cfg.h:8` `BSP_ROM_SIZE_BYTES 1048576`; linker `mram LENGTH = 1M`, E/scripts/evk-ra8p1_non_ospi.ld:64-79). `/dev/mtdblock1` (LittleFS `/mnt/params`) lies outside MRAM → bus fault or silent no-op; code partition at 0x02000000 covers the executing image → erase/program bricks the image.
- Ref: FSP tests only the last 4 KB at 0x020FF000 (`mram_ep.h:22`).
- RA8E1: header shared under ra8 but RA8E1 has no MRAM driver config; none.
- Remediation: derive sizes from 1 MB; put data partition at the top (e.g. 0x020F0000 / 64 KB) and reserve it in the linker script with an ASSERT.
- Class: pre-existing.

### MEM-03 Medium (medium conf, latent): MRAM driver sequence diverges from FSP `r_mram`
- MRCPC0/key 0x8600 vs FSP MRCPC1/0x6800; self-entry to P/E via MENTRYR; MRPSC never set; no RAM-resident programming routine (execute-in-place while programming); only PRGBSYC polled; 32-bit accesses to 8/16-bit registers; MRCFREQ written without key; PFB enabled unconditionally; erase emulation commented "8KB" (drift); no cache maintenance/no mutex; reset does not wait MRDY; board glue writes without read-modify-write.
- Ref: `mram/.../ra/fsp/src/r_mram/r_mram.c`. RA8E1: none. Remediation: port the FSP sequence verbatim (RAM function, keys, status polling). Class: pre-existing.

### MEM-04 High (high conf): OSPI drives the wrong chip select / unit; EK flash cannot be addressed
- Failure: EK flash MX25LW51245G is on OSPI unit 0 **CS1** at 0x90000000 (FSP hal_data.c:225-226; configuration.xml:1009-1021: P104 CS1, DQS P801; `bsp_mcu_device_pn_cfg.h:12-19` OSPI0_CS0 0x80000000, OSPI0_CS1 0x90000000, OSPI1_CS0 0x70000000, OSPI1_CS1 0x78000000). NuttX board muxes `GPIO_OM_0_CS0_1` (P107) and no DQS (E/src/ra8p1_ospi_b.c:63), calls `ra_ospi_initialize(0)` (:82); driver maps port 1 → R_XSPI1 with `RA_OSPI_B_MMAP_BASE_CS1 0x90000000` (A/ra_ospi_b.c:60, 855, 1564) → unit 0/CS1 unexpressible; flash never selected → JEDEC ID all-FF, every op fails. board.h:600-602 pin comments wrong.
- RA8E1: `ra_ospi_b.c` shared and RA8E1 selects `RA_HAVE_OSPI`, but no F defconfig enables `RA_OSPI` → no current config affected; any future F OSPI config inherits the port/CS model.
- Remediation: separate unit and CS in the API (`ra_ospi_initialize(unit, cs)`), use base table from FSP, mux P104 CS1 + P801 DQS.
- Class: pre-existing.

### MEM-05 High (high conf): memory-mapped read command programmed in the wrong byte and wrong opcode
- Failure: driver writes 1-byte commands into the low byte of CMCFG; FSP shifts 1-byte commands by 8 (`r_ospi_b.c:137`). Read uses 0x03 + 4-byte address (A/ra_ospi_b.c:75, 847) where FSP uses 0x0C + 8 dummy; OPI set differs (FSP 0xEE11, 10 dummy). → XIP/mmap reads return garbage even with MEM-04 fixed.
- RA8E1: shared code, no F config enables it. Remediation: copy FSP command encoding (`<< 8` for 1-byte) and the FSP SPI/OPI command tables. Class: pre-existing.

### MEM-06 Medium (high conf): OSPI functional gaps
- No SPI→OPI switch (no WCR2); autocalibration returns -ENOSYS; WRAPCFG always 0; BMCFGCH MWRSIZE `0x100<<8` overflows its 8-bit field; BMCTL0 grants CH0 only; error/status checks CS0/CH0 only; ISR posts both semaphores on error; no MTD registered; manual command limited to 8 bytes; memory-mapped writes without WREN/status poll; 100 MHz fallback clock (FSP OCTACLK = PLL2Q/1).
- Cache: 0x90000000 is write-through cacheable under the default ARMv8-M map (no MPU programming in ra8) and the driver has no `up_invalidate_dcache` after program/erase → stale mmap reads. Medium.
- RA8E1: shared, no F config. Class: pre-existing. Remediation: per item; add D-cache invalidate of the affected range after command-mode program/erase.

### MEM-07 High (medium conf): SDRAM row address bits A11/A12 never muxed
- Failure: board pin array (E/src/ra8p1_sdram.c:~110-127) lists `BOARD_SDRAM_A0..A12, A15 (BA0, PD00), A16 (BA1, PC15)` but omits `BOARD_SDRAM_A13` (P510) and `A14` (P608). In FSP 32-bit naming P510 = SDRAM_A11_32BIT and P608 = SDRAM_A12_32BIT (sdram sample `bsp_pin_cfg.h:91,105`). Row lines float → rows alias → upper 3/4 of the array unreachable/corrupt. Boot test covers 4096 bytes only, so it passes.
- Note: NuttX "A0"=PA05, "A1"=PA04 are actually DQM1/DQM3; same PSEL_BUS 0x0B (A/hardware/ra8p1/ra_pinmap.h:220,325) so duplicates are harmless.
- RA8E1: board file only; none. Remediation: add P510/P608 with `PFS_PSEL_BUS`; extend the boot test to walk address bits across the full size. Class: pre-existing.

### MEM-08 High (medium conf): SDRAM timings too tight for 125 MHz SDCLK
- Failure: board passes TRAS=5, TRCD=2, TRP=2 commented "IS42S32800J at 100MHz" (E/src/ra8p1_sdram.c:64-69, 93-95). BCLK = SDCLK = 125 MHz (A/Kconfig:1563-1564, FSP `bsp_clock_cfg.h:40` PLL1P/8) → 16 ns < 18 ns tRCD/tRP, 40 ns < 42 ns tRAS → marginal/intermittent corruption, temperature dependent.
- Ref: FSP 125 MHz values TRAS 6, TRCD 3, TRP 3, TWR 2, CL 3, RFC 937, REFW 8 (`sdram/.../bsp_mcu_family_cfg.h:452-509`). TRFC 780 is shorter than 937 (more refresh) → safe.
- RA8E1: none. Remediation: use FSP values. Class: pre-existing (drift from FSP).

### MEM-09 Medium (medium conf): SDRAM pins at default (low) drive strength
- NuttX uses `PFS_PSEL_BUS` only; FSP uses `IOPORT_CFG_DRIVE_HIGH` and `DRIVE_HS_HIGH` for clock PA15 (sdram `pin_data.c:188,217,394`). Signal-integrity risk at 125 MHz. RA8E1: none. Remediation: add high drive (HS-high on SDCLK). Class: pre-existing.

### MEM-10 Low (high conf, latent): SDRAM Kconfig TRFC/TREFW semantics swapped; defconfig timing values dead
- Kconfig `TRFC` default 8 ("cycle time") and `TREFW` default 1170 ("period"); driver puts trefw into REFW (4 bits @12) and trfc into RFC (12 bits). NULL-config path would give REFW=1, RFC=7 (refresh every 8 cycles). Board always passes its own struct, so all defconfig timing symbols are dead. Header fallbacks (TREFW 8, TRFC 780) correct but shadowed.
- Also Low drift: size 32 MB vs EK 64 MB (underuse, safe); INIT_ARFI 7 / PRC 5 vs FSP 10 / 3; `RA_SDRAM_HEAP` has no consumer (no ra_allocateheap).
- RA8E1: shared `ra_sdram.c` but `RA_HAVE_SDRAM` RA8P1-only → none. Remediation: swap Kconfig names/help or the driver fields; delete dead symbols or wire them. Class: drift.

### MEM-11 High (medium-high conf): SDHI sends every short response as R1 type → ACMD41 (R3) fails, SD init fails
- Failure: `ra_sdhi_sendcmd` sets `R_SDHI_SD_CMD_RSPTP_100` for all short responses (A/ra_sdhi.c:1378-1381); its own comment says FSP uses 111 for R3/R4. R3 has no valid CRC/index → controller flags CRCE/CMDE (in `RA_SDHI_INFO2_ERR_INTS`) → ISR sets SDIOWAIT_ERROR → `waitresponse` -EIO → mmcsd ACMD41 loop fails → no `/dev/mmcsd0`. `MMCSD_R3_RESPONSE`/`R4` are distinguishable in `cmd & MMCSD_RESPONSE_MASK`.
- Ref: FSP uses normal mode with C_ACMD (`sdhi/.../r_sdhi.c:1454`).
- RA8E1: `RA_HAVE_SDHI` RA8P1-only → none. Remediation: map R3/R4 → RSPTP_111 (no CRC check). Class: pre-existing.

### MEM-12 High (medium conf): SDHI R2 (CID/CSD) not shifted by 8 bits
- Failure: `ra_sdhi_recvlong` copies RSP76/54/32/10 directly to rlong[0..3] (A/ra_sdhi.c:1628-1653). SDHI strips the CRC byte, so registers hold bits [127:8] right-aligned (FSP CSD union starts at bit 8: `reserved_8:2 [9:8]` … `csd_structure [127:126]`, `reserved_128 [135:128]`, `r_sdhi_private.h:160-233`; FSP reads RSP10..76 raw, r_sdhi.c:1760-1763). NuttX mmcsd expects rlong[0] = bits 127:96 → CSD decode wrong (capacity, block length, TRAN_SPEED).
- RA8E1: none. Remediation: `rlong[0] = (RSP76 << 8) | (RSP54 >> 24)`, … , `rlong[3] = RSP10 << 8`. Clean up the "Wait, FSP says" comment block. Class: pre-existing.

### MEM-13 Medium (high conf, latent build break): SDHI DMA path does not compile when `RA_DMAC` is enabled
- A/ra_sdhi.c:579-580 `#if (defined(CONFIG_RA_SDHI0_USE_DMAC) && priv->channel == 0) || \\` — `->` is invalid in a preprocessor expression and `\\` leaves a stray backslash. Block is inside `#ifdef CONFIG_RA_DMAC` (:471), so `sdhi` (no DMAC) compiles; any config with `RA_DMAC=y` + `RA_SDHI=y` fails. Also the DMA path has no D-cache maintenance while `ARMV8M_DCACHE=y` in `sdhi` defconfig.
- RA8E1: none. Remediation: runtime `if` on `priv->channel` with `IS_ENABLED`-style macros; add clean/invalidate around DMA. Class: pre-existing.

### MEM-14 Medium (high conf, latent): SDHI PM / channel-1 MSTP symbols
- `RA_MSTP_SDHI0`/`RA_MSTP_SDHI1` (A/ra_sdhi.c:1055,1073, under `CONFIG_PM`) are undefined (only `RA_MSTP_SDHI` = MSTPC12 exists, A/ra_mstp.h:223, ra_mstp.c:163) → build break with `CONFIG_PM`. Init always starts MSTPC12 (:1743) → SDHI1 (FSP MSTPC11, `bsp_module_stop.h:306` `1U << (12U - channel)`) never clocked.
- RA8E1: none. Remediation: add per-channel MSTP ids (C12, C11). Class: pre-existing.

### MEM-15 Low (high conf): SDHI clock divider computed from PCLKA; FSP source is PCLKB
- `ra_sdhi_clock` uses `RA_PCLK_PCLKA` (A/ra_sdhi.c:1229; board.h:87 "125MHz - SDHI clock source"); FSP `bsp_feature.h:519` `BSP_FEATURE_SDHI_CLOCK FSP_PRIV_CLOCK_PCLKB` (62.5 MHz in NuttX board.h:88). Actual SDCLK = half the computed value (transfer ~7.8 MHz vs 25 MHz target; ID ~122 kHz). Safe direction, performance only. CLKSEL encoding matches FSP table (r_sdhi.c:78-92).
- RA8E1: none. Remediation: use PCLKB. Class: drift.

### MEM-16 Low (high conf): SDHI interrupt flag clear can lose events
- ISR writes `info & ~mask` back to SD_INFO1/2 (A/ra_sdhi.c:318-319, 374, 399, 424). Bits are write-0-to-clear; a flag that sets between read and write is written 0 → lost. Remediation: write `~bits_to_clear` (FSP style). RA8E1: none. Class: pre-existing.

### MEM-17 Low (high conf): linker / memory map drift and dead scripts
- `memory.yaml`: CM85 flash 512K, RAM 0xE2000, `ospi_flash` 0x80000000/128 MB (CS0, unpopulated; flash is CS1 0x90000000). Active `evk-ra8p1_non_ospi.ld` uses mram 1M, sram 1664K → yaml drift.
- Dead: `evk-ra8p1.ld` (FSP style; OSPI1_CS1 LENGTH duplicated :56-57; `__sdram_from_ospi0_cs1` copy via `ra_start.c:813-817` `ra_mem_init_fsp(1)` runs before `ra_clock()` and before SDRAM/OSPI init → would fault if `RA_FSP_LINKER_STYPE` were set); `cm85/cm85_user_defs.ld` (OSPI1_CS1 at 0xA0000000 vs FSP 0x78000000, FLASH_APP on unpopulated OSPI0_CS0, DATA_FLASH 0x08000000) — selection commented out (E/scripts/Make.defs:25-31).
- Active script has no SDRAM/OSPI region, so SDRAM is used only via raw pointers.
- RA8E1: board scripts only; none. Remediation: regenerate memory.yaml from the active script; delete or fix dead scripts; if FSP STYPE is kept, move `ra_mem_init_fsp(1)` after external memory init. Class: drift.

### MEM-18 validation gap: build-file parity
- A/CMakeLists.txt missing `ra_ospi_b.c`; E/src/CMakeLists.txt missing `ra8p1_mram.c`, `ra8p1_ospi_b.c`, `ra8p1_ospi_test.c` → CMake builds of `ospi-b` link-fail or silently drop. (adc_b_hwtrigger Make/CMake gating mismatch noted, out of scope.)
- RA8E1: A/CMakeLists.txt shared; affects any F CMake config enabling OSPI (none today).

## 4. Verified correct

- SDRAM init sequence (A/ra_sdram.c:279-450) matches FSP `bsp_sdram.c:62-145` step for step; SDCKOCR under PRCR; DMA read-cache invalidation state present.
- SDHI pins (E/src/ra8p1_sdhi.c): CMD PD04, CLK PD05, DAT0-3 PD03/PD02/PD01/P111, CD P503, WP PD06, PSEL 0x15, high drive — match FSP sdhi `pin_data.c` (8 pins) and channel 0, 4-bit, CD+WP (`common_data.c:47-50`).
- SDHI ELC events `RA_ELC_SDHIMMC0_*` 0x0AB-0x0AE (ra8p1_irq.h:252-255).
- OSPI ELC `XSPI_ERR 0x0BB`, `XSPI_CMP 0x0BC`, `XSPI1_ERR 0x0BD` (ra8p1_irq.h:266-268); RA8E1 0x182/0x183 (ra8e1_irq.h:360-361); MSTP OSPI0 B16 / OSPI1 B17 (ra_mstp.c:134-135) = FSP `bsp_module_stop.h:263-264`.
- Active linker: ipc_shmem 0x220E2000/32K inside sram with ASSERT empty (:205); heap end 0x2207FFFF (RAM_SIZE 512K) below IPC → no overlap.
- OSPI test argc check (prior review H3) fixed at source level; test still non-functional due to MEM-04/05.

## 5. Rejected paths / dead code

- Rejected: SDRAM DQM-as-A0/A1 duplicates (same PSEL → harmless); SDRAM TRFC 780 vs 937 (more frequent refresh → safe).
- Dead: `ra8p1_mram.c`, MRAM bringup block; `evk-ra8p1.ld`, `cm85/cm33 *_user_defs.ld`; SDRAM Kconfig timing symbols and `RA_SDRAM_HEAP`; SDHI DMA path (DMAC off in `sdhi`).

## 6. Evidence tier / verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_mram | E1 (never compiled) | FAIL |
| ra_ospi_b | E1 | FAIL |
| ra_sdram | E1 | DONE_WITH_CONCERNS |
| ra_sdhi | E1 | FAIL |
| linker/memory map | E1 | PASS_WITH_LIMITATIONS |

ELF layer for `mram`, `ospi-b`, `sdram`, `sdhi`: not built (user declined builds).

## 7. Unresolved questions

1. EK-RA8P1 schematic: confirm P510/P608 are SDRAM row A11/A12 on this board revision (MEM-07 confidence medium).
2. Exact SDRAM part on the EK (IS42S32800J vs 64 MB part in FSP) — decides final size and timings.
3. Is the MRAM params partition (LittleFS `/mnt/params`) intended to coexist with the code image in the same 1 MB?
4. Target status of `evk-ra8p1.ld` / FSP STYPE path: keep or delete?
