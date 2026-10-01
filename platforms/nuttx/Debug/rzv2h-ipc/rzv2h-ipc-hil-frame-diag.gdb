# Read-only: decode a NuttX ARMv7-R exception frame at a known address and
# resolve the faulting PC/LR to source.  No writes, no reset.  Detach at end.
#
# Frame layout (18 words): R0..R12, SP(13), LR(14), PC(15), CPSR(16), + spare.
set pagination off
target remote :50000
monitor halt
printf "== exception frame @ 0x40837430 ==\n"
x/18xw 0x40837430
printf "== R12(sp)=word13 LR=word14 PC=word15 CPSR=word16 ==\n"
set $frame = 0x40837430
printf "FAULT_PC = %#x\n", *(unsigned int *)($frame + 15*4)
printf "FAULT_LR = %#x\n", *(unsigned int *)($frame + 14*4)
printf "FAULT_SP = %#x\n", *(unsigned int *)($frame + 13*4)
printf "FAULT_CPSR = %#x\n", *(unsigned int *)($frame + 16*4)
printf "== symbol @ fault PC ==\n"
info symbol *(unsigned int *)($frame + 15*4)
printf "== symbol @ fault LR ==\n"
info symbol *(unsigned int *)($frame + 14*4)
printf "== disassemble around fault PC ==\n"
disassemble *(unsigned int *)($frame + 15*4)-16, *(unsigned int *)($frame + 15*4)+8
detach
