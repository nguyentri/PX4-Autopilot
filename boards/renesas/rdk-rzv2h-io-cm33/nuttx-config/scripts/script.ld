/****************************************************************************
 * boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cm33_nuttx.ld
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

/* RZV2H CM33 Memory Map:
 *
 * ATCM (Instruction TCM): 0x00000000 - 0x0001FFFF (128KB)
 *   - Used for vectors and critical code
 *   - Fastest memory for code execution
 *
 * BTCM (Data TCM): 0x20000000 - 0x2001FFFF (128KB)
 *   - Used for stack and critical data
 *   - Fastest memory for data access
 *
 * System RAM: 0x22000000 - 0x2207FFFF (512KB)
 *   - Main application RAM
 *   - Used for .data, .bss, heap
 *
 * Peripherals: 0x10000000 - 0x1FFFFFFF
 * External Memory: 0x40000000 onwards (if configured)
 */

MEMORY
{
    /* ATCM - 128KB at 0x00000000 (Instruction TCM) */
    atcm (rx)  : ORIGIN = 0x00000000, LENGTH = 128K

    /* BTCM - 128KB at 0x20000000 (Data TCM) */
    btcm (rwx) : ORIGIN = 0x20000000, LENGTH = 128K

    /* System RAM - 512KB at 0x22000000 */
    sram (rwx) : ORIGIN = 0x22000000, LENGTH = 512K

    /* IPC RAM - 64KB at 0x70000000 (Shared with CR8) */
    IPC_RAM (rw) : ORIGIN = 0x70000000, LENGTH = 64K
}

OUTPUT_ARCH(arm)
ENTRY(__start)

SECTIONS
{
    /* Exception vectors must be at 0x00000000 for CM33 */
    .vectors :
    {
        _vectors = ABSOLUTE(.);
        *(.vectors)
        . = ALIGN(4);
    } > atcm

    /* Code sections in ATCM for best performance */
    .text :
    {
        _stext = ABSOLUTE(.);
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
        . = ALIGN(4);
        _etext = ABSOLUTE(.);
    } > atcm

    /* C++ exception handling */
    .ARM.extab :
    {
        *(.ARM.extab*)
    } > atcm

    .ARM.exidx :
    {
        __exidx_start = ABSOLUTE(.);
        *(.ARM.exidx*)
        __exidx_end = ABSOLUTE(.);
    } > atcm

    /* Init/fini sections */
    .init_section :
    {
        _sinit = ABSOLUTE(.);
        KEEP(*(.init_array .init_array.*))
        _einit = ABSOLUTE(.);
    } > atcm

    /* Stack in BTCM for best performance */
    .stack (NOLOAD) :
    {
        . = ALIGN(8);
        _sstack = ABSOLUTE(.);
        . = . + 16384;  /* 16KB stack */
        . = ALIGN(8);
        _estack = ABSOLUTE(.);
    } > btcm

    /* Initialized data - stored in flash, copied to RAM at startup */
    _eronly = LOADADDR(.data);

    .data :
    {
        _sdata = ABSOLUTE(.);
        *(.data .data.*)
        *(.gnu.linkonce.d.*)
        CONSTRUCTORS
        . = ALIGN(4);
        _edata = ABSOLUTE(.);
    } > sram AT > atcm

    /* Uninitialized data (BSS) */
    .bss (NOLOAD) :
    {
        _sbss = ABSOLUTE(.);
        *(.bss .bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = ABSOLUTE(.);
    } > sram

    /* Heap */
    .heap (NOLOAD) :
    {
        . = ALIGN(8);
        _sheap = ABSOLUTE(.);
        . = . + (ORIGIN(sram) + LENGTH(sram) - .);
        _eheap = ABSOLUTE(.);
    } > sram

    /* IPC RAM Section */
    .ipc_ram (NOLOAD) :
    {
        . = ALIGN(0x10);
        PROVIDE(__ipc_ram_start = .);
        *(.ipc_ram)
        *(.ipc_ram.*)
        . = ALIGN(0x10);
        PROVIDE(__ipc_ram_end = .);
    } > IPC_RAM

    /* DMA Buffers (Non-cacheable) */
    .dma_buffers (NOLOAD) :
    {
        . = ALIGN(0x10);
        *(.dma_buffers)
        *(.dma_buffers.*)
    } > IPC_RAM

    /* Stabs debugging sections */
    .stab 0 : { *(.stab) }
    .stabstr 0 : { *(.stabstr) }
    .stab.excl 0 : { *(.stab.excl) }
    .stab.exclstr 0 : { *(.stab.exclstr) }
    .stab.index 0 : { *(.stab.index) }
    .stab.indexstr 0 : { *(.stab.indexstr) }
    .comment 0 : { *(.comment) }

    /* DWARF debug sections */
    .debug_abbrev 0 : { *(.debug_abbrev) }
    .debug_info 0 : { *(.debug_info) }
    .debug_line 0 : { *(.debug_line) }
    .debug_pubnames 0 : { *(.debug_pubnames) }
    .debug_aranges 0 : { *(.debug_aranges) }
}
