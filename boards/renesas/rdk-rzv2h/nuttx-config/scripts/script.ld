/****************************************************************************
 * boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld
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
SRAM_CR8_0_START = 0x00000000;
SRAM_CR8_0_LENGTH = 0x10000000;
ITCM_AXI_CR8_0_START = 0x12040000;
ITCM_AXI_CR8_0_LENGTH = 0x20000;
XSPIFLASH_CR8_0_START = 0x20000000;
XSPIFLASH_CR8_0_LENGTH = 0x10000000;
DDR0_CR8_0_START = 0x40000000;
DDR0_CR8_0_LENGTH = 0xC0000000;

CR8_0 = 1;

ITCM_PRV_START          = DEFINED(CR8_0) ? SRAM_CR8_0_START : SRAM_CR8_1_START;
ITCM_PRV_LENGTH         = 0x0001FE00;
DTCM_PRV_START          = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x00020000 : SRAM_CR8_1_START + 0x00020000;
DTCM_PRV_LENGTH         = 0x00020000;
ITCM_PRV_AXI_START      = DEFINED(CR8_0) ? 0x12040000 : 0x12080000;
SRAM_CACHE_PRV_START    = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x08180000 : SRAM_CR8_1_START + 0x081C0000;
SRAM_CACHE_PRV_LENGTH   = DEFINED(CR8_0) ? 0x00020000 : 0x00020000;
SRAM_UNCACHE_PRV_START  = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x081A0000 : SRAM_CR8_1_START + 0x081E0000;
SRAM_UNCACHE_PRV_LENGTH = DEFINED(CR8_0) ? 0x0001FFFC : 0x0001FFFC;
XSPIFLASH_PRV_START     = DEFINED(CR8_0) ? XSPIFLASH_CR8_0_START : XSPIFLASH_CR8_1_START;
XSPIFLASH_PRV_LENGTH    = DEFINED(CR8_0) ? XSPIFLASH_CR8_0_LENGTH : XSPIFLASH_CR8_1_LENGTH;
DDR_CACHE_PRV_START     = DEFINED(CR8_0) ? DDR0_CR8_0_START + 0x00800000 : DDR0_CR8_1_START + 0x01800000;
DDR_CACHE_LENGTH        = DEFINED(CR8_0) ? 0x01000000 : 0x01000000;
DDR_UNCACHE_PRV_START   = DEFINED(CR8_0) ? DDR0_CR8_0_START + 0x01000000 : DDR0_CR8_1_START + 0x02000000;
DDR_UNCACHE_LENGTH      = DEFINED(CR8_0) ? 0x00800000 : 0x00800000;

/* Memory allocation OpenAMP using ddr. */
OPENAMP_RSCTBL_START    = DEFINED(CR8_0) ? DDR0_CR8_0_START + 0x02f00000 : DDR0_CR8_1_START + 0x02f00000;
OPENAMP_RSCTBL_LENGTH   = 0x00001000;
MHU_SHMEM_START         = DEFINED(CR8_0) ? DDR0_CR8_0_START + 0x02f01000 : DDR0_CR8_1_START + 0x02f01000;
MHU_SHMEM_LENGTH        = 0x00001000;
OPENAMP_VRING_START     = DEFINED(CR8_0) ? DDR0_CR8_0_START + 0x03000000 : DDR0_CR8_1_START + 0x03000000;
OPENAMP_VRING_LENGTH    = 0x00F00000;

/* Flash header infomation */
ITCM_HEADER_START  = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x0001FE00 : SRAM_CR8_1_START + 0x0001FE00;
FLASH_HEADER_START = DEFINED(CR8_0) ? XSPIFLASH_CR8_0_START + 0x00200000 : XSPIFLASH_CR8_1_START + 0x01300000;
HEADER_LENGTH      = 0x80;
FLASH_DATA_START   = FLASH_HEADER_START + HEADER_LENGTH;

/* Initialization waiting area */
INIT_WAIT_AREA_START = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x081BFFFC : SRAM_CR8_1_START + 0x081FFFFC;
INIT_WAIT_AREA_OTHER_CORE_START = DEFINED(CR8_0) ? SRAM_CR8_0_START + 0x081FFFFC : SRAM_CR8_1_START + 0x081BFFFC;
INIT_WAIT_AREA_LENGTH = 0x00000004;

/* Dummy area to provide a space between the code area and data area */
DUMMY_START = 0x0001FDF0;
DUMMY_LENGTH = 0x00000008;

MEMORY
{
    ITCM : ORIGIN = ITCM_PRV_START, LENGTH = ITCM_PRV_LENGTH
    DTCM : ORIGIN = DTCM_PRV_START, LENGTH = DTCM_PRV_LENGTH
    SRAM_CACHE : ORIGIN = SRAM_CACHE_PRV_START, LENGTH = SRAM_CACHE_PRV_LENGTH
    SRAM_UNCACHE : ORIGIN = SRAM_UNCACHE_PRV_START, LENGTH = SRAM_UNCACHE_PRV_LENGTH
    XSPI_FLASH : ORIGIN = XSPIFLASH_PRV_START, LENGTH = XSPIFLASH_PRV_LENGTH
    DDR_SDRAM_CACHE : ORIGIN = DDR_CACHE_PRV_START, LENGTH = DDR_CACHE_LENGTH
    DDR_SDRAM_UNCACHE : ORIGIN = DDR_UNCACHE_PRV_START, LENGTH = DDR_UNCACHE_LENGTH

    OPENAMP_RSCTBL(rw): ORIGIN = OPENAMP_RSCTBL_START,LENGTH = OPENAMP_RSCTBL_LENGTH
    MHU_SHMEM(rw)     : ORIGIN = MHU_SHMEM_START,     LENGTH = MHU_SHMEM_LENGTH
    OPENAMP_VRING(rw) : ORIGIN = OPENAMP_VRING_START, LENGTH = OPENAMP_VRING_LENGTH

    HEADER_REGION(r) : ORIGIN = ITCM_HEADER_START, LENGTH = HEADER_LENGTH

    INIT_WAIT_AREA(rw) : ORIGIN = INIT_WAIT_AREA_START, LENGTH = INIT_WAIT_AREA_LENGTH
    INIT_WAIT_AREA_OTHER_CORE(rw) : ORIGIN = INIT_WAIT_AREA_OTHER_CORE_START, LENGTH = INIT_WAIT_AREA_LENGTH

    DUMMY : ORIGIN = DUMMY_START, LENGTH = DUMMY_LENGTH

    /* IPC RAM for CR8-0 <-> CR8-1 <-> M33 communication (non-cacheable) */
    IPC_RAM (rw) : ORIGIN = 0x70000000, LENGTH = 64K
}

PHDRS
{
    itcm_load_ph     PT_LOAD FLAGS(5); /* R+X */
    itcm_data_ph     PT_LOAD FLAGS(6); /* RW */
    dtcm_ph          PT_LOAD FLAGS(6); /* RW */
    sram_ph          PT_LOAD FLAGS(6); /* RW */
    sram_data_ph     PT_LOAD FLAGS(6); /* RW */
    sdram_text_ph    PT_LOAD FLAGS(5); /* R+X */
    sdram_data_ph    PT_LOAD FLAGS(6); /* RW */
    openamp_ph       PT_LOAD FLAGS(6); /* RW */
    wait_ph          PT_LOAD FLAGS(6); /* RW */
    dummy_ph         PT_LOAD FLAGS(6); /* RW */
}

OUTPUT_ARCH(arm)
EXTERN(_vectors)
ENTRY(_VECTORS)

SECTIONS
{
    .itcm_load_section0 0x00000000 :
    {
        _itcm_load_start = .;
        /* vector */
        _fvector_start = .; _VECTORS = .;
        KEEP(*(.vectors))
        _fvector_end = .;

        . = ALIGN(0x100);

        /* BSP code */
        _text_start = .;

        KEEP(*(.int_handler))

        KEEP(*(.init))
        KEEP(*(.fini))

        /* .ctors */
        *crtbegin.o(.ctors)
        *crtbegin?.o(.ctors)
        *(EXCLUDE_FILE(*crtend?.o *crtend.o) .ctors)
        *(SORT(.ctors.*))
        *(.ctors)
        _ctor_end = .;

        /* .dtors */
        *crtbegin.o(.dtors)
        *crtbegin?.o(.dtors)
        *(EXCLUDE_FILE(*crtend?.o *crtend.o) .dtors)
        *(SORT(.dtors.*))
        *(.dtors)
        _dtor_end = .;

        KEEP(*(.warm_start))

        . = ALIGN(0x04);
        *(.got)
        *(.got.plt)

        /* Minimal .eh_frame section to satisfy C runtime references */
        . = ALIGN(0x04);
        __EH_FRAME_BEGIN__ = .;
        KEEP(*(.eh_frame))
        __EH_FRAME_END__ = .;

        /* Project/user objects: prefer NuttX and apps outputs */
        ./nuttx/**/*.obj (.text .text.*)
        ./nuttx/**/*.o    (.text .text.*)
        ./apps/**/*.obj   (.text .text.*)
        ./apps/**/*.o     (.text .text.*)

        _text_end = .;
    } > ITCM : itcm_load_ph
    .loader_dummy_itcm :
    {
        _loader_dummy_itcm_start = .;
        KEEP(*(.loader_dummy_itcm));
        _loader_dummy_itcm_end = .;
    } > DUMMY AT > ITCM : dummy_ph
    .itcm_load_section1 :
    {
        . = ALIGN(0x10);
        /* BSP data */
        _data_start = .;

        *(vtable)
        KEEP(*(.application_vectors))

        _erodata = .;

        . = ALIGN(0x04);
        /* preinit data */
        PROVIDE_HIDDEN (__preinit_array_start = .);
        KEEP(*(.preinit_array))
        PROVIDE_HIDDEN (__preinit_array_end = .);

        . = ALIGN(0x04);
        /* init data */
        PROVIDE_HIDDEN (__init_array_start = .);
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array))
        PROVIDE_HIDDEN (__init_array_end = .);

        . = ALIGN(0x04);
        /* finit data */
        PROVIDE_HIDDEN (__fini_array_start = .);
        KEEP(*(SORT(.fini_array.*)))
        KEEP(*(.fini_array))
        PROVIDE_HIDDEN (__fini_array_end = .);

        KEEP(*(.jcr*))

        . = ALIGN(0x04);


      /* Project/user data placed in ITCM when necessary */
        ./nuttx/**/*.obj (.data .data.*)
        ./nuttx/**/*.o    (.data .data.*)
        ./apps/**/*.obj   (.data .data.*)
        ./apps/**/*.o     (.data .data.*)

        /* Project/user rodata placed in ITCM when necessary */
        ./nuttx/**/*.obj (.rodata .rodata.*)
        ./nuttx/**/*.o    (.rodata .rodata.*)
        ./apps/**/*.obj   (.rodata .rodata.*)
        ./apps/**/*.o     (.rodata .rodata.*)

        . = ALIGN(0x04);

        /* All data end */
        _data_end = .;
        _itcm_load_end = .;
    } > ITCM : itcm_data_ph
    .dtcm_noload_section (NOLOAD) :
    {
        /* heap */
        . = ALIGN(8);
        __HeapBase = .;
        /* Place the STD heap here. */
        KEEP(*(.heap))
        __HeapLimit = .;

        /* system stack */
        . = ALIGN(8);
        __SysStackBase = .;
        /* Place the sys_stack here. */
        KEEP(*(.sys_stack))
        __SysStackLimit = .;

        /* SVC stack */
        . = ALIGN(8);
        __SvcStackBase = .;
        /* Place the svc_stack here. */
        KEEP(*(.svc_stack))
        __SvcStackLimit = .;

        /* IRQ stack */
        . = ALIGN(8);
        __IrqStackBase = .;
        /* Place the irq_stack here. */
        KEEP(*(.irq_stack))
        __IrqStackLimit = .;

        /* FIQ stack */
        . = ALIGN(8);
        __FiqStackBase = .;
        /* Place the fiq_stack here. */
        KEEP(*(.fiq_stack))
        __FiqStackLimit = .;

        /* Undefined stack */
        . = ALIGN(8);
        __UndStackBase = .;
        /* Place the und_stack here. */
        KEEP(*(.und_stack))
        __UndStackLimit = .;

        /* Abort stack */
        . = ALIGN(8);
        __AbtStackBase = .;
        /* Place the abt_stack here. */
        KEEP(*(.abt_stack))
        __AbtStackLimit = .;

        /* Thread stack */
        . = ALIGN(8);
        /* Place the thread stack here. */
        KEEP(*(.stack.*))

        /* BSP BSS */
        . = ALIGN(0x04);
        __bss_start__ = .;
        _bss = .;

        /* Project/user BSS */
        ./nuttx/**/*.obj (.bss .bss.*)
        ./nuttx/**/*.o    (.bss .bss.*)
        ./apps/**/*.obj   (.bss .bss.*)
        ./apps/**/*.o     (.bss .bss.*)

        *(COMMON)
        . = ALIGN(0x04);
        __bss_end__ = .;
        _ebss = .;
        _end = .;
    } > DTCM : dtcm_ph

    /* Separate executable code section in DDR */
    .sdram_text_section :  ALIGN( 0x04 )
    {
        . = ALIGN ( 0x04 ) ;
        _sdram_text_start = .;

        /* Only user project code - exclude critical system code */
        __text_usr_start = .;

         /* NuttX specific objects */
        ./nuttx/**/*.obj (.text .text.*)
        ./nuttx/**/*.o    (.text .text.*)
        ./apps/**/*.obj   (.text .text.*)
        ./apps/**/*.o     (.text .text.*)

        /* Catch-all for any remaining .text sections not explicitly placed in ITCM */
        *(.text .text.* .gnu.linkonce.t.*)

        /* Catch-all for other code sections that might not be in ITCM */
        *(.init)
        *(.fini)
        *(.glue_7)
        *(.glue_7t)
        *(.vfp11_veneer)
        *(.v4_bx)

        . = ALIGN( 0x04 );
        __text_usr_end = .;

        . = ALIGN(0x04);
        _sdram_text_end = .;
    } > DDR_SDRAM_CACHE : sdram_text_ph

    /* Separate data section in DDR */
    .sdram_data_section :  ALIGN( 0x04 )
    {
        . = ALIGN ( 0x04 ) ;
        _sdram_data_start = .;

        /* Only user project data - exclude critical system data */
        __data_usr_start = .;
        ./nuttx/**/*.obj (.data .data.*)
        ./nuttx/**/*.o    (.data .data.*)
        ./apps/**/*.obj   (.data .data.*)
        ./apps/**/*.o     (.data .data.*)

        /* Catch-all for any remaining .data sections not explicitly placed in ITCM */
        *(.data .data.* .gnu.linkonce.d.*)
        . = ALIGN(0x04);

        /* C++ initialized data sections used in PX4 */
        CONSTRUCTORS

        . = ALIGN(0x04);

        __rodata_usr_start = .;

        ./nuttx/**/*.obj (.rodata .rodata.*)
        ./nuttx/**/*.o    (.rodata .rodata.*)
        ./apps/**/*.obj   (.rodata .rodata.*)
        ./apps/**/*.o     (.rodata .rodata.*)

        /* Catch-all for any remaining .rodata sections not explicitly placed in ITCM */
        *(.rodata .rodata.* .gnu.linkonce.r.*)

        /* Catch-all for other data sections */
        *(.sdata .sdata.* .gnu.linkonce.s.*)
        *(.sdata2 .sdata2.* .gnu.linkonce.s2.*)
        *(.got .got.plt)
        *(.tdata .tdata.* .gnu.linkonce.td.*)
        *(.tbss .tbss.* .gnu.linkonce.tb.*)

        /* Catch-all for constructor/destructor tables not in ITCM */
        *(SORT(.ctors.*))
        *(.ctors)
        *(SORT(.dtors.*))
        *(.dtors)

        /* Array initialization sections */
        *(.preinit_array)
        *(SORT(.init_array.*))
        *(.init_array)
        *(SORT(.fini_array.*))
        *(.fini_array)
        *(.jcr*)

        . = ALIGN(0x04);
        /* All data end */
        __data_usr_end = .;

        . = ALIGN(0x04);
        _sdram_data_end = .;
    } > DDR_SDRAM_CACHE : sdram_data_ph
    .sram_load_section0 : ALIGN( 0x04 )
    {
        /* User code moved to DDR - keep section for compatibility */
        _sram_load_start = .;
        . = ALIGN( 0x04 );
        __text_usr_end = .;
    } > SRAM_CACHE
    .loader_dummy_sram :
    {
        _loader_dummy_sram_start = .;
        KEEP(*(.loader_dummy_sram));
        _loader_dummy_sram_end = .;
    } > DUMMY AT > SRAM_CACHE : dummy_ph
    .sram_load_section1 : ALIGN( 0x04 )
    {
        /* user data moved to DDR - keep section for compatibility */
        . = ALIGN(0x04);
        _sram_load_end = .;
    } > SRAM_CACHE : sram_ph
    .sram_noload_section (NOLOAD) :
    {
        /* user BSS moved to DDR - keep section for compatibility */
        . = ALIGN(0x10);
        _cbuffer_start = .;
        KEEP(*(.cache_buffer*))
        _cbuffer_end = .;
    } > SRAM_CACHE
    .sram_uncache_section (NOLOAD) :
    {
        . = ALIGN(0x10);
        _ncbuffer_start = .;
        KEEP(*(.noncache_buffer*))
        _ncbuffer_end = .;
    } > SRAM_UNCACHE
    .wait_data  :
    {
        KEEP(*(.wait_data))
    } > INIT_WAIT_AREA : wait_ph
    .wait_data_other_core  :
    {
        KEEP(*(.wait_data_other_core))
    } > INIT_WAIT_AREA_OTHER_CORE : wait_ph

    .noinit (NOLOAD) :
    {
        *(.noinit)
        *(.noinit.*)
    } > SRAM_UNCACHE : sram_data_ph

    .sdram_noload_section (NOLOAD) :
    {
        . = ALIGN ( 0x10 ) ;
        PROVIDE(_cbuffer_sdram_start = .);

        /* Only user PX4 BSS - exclude critical system BSS */
        . = ALIGN( 0x04 );
        __bss_usr_start__ = .;

        /* Only PX4 specific objects */
        /* ./px4.dir/**/*.obj (.bss .bss.*) */

        /* Catch-all for any remaining .bss sections not explicitly placed in DTCM */
        *(.bss .bss.* .gnu.linkonce.b.*)

        /* Catch-all for other uninitialized data sections */
        *(.sbss .sbss.* .gnu.linkonce.sb.*)
        *(.sbss2 .sbss2.* .gnu.linkonce.sb2.*)
        *(COMMON)

        . = ALIGN(0x04);
        __bss_usr_end__ = .;
        _end_usr = .;

        . = ALIGN(0x10);
        /* Use separate symbol for DDR cache buffer to avoid conflict with SRAM symbols */
        _cbuffer_ddr_start = .;
        KEEP(*(.cache_buffer*))
        _cbuffer_ddr_end = .;
        PROVIDE(_cbuffer_sdram_end = .);
    } > DDR_SDRAM_CACHE
    .sdram_uncache_section (NOLOAD) :
    {
        . = ALIGN ( 0x10 ) ;
        PROVIDE(_ncbuffer_sdram_start = .);
        *(.mutex_flags);
        PROVIDE(_ncbuffer_sdram_end = .);
    } > DDR_SDRAM_UNCACHE

    __tz_MHU_SHMEM = ABSOLUTE ( MHU_SHMEM_START ) ;
    . = __tz_MHU_SHMEM;
    .resource_table (NOLOAD) :
    {
        PROVIDE(__rsctbl_start = .);
        *  (  .resource_table  )
        PROVIDE(__rsctbl_end = .);
    } > OPENAMP_RSCTBL : openamp_ph
    __tz_MHU_SHMEM = ABSOLUTE ( MHU_SHMEM_START ) ;
    . = __tz_MHU_SHMEM;
    .mhu_shmem (NOLOAD) :
    {
        PROVIDE(__mhu_shmem_start = .);
        . += MHU_SHMEM_LENGTH;
        PROVIDE(__mhu_shmem_end = .);
    } > MHU_SHMEM : openamp_ph
    __tz_OPENAMP_VRING = ABSOLUTE ( OPENAMP_VRING_START ) ;
    . = __tz_OPENAMP_VRING;
    .vring (NOLOAD) :
    {
        PROVIDE(__vring_start = .);
        . += OPENAMP_VRING_LENGTH;
        PROVIDE(__vring_end = .);
    } > OPENAMP_VRING : openamp_ph

    /* IPC RAM Section for CR8-0 <-> CR8-1 communication (non-cacheable) */
    .ipc_ram (NOLOAD) :
    {
        . = ALIGN(0x40);
        PROVIDE(__ipc_ram_start = .);
        PROVIDE(__ipc_cr8_cr8_base = .);
        *(.ipc_ram)
        *(.ipc_ram.*)
        . = ALIGN(0x40);
        PROVIDE(__ipc_ram_end = .);
    } > IPC_RAM

    _itcm_load_addr = FLASH_DATA_START;
    _itcm_load_size = _itcm_load_end - _itcm_load_start;
    _itcm_load_start = _itcm_load_start + ITCM_PRV_AXI_START;
    _sram_load_addr = FLASH_DATA_START + _itcm_load_size;
    _sram_load_size = _sram_load_end - _sram_load_start;
    _sdram_load_addr = FLASH_DATA_START + _itcm_load_size + _sram_load_size;
    _sdram_load_size = (_sdram_text_end - _sdram_text_start) + (_sdram_data_end - _sdram_data_start);
    _sdram_load_start = _sdram_text_start;
    .header : {
        _header_start = .;
        LONG(_itcm_load_addr)
        LONG(_itcm_load_start)
        LONG(_itcm_load_size)
        LONG(0xFFFFFFFF - _itcm_load_addr)
        LONG(0xFFFFFFFF - _itcm_load_start)
        LONG(0xFFFFFFFF - _itcm_load_size)
        LONG(_sram_load_addr)
        LONG(_sram_load_start)
        LONG(_sram_load_size)
        LONG(0xFFFFFFFF - _sram_load_addr)
        LONG(0xFFFFFFFF - _sram_load_start)
        LONG(0xFFFFFFFF - _sram_load_size)
        LONG(_sdram_load_addr)
        LONG(_sdram_load_start)
        LONG(_sdram_load_size)
        LONG(0xFFFFFFFF - _sdram_load_addr)
        LONG(0xFFFFFFFF - _sdram_load_start)
        LONG(0xFFFFFFFF - _sdram_load_size)
        LONG(INIT_WAIT_AREA_START)
        LONG(0x1234FEDC)
        _header_end = .;
    } > HEADER_REGION
    /* Header reserved area (signature, padding) */
    _header_padding_size = HEADER_LENGTH - ((_header_end + 4)- _header_start);
    .header_reserved : {
        LONG(0x562F5A52)
        FILL(0x00)
        . += _header_padding_size;
    } > HEADER_REGION

    /* Discard ARM exception tables that cause relocation overflow with split memory layout */
    /DISCARD/ :
    {
        *(.ARM.exidx*)
        *(.ARM.extab*)
        *(.gnu.linkonce.armexidx.*)
        *(.gnu.linkonce.armextab.*)
    }
}

/* Provide required symbols for libgcc even though we don't use exception handling */
__exidx_start = 0;
__exidx_end = 0;

/* NuttX specific symbol definitions (using existing computed symbols) */
PROVIDE( _sinit = __init_array_start );
PROVIDE( _einit = __init_array_end );
/* Flash area containing data to copy to RAM starts at _itcm_load_addr (FLASH_DATA_START) */
PROVIDE( _sdata = _itcm_load_addr );
/* End of flash load area: end of SDRAM load region */
PROVIDE( _edata = _sdram_load_addr + _sdram_load_size );
/* Flash readonly/text area: use FLASH_HEADER_START as the base for readonly data */
PROVIDE( _stext = FLASH_HEADER_START );
/* End of readonly/text area: same end as the overall flash load region */
PROVIDE( _etext = _sdram_load_addr + _sdram_load_size );
PROVIDE( _eronly = _etext );
/* End of zero-initialized RAM (BSS end) */
PROVIDE( _sbss = __bss_start__ );
PROVIDE( _ebss = __bss_end__ );
