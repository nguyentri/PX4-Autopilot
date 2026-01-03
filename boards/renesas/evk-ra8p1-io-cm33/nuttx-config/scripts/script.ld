MEMORY
{
    itcm  (rx)  : ORIGIN = 0x20100000, LENGTH = 64K
    dtcm  (rwx) : ORIGIN = 0x20110000, LENGTH = 64K
    sram  (rwx) : ORIGIN = 0x22000000, LENGTH = 896K
    ipc_ram (rw) : ORIGIN = 0x220E0000, LENGTH = 64K
}

OUTPUT_ARCH(arm)
ENTRY(__start)

SECTIONS
{
	.text : {
		_stext = .;
		*(.vectors)
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
		_etext = .;
	} > itcm

	.init_section : {
		_sinit = .;
		*(.init_array .init_array.*)
		_einit = .;
	} > itcm

	.ARM.extab : {
		*(.ARM.extab*)
	} > itcm

	.ARM.exidx : {
		__exidx_start = .;
		*(.ARM.exidx*)
		__exidx_end = .;
	} > itcm

	.data : {
		_sdata = .;
		*(.data .data.*)
		*(.gnu.linkonce.d.*)
		CONSTRUCTORS
		_edata = .;
	} > dtcm AT > itcm

	.bss : {
		_sbss = .;
		*(.bss .bss.*)
		*(.gnu.linkonce.b.*)
		*(COMMON)
		_ebss = .;
	} > dtcm

	.ipc_ram (NOLOAD) : {
		. = ALIGN(4);
		_sipc_ram = .;
		*(.ipc_ram)
		. = ALIGN(4);
		_eipc_ram = .;
	} > ipc_ram

	/* Stabs debugging sections. */
	.stab 0 : { *(.stab) }
	.stabstr 0 : { *(.stabstr) }
	.stab.excl 0 : { *(.stab.excl) }
	.stabstr.excl 0 : { *(.stabstr.excl) }
	.stab.index 0 : { *(.stab.index) }
	.stabstr.index 0 : { *(.stabstr.index) }
	.comment 0 : { *(.comment) }
	.debug_abbrev 0 : { *(.debug_abbrev) }
	.debug_info 0 : { *(.debug_info) }
	.debug_line 0 : { *(.debug_line) }
	.debug_pubnames 0 : { *(.debug_pubnames) }
	.debug_aranges 0 : { *(.debug_aranges) }
}
