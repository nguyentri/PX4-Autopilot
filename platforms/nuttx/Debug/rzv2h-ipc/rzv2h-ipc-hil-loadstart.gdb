# Volatile RAM load + core-local start for one RZ/V2H CR8 core.
#
# Mutating: writes ELF PT_LOAD segments to core-local RAM, sets PC to the
# image entry (__start), resumes with J-Link "go", and detaches leaving the
# core running.  No monitor reset (avoids unmeasured SoC-wide reset scope
# while a peer image is already resident).
#
# CPSR is set to the ARMv7-R reset value (SVC, A/I/F masked).  The halted
# image's CPSR usually has IRQs unmasked, and its GTM/HRT interrupt may still
# be pending at the shared GIC, so keeping it lets that IRQ fire on the very
# first __start instruction, before the new image owns a vector or a handler.
#
# Usage:
#   arm-none-eabi-gdb -q -batch <elf> -x rzv2h-ipc-hil-loadstart.gdb
set pagination off
target remote :50000
monitor halt
printf "PRE_LOAD_PC=%#x CPSR=%#x\n", $pc, $cpsr
load
set $pc = &__start
set $cpsr = 0x1d3
printf "ENTRY=%#x SET_PC=%#x CPSR=%#x\n", &__start, $pc, $cpsr
monitor go
detach
