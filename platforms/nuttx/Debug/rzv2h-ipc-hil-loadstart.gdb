# Volatile RAM load + core-local start for one RZ/V2H CR8 core.
#
# Mutating: writes ELF PT_LOAD segments to core-local RAM, sets PC to the
# image entry (__start), resumes with J-Link "go", and detaches leaving the
# core running.  No monitor reset (avoids unmeasured SoC-wide reset scope
# while a peer image is already resident).
#
# Usage:
#   arm-none-eabi-gdb -q -batch <elf> -x rzv2h-ipc-hil-loadstart.gdb
set pagination off
target remote :50000
monitor halt
printf "PRE_LOAD_PC=%#x CPSR=%#x\n", $pc, $cpsr
load
set $pc = &__start
printf "ENTRY=%#x SET_PC=%#x\n", &__start, $pc
monitor go
detach
