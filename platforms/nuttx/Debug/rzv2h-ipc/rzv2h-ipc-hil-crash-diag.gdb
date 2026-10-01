# Read-only crash diagnosis for a halted RZ/V2H CR8 core.
#
# Non-mutating: halt, capture the live PC/CPSR and backtrace, then decode the
# NuttX exception frame saved in g_current_regs (the register context at the
# faulting instruction) plus the CP15 Data Fault Address/Status registers via
# a J-Link CP15 read.  No writes, no reset, no load.  Detach at the end.
#
# ARMv7-R exception frame indices (arch/arm/include/armv7-r/irq.h):
#   REG_R0..R12 = words 0..12, REG_SP=13, REG_LR=14, REG_PC=15, REG_CPSR=16
set pagination off
target remote :50000
monitor halt
printf "== live PC/CPSR ==\n"
printf "PC=%#x CPSR=%#x\n", $pc, $cpsr
printf "== backtrace ==\n"
bt
printf "== g_current_regs (exception frame) ==\n"
p/x g_current_regs
printf "== faulting frame R0..PC,CPSR ==\n"
x/17xw g_current_regs
printf "== CP15 Data Fault Address Register (DFAR) ==\n"
monitor cp15 6 0 0 0
printf "== CP15 Data Fault Status Register (DFSR) ==\n"
monitor cp15 5 0 0 0
detach
