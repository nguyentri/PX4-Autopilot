/****************************************************************************
 * boards/renesas/evk-ra8p1-io-cm33/nuttx-config/scripts/script.ld
 *
 * RA8P1 CM33 IO Processor - Linker Script
 *
 * Memory Layout (CM33 system view):
 * - MRAM:    0x02080000, 96KB  - Non-volatile code storage (XIP or copied to ITCM by CM85)
 * - ITCM:    0x20100000, 64KB  - Critical code: ISRs, DShot, GPT (fast execution)
 * - DTCM:    0x20110000, 64KB  - Data, stacks (fast access)
 * - SRAM:    0x22000000, 32KB  - Dynamic heap (NuttX malloc)
 * - IPC_RAM: 0x22008000, 32KB  - Shared memory (non-cacheable)
 *
 * Boot Sequence:
 * 1. CM85 boots from MRAM @ 0x02000000
 * 2. CM85 copies CM33 firmware from MRAM @ 0x02080000 to CM33_ITCM @ 0x20100000
 * 3. CM85 releases CM33 reset
 * 4. CM33 executes from ITCM (vectors + critical code) and MRAM (general code)
 *
 ****************************************************************************/

MEMORY
{
    /* CM33 Code MRAM - 96KB allocated from 1MB MRAM */
    /* CM85 uses 0x02000000-0x0207FFFF (512KB), CM33 uses 0x02080000-0x02097FFF (96KB) */
    mram (rx)   : ORIGIN = 0x02080000, LENGTH = 96K    /* General code, rodata (XIP) */

    /* Tightly-Coupled Memory for CM33 (system view addresses) */
    itcm (rx)   : ORIGIN = 0x20100000, LENGTH = 64K    /* Critical code: ISRs, DShot, GPT */
    dtcm (rwx)  : ORIGIN = 0x20110000, LENGTH = 64K    /* Data, stacks */

    /* User SRAM (partitioned for CM33 use) */
    sram (rwx)  : ORIGIN = 0x22000000, LENGTH = 32K    /* Dynamic heap */

    /* IPC Shared Memory Region (non-cacheable, 4KB aligned) */
    /* This region is shared between CM85 and CM33 for inter-core communication */
    ipc_ram (rw) : ORIGIN = 0x22008000, LENGTH = 32K
}

/* Entry point */
OUTPUT_ARCH(arm)
ENTRY(__start)

/* Exported symbols for runtime use */
__ipc_ram_start = ORIGIN(ipc_ram);
__ipc_ram_end   = ORIGIN(ipc_ram) + LENGTH(ipc_ram);
__ipc_ram_size  = LENGTH(ipc_ram);

/* Stack sizes */
_stacksize = 4096;        /* Main stack size */
_irqstacksize = 2048;     /* IRQ stack size */

SECTIONS
{
    /* Vector table at start of MRAM (copied to ITCM by CM85 bootloader) */
    .vectors : {
        . = ALIGN(512);  /* ARMv8-M vector table alignment */
        _svectors = .;
        KEEP(*(.vectors))
        _evectors = .;
    } > mram

    /* Critical code in ITCM for fast execution */
    /* ISRs, DShot DMA, GPT timers, other performance-critical functions */
    .itcmfunc : {
        . = ALIGN(8);
        _sitcmfuncs = ABSOLUTE(.);

        /* Interrupt handlers and low-level drivers */
        *(.text.arm_doirq)
        *(.text.exception_common)
        *(.text.hrt_tim_isr)
        *(.text.up_block_task)
        *(.text.up_unblock_task)

        /* GPT timer functions (PWM/DShot critical path) */
        *(.text.*gpt*)
        *(.text.*GPT*)
        *(.text.*timer*)
        *(.text.*Timer*)

        /* DShot DMA functions */
        *(.text.*dshot*)
        *(.text.*dma*)
        *(.text.*DMA*)
        *(.text.*DMAC*)

        /* IO timer functions */
        *(.text.*io_timer*)
        *(.text.*IOTimer*)

        /* RC input processing */
        *(.text.*sbus*)
        *(.text.*dsm*)
        *(.text.*crsf*)

        /* Scheduler critical functions */
        *(.text.nxsched_process_timer)
        *(.text.sched_lock)
        *(.text.sched_unlock)

        /* Semaphore fast paths */
        *(.text.nxsem_post)
        *(.text.nxsem_trywait)

        /* Memory operations */
        *(.text.memcpy)
        *(.text.memset)

        . = ALIGN(8);
        _eitcmfuncs = ABSOLUTE(.);
    } > itcm AT > mram

    _fitcmfuncs = LOADADDR(.itcmfunc);

    /* General code sections in MRAM */
    .text : {
        . = ALIGN(4);
        _stext = .;
        *(.text .text.*)
        *(.fixup)
        *(.gnu.warning)
        *(.glue_7)
        *(.glue_7t)
        *(.got)
        *(.gcc_except_table)
        *(.gnu.linkonce.t.*)
        . = ALIGN(4);
        _etext = .;
    } > mram

    /* Read-only data in MRAM */
    .rodata : {
        . = ALIGN(4);
        _srodata = .;
        *(.rodata .rodata.*)
        *(.gnu.linkonce.r.*)
        . = ALIGN(4);
        _erodata = .;
    } > mram

    /* Initialization array (C++ constructors, etc.) */
    .init_section : {
        . = ALIGN(4);
        _sinit = .;
        KEEP(*(.init_array .init_array.*))
        . = ALIGN(4);
        _einit = .;
    } > mram

    /* ARM exception handling tables */
    .ARM.extab : {
        . = ALIGN(4);
        *(.ARM.extab* .gnu.linkonce.armextab.*)
    } > mram

    .ARM.exidx : {
        . = ALIGN(4);
        __exidx_start = .;
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
        __exidx_end = .;
    } > mram

    /* End of read-only sections in MRAM */
    _eronly = .;

    /* Initialized data (copied from MRAM to DTCM at startup) */
    .data : {
        . = ALIGN(4);
        _sdata = .;
        *(.data .data.*)
        *(.gnu.linkonce.d.*)
        CONSTRUCTORS
        . = ALIGN(4);
        _edata = .;
    } > dtcm AT > mram

    /* Store load address for .data initialization */
    _eronly_data = LOADADDR(.data);

    /* Functions to be executed from SRAM for performance (non-ITCM critical code) */
    .ramfunc ALIGN(4):
    {
        _sramfuncs = ABSOLUTE(.);
        *(.ramfunc .ramfunc.*)
        _eramfuncs = ABSOLUTE(.);
    } > sram AT > mram

    _framfuncs = LOADADDR(.ramfunc);

    /* Uninitialized data (BSS) */
    .bss : {
        . = ALIGN(4);
        _sbss = .;
        *(.bss .bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > dtcm

    /* No-init section (preserved across reset) */
    .noinit (NOLOAD) : {
        . = ALIGN(4);
        _snoinit = .;
        *(.noinit .noinit.*)
        . = ALIGN(4);
        _enoinit = .;
    } > dtcm

    /* Main stack at top of DTCM */
    .stack (NOLOAD) : {
        . = ALIGN(8);
        _sstack = .;
        . = . + _stacksize;
        _estack = .;
    } > dtcm

    /* IRQ stack */
    .irqstack (NOLOAD) : {
        . = ALIGN(8);
        _sirqstack = .;
        . = . + _irqstacksize;
        _eirqstack = .;
    } > dtcm

    /* Heap in SRAM (for malloc, etc.) */
    /* Note: NuttX uses _sheap and _eheap as heap boundaries.
     * The heap grows dynamically - we just mark the available region.
     * Don't pre-allocate the entire SRAM space in the linker script. */
    .heap (NOLOAD) : {
        . = ALIGN(4);
        _sheap = .;
        /* Heap extends to end of SRAM, calculated at runtime by NuttX */
    } > sram

    /* Mark end of SRAM for heap calculation */
    _eheap = ORIGIN(sram) + LENGTH(sram);

    /* DMA buffers in SRAM (non-cacheable region for DShot) */
    .dma_buffers (NOLOAD) : {
        . = ALIGN(32);  /* Cache line alignment */
        _sdma = .;
        *(.dma_buffer .dma_buffer.*)
        . = ALIGN(32);
        _edma = .;
    } > sram

    /* IPC Shared Memory Region */
    /* This section is NOLOAD because both cores access it directly */
    /* Memory barriers (DMB/DSB) must be used around all accesses */
    .ipc_ram (NOLOAD) : {
        . = ALIGN(4096);    /* 4KB alignment for MPU configuration */
        _sipc_ram = .;

        /* Ring buffers for inter-core messaging */
        *(.ipc_ram .ipc_ram.*)
        *(.ipc_buffer .ipc_buffer.*)

        . = ALIGN(4);
        _eipc_ram = .;
    } > ipc_ram

    /* Debug sections */
    .stab          0 : { *(.stab) }
    .stabstr       0 : { *(.stabstr) }
    .stab.excl     0 : { *(.stab.excl) }
    .stabstr.excl  0 : { *(.stabstr.excl) }
    .stab.index    0 : { *(.stab.index) }
    .stabstr.index 0 : { *(.stabstr.index) }
    .comment       0 : { *(.comment) }

    /* DWARF debug sections */
    .debug_abbrev  0 : { *(.debug_abbrev) }
    .debug_info    0 : { *(.debug_info) }
    .debug_line    0 : { *(.debug_line) }
    .debug_pubnames 0 : { *(.debug_pubnames) }
    .debug_aranges 0 : { *(.debug_aranges) }
    .debug_frame   0 : { *(.debug_frame) }
    .debug_str     0 : { *(.debug_str) }
    .debug_loc     0 : { *(.debug_loc) }
    .debug_macinfo 0 : { *(.debug_macinfo) }
    .debug_ranges  0 : { *(.debug_ranges) }

    /* Discard unwanted sections */
    /DISCARD/ : {
        *(.note.GNU-stack)
        *(.gnu_debuglink)
        *(.gnu.lto_*)
    }
}

/* Provide symbols for runtime checks */
PROVIDE(_stext = _stext);
PROVIDE(_etext = _etext);
PROVIDE(_sdata = _sdata);
PROVIDE(_edata = _edata);
PROVIDE(_sbss = _sbss);
PROVIDE(_ebss = _ebss);
PROVIDE(_sheap = _sheap);
PROVIDE(_eheap = _eheap);
