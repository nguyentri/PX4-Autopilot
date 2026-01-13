 /****************************************************************************
 * boards/arm/ra8/evk-ra8p1/scripts/evk-ra8p1_non_ospi.ld
 *
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.  The
 * ASF licenses this file to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance with the
 * License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
 * License for the specific language governing permissions and limitations
 * under the License.
 *
 ****************************************************************************/

/* The RA8P1 has 1MB MRAM (non-volatile) at 0x02000000, 2MB total SRAM,
 * plus TCM memories. External 64MB Octo-SPI Flash at 0x90000000 (OSPI0_CS1).
 *
 * RA8P1 Memory Specification (from datasheet):
 * ============================================
 * Total SRAM: 2048KB = 256KB(CM85 TCM) + 128KB(CM33 TCM) + 1664KB(User SRAM)
 *   - CM85 TCM RAM: 256KB (128KB ITCM + 128KB DTCM)
 *   - CM33 TCM RAM: 128KB (64KB ITCM + 64KB DTCM)
 *   - User SRAM: 1664KB @ 0x22000000 - 0x2219FFFF
 *     - CM85 SRAM: 1536KB @ 0x22000000 - 0x2217FFFF (CM85 use)
 *     - Reserved:    32KB @ 0x22180000 - 0x22187FFF (reserved)
 *     - IPC Shared:  64KB @ 0x22188000 - 0x22197FFF (shared CM85/CM33)
 *     - CM33 SRAM:   32KB @ 0x22198000 - 0x2219FFFF (private to CM33)
 *
 * External Flash (EK-RA8P1 Board):
 * ================================
 * EXTERNAL OSPI0_CS1 (64MB) - PX4 application code and modules (XIP)
 * OSPI0_CS1: 64MB Macronix MX25LW51245GXDI00 @ 0x90000000 (not used due to conflicts with other peripherals))
 * OSPI1: Not populated on this board
 *
 * Internal Code MRAM (1MB total):
 * ===================================================
 * Memory Allocation:
 *   - CM85: 0x02000000 - 0x020E7FFF (928KB) - Boot, NuttX kernel, XIP code
 *   - CM33: 0x020E8000 - 0x020FFFFF (96KB)  - CM33 firmware (copied to ITCM)
 *   - Free: None - All 1MB MRAM allocated
 *
 * CM33 Dual-Core Support:
 * ===================================================
 * CM33 cannot execute from MRAM directly. Boot sequence:
 *   1. CM85 boots from MRAM @ 0x02000000, initializes system
 *   2. CM85 copies CM33 firmware from MRAM @ 0x020E8000 to CM33_ITCM @ 0x20100000
 *   3. CM85 releases CM33 reset via SYSC registers
 *   4. CM33 starts executing from its ITCM @ 0x00000000 (CM33 view)
 *
 * Internal Sip-Flash (8MB):
 * ===================================================
 *   -  0x0800_0000 - 0x0807_FFFF: 8MB Sip-Flash (not applicable for the RA8P1 part number in the EK-RA8P1)
 */

/* Include Renesas OFS register definitions */
INCLUDE renesas_ofs_defs.ld

/* Memory regions */
MEMORY
{
  /* Internal Code MRAM - CM85 code (912KB) */
  mram (rx)   : ORIGIN = 0x02000000, LENGTH = 912K

  /* Internal MRAM - CM85 data (8KB) */
  mram_data (rw) : ORIGIN = 0x020E4000, LENGTH = 8K

  /* User SRAM - 1664KB total, partitioned:
   * CM85: 0x22000000-0x2217FFFF (1536KB)
   * Rsv:  0x22180000-0x22187FFF (32KB)
   * IPC:  0x22188000-0x22197FFF (64KB)
   * CM33: 0x22198000-0x2219FFFF (32KB) */
  sram (rwx)   : ORIGIN = 0x22000000, LENGTH = 1536K

  /* Tightly-Coupled Memory - CM85 (local view) */
  itcm (rwx)   : ORIGIN = 0x00000000, LENGTH = 128K
  dtcm (rwx)   : ORIGIN = 0x20000000, LENGTH = 128K

  /* Tightly-Coupled Memory - CM33 (CM85 system view for loading) */
  /* Note: CM33 sees its ITCM at 0x00000000, but CM85 accesses it via system bus */
  cm33_itcm (rwx) : ORIGIN = 0x20100000, LENGTH = 64K   /* CM85 view of CM33 ITCM */
  cm33_dtcm (rwx) : ORIGIN = 0x20110000, LENGTH = 64K   /* CM85 view of CM33 DTCM */

  /* CM33 code in MRAM (96KB) - CM85 copies this to CM33 ITCM */
  cm33_mram (rx) : ORIGIN = 0x020E6000, LENGTH = 96K

  /* CM33 data in MRAM (4KB) */
  cm33_mram_data (rw) : ORIGIN = 0x020FE000, LENGTH = 4K

  /* IPC Shared Memory - 64KB within User SRAM (shared with CM33) */
  ipc_ram (rw) : ORIGIN = 0x22188000, LENGTH = 64K

  /* Renesas OFS Registers - defined in renesas_ofs_defs.ld */
  OPTION_SETTING_OFS0 (r)         : ORIGIN = OPTION_SETTING_OFS0_START, LENGTH = OPTION_SETTING_OFS0_LENGTH
  OPTION_SETTING_OFS1 (r)         : ORIGIN = OPTION_SETTING_OFS1_START, LENGTH = OPTION_SETTING_OFS1_LENGTH
  OPTION_SETTING_OFS2 (r)         : ORIGIN = OPTION_SETTING_OFS2_START, LENGTH = OPTION_SETTING_OFS2_LENGTH
  OPTION_SETTING_OFS3 (r)         : ORIGIN = OPTION_SETTING_OFS3_START, LENGTH = OPTION_SETTING_OFS3_LENGTH
  OPTION_SETTING_OFS0_SEC (r)     : ORIGIN = OPTION_SETTING_OFS0_SEC_START, LENGTH = OPTION_SETTING_OFS0_SEC_LENGTH
  OPTION_SETTING_OFS1_SEC (r)     : ORIGIN = OPTION_SETTING_OFS1_SEC_START, LENGTH = OPTION_SETTING_OFS1_SEC_LENGTH
  OPTION_SETTING_OFS2_SEC (r)     : ORIGIN = OPTION_SETTING_OFS2_SEC_START, LENGTH = OPTION_SETTING_OFS2_SEC_LENGTH
  OPTION_SETTING_OFS3_SEC (r)     : ORIGIN = OPTION_SETTING_OFS3_SEC_START, LENGTH = OPTION_SETTING_OFS3_SEC_LENGTH
  OPTION_SETTING_OFS3_SEL (r)     : ORIGIN = OPTION_SETTING_OFS3_SEL_START, LENGTH = OPTION_SETTING_OFS3_SEL_LENGTH
  OPTION_SETTING_BPS (r)          : ORIGIN = OPTION_SETTING_BPS_START, LENGTH = OPTION_SETTING_BPS_LENGTH
  OPTION_SETTING_BPS_SEC (r)      : ORIGIN = OPTION_SETTING_BPS_SEC_START, LENGTH = OPTION_SETTING_BPS_SEC_LENGTH
  OPTION_SETTING_OTP_FSBLCTRL0 (r): ORIGIN = OPTION_SETTING_OTP_FSBLCTRL0_START, LENGTH = OPTION_SETTING_OTP_FSBLCTRL0_LENGTH
  OPTION_SETTING_OTP_FSBLCTRL1 (r): ORIGIN = OPTION_SETTING_OTP_FSBLCTRL1_START, LENGTH = OPTION_SETTING_OTP_FSBLCTRL1_LENGTH
  OPTION_SETTING_OTP_FSBLCTRL2 (r): ORIGIN = OPTION_SETTING_OTP_FSBLCTRL2_START, LENGTH = OPTION_SETTING_OTP_FSBLCTRL2_LENGTH
  OPTION_SETTING_OTP_SAMR (r)     : ORIGIN = OPTION_SETTING_OTP_SAMR_START, LENGTH = OPTION_SETTING_OTP_SAMR_LENGTH
  OPTION_SETTING_OTP_SACC00 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC00_START, LENGTH = OPTION_SETTING_OTP_SACC00_LENGTH
  OPTION_SETTING_OTP_SACC10 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC10_START, LENGTH = OPTION_SETTING_OTP_SACC10_LENGTH
  OPTION_SETTING_OTP_SACC01 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC01_START, LENGTH = OPTION_SETTING_OTP_SACC01_LENGTH
  OPTION_SETTING_OTP_SACC11 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC11_START, LENGTH = OPTION_SETTING_OTP_SACC11_LENGTH
  OPTION_SETTING_OTP_SACC02 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC02_START, LENGTH = OPTION_SETTING_OTP_SACC02_LENGTH
  OPTION_SETTING_OTP_SACC12 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC12_START, LENGTH = OPTION_SETTING_OTP_SACC12_LENGTH
  OPTION_SETTING_OTP_SACC03 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC03_START, LENGTH = OPTION_SETTING_OTP_SACC03_LENGTH
  OPTION_SETTING_OTP_SACC13 (r)   : ORIGIN = OPTION_SETTING_OTP_SACC13_START, LENGTH = OPTION_SETTING_OTP_SACC13_LENGTH
  OPTION_SETTING_OTP_PBPS_SEC (r) : ORIGIN = OPTION_SETTING_OTP_PBPS_SEC_START, LENGTH = OPTION_SETTING_OTP_PBPS_SEC_LENGTH
  OPTION_SETTING_OTP_PBPS (r)     : ORIGIN = OPTION_SETTING_OTP_PBPS_START, LENGTH = OPTION_SETTING_OTP_PBPS_LENGTH
  OPTION_SETTING_OTP_ZHUK (r)     : ORIGIN = OPTION_SETTING_OTP_ZHUK_START, LENGTH = OPTION_SETTING_OTP_ZHUK_LENGTH
}

OUTPUT_ARCH(arm)
EXTERN(_vectors)
ENTRY(_stext)

/* Export memory region symbols for runtime use */
__itcm_start = ORIGIN(itcm);
__itcm_end   = ORIGIN(itcm) + LENGTH(itcm);
__dtcm_start = ORIGIN(dtcm);
__dtcm_end   = ORIGIN(dtcm) + LENGTH(dtcm);
__sram_start = ORIGIN(sram);
__sram_end   = ORIGIN(sram) + LENGTH(sram);

/* Exported symbols for runtime use */
__ipc_ram_start = ORIGIN(ipc_ram);
__ipc_ram_end   = ORIGIN(ipc_ram) + LENGTH(ipc_ram);
__ipc_ram_size  = LENGTH(ipc_ram);

SECTIONS
{
  /* Vector table must be at start of mram, 512-byte aligned for Cortex-M85 */
  .text : ALIGN(512)
  {
    _stext = ABSOLUTE(.);
    _VECTORS = ABSOLUTE(.);
    KEEP(*(.vectors))
    *(.text .text.*)
    *(.fixup)
    *(.gnu.warning)
    *(.rodata .rodata.*)
    *(.gnu.linkonce.t.*)
    *(.glue_7)
    *(.glue_7t)
    *(.got)
    *(.gcc_except_table)
    *(.gnu.linkonce.r.*)
    _etext = ABSOLUTE(.);
  } > mram

  /* C++ Static constructors/destructors */
  .init_section :
  {
    _sinit = ABSOLUTE(.);
    KEEP(*(.init_array .init_array.*))
    _einit = ABSOLUTE(.);
  } > mram

  /* ARM exception handling */
  .ARM.extab :
  {
    *(.ARM.extab*)
  } > mram

  __exidx_start = ABSOLUTE(.);
  .ARM.exidx :
  {
    *(.ARM.exidx*)
  } > mram
  __exidx_end = ABSOLUTE(.);

  _eronly = ABSOLUTE(.);

  /* Initialized data section - loaded from mram to SRAM */
  .data :
  {
    _sdata = ABSOLUTE(.);
    *(.data .data.*)
    *(.gnu.linkonce.d.*)
    CONSTRUCTORS
    . = ALIGN(4);
    _edata = ABSOLUTE(.);
  } > sram AT > mram

  /* Functions to be executed from RAM for performance */
  .ramfunc ALIGN(4):
  {
    _sramfuncs = ABSOLUTE(.);
    *(.ramfunc .ramfunc.*)
    _eramfuncs = ABSOLUTE(.);
  } > sram AT > mram

  _framfuncs = LOADADDR(.ramfunc);

  /* Uninitialized data section */
  .bss :
  {
    _sbss = ABSOLUTE(.);
    *(.bss .bss.*)
    *(.gnu.linkonce.b.*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = ABSOLUTE(.);
  } > sram

  /* =========================================================
   * CM33 Dual-Core Support Sections
   * CM85 copies these sections to CM33 TCM at boot
   * ========================================================= */

  /* CM33 code - stored in MRAM, copied to CM33 ITCM by CM85 */
  .cm33_text : ALIGN(4)
  {
    _scm33_text = ABSOLUTE(.);
    KEEP(*(.cm33_vectors))      /* CM33 vector table */
    *(.cm33_text .cm33_text.*)  /* CM33 code */
    *(.cm33_rodata .cm33_rodata.*)
    . = ALIGN(4);
    _ecm33_text = ABSOLUTE(.);
  } > cm33_itcm AT > mram

  _fcm33_text = LOADADDR(.cm33_text);  /* Flash location of CM33 code */

  /* CM33 data - stored in MRAM, copied to CM33 DTCM by CM85 */
  .cm33_data : ALIGN(4)
  {
    _scm33_data = ABSOLUTE(.);
    *(.cm33_data .cm33_data.*)
    . = ALIGN(4);
    _ecm33_data = ABSOLUTE(.);
  } > cm33_dtcm AT > mram

  _fcm33_data = LOADADDR(.cm33_data);  /* Flash location of CM33 data */

  /* CM33 BSS - zero-initialized by CM85 */
  .cm33_bss (NOLOAD) : ALIGN(4)
  {
    _scm33_bss = ABSOLUTE(.);
    *(.cm33_bss .cm33_bss.*)
    . = ALIGN(4);
    _ecm33_bss = ABSOLUTE(.);
  } > cm33_dtcm

  /* IPC Shared Memory Region */
  /* This section is NOLOAD because both cores access it directly */
  /* Memory barriers (DMB/DSB) must be used around all accesses */
  .ipc_ram (NOLOAD) : {
      . = ALIGN(4096);    /* 4KB alignment for MPU configuration */
      _sipc_ram = .;

      /* Ring buffers for inter-core messaging */
      *(.ipc_ram .ipc_ram.*)
      *(.ipc_buffer .ipc_buffer.*)

      /* Reserve full 32KB to prevent overlap with CM85 SRAM */
      . = ORIGIN(ipc_ram) + LENGTH(ipc_ram);

      . = ALIGN(4);
      _eipc_ram = .;
  } > ipc_ram

  /* Stabs debugging sections */
  .stab 0 : { *(.stab) }
  .stabstr 0 : { *(.stabstr) }
  .stab.excl 0 : { *(.stab.excl) }
  .stab.exclstr 0 : { *(.stab.exclstr) }
  .stab.index 0 : { *(.stab.index) }
  .stab.indexstr 0 : { *(.stab.indexstr) }
  .comment 0 : { *(.comment) }
  .debug_abbrev 0 : { *(.debug_abbrev) }
  .debug_info 0 : { *(.debug_info) }
  .debug_line 0 : { *(.debug_line) }
  .debug_pubnames 0 : { *(.debug_pubnames) }
  .debug_aranges 0 : { *(.debug_aranges) }
}

/* Include Renesas OFS sections */
INCLUDE renesas_ofs_sections.ld
