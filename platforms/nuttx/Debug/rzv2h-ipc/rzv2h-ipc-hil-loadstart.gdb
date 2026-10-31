# Connection is supplied by the guarded shell loader using GDB_PORT.
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
#   JLINK_SERIAL=<probe-sn> ./rzv2h-load-one-core.sh <cr8_0|cr8_1> <elf>
set pagination off
monitor halt
printf "PRE_LOAD_PC=%#x CPSR=%#x\n", $pc, $cpsr
# SCTLR to the Cortex-R8 reset value (MPU, caches, branch prediction off).
# The halted image's MPU only maps its own windows: after a different image
# ran on this core (e.g. the CR8-1 image on CR8-0) the debugger's writes to
# this core's SDRAM window are blocked and __start prefetch-aborts forever.
# __start invalidates the caches and programs SCTLR/MPU itself.
monitor cp15 1, 0, 0, 0 = 0x00C50078
load
set $pc = &__start
set $cpsr = 0x1d3
printf "ENTRY=%#x SET_PC=%#x CPSR=%#x\n", &__start, $pc, $cpsr
monitor go
detach
