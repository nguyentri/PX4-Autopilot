# Connection is supplied by the guarded shell loader using GDB_PORT.
# Halt a running RZ/V2H CR8 core briefly, capture PC + GIC SPI targeting,
# then resume it with J-Link "go" and detach.  Used to confirm a peer image
# is actually running after load and that MHU SPIs were retargeted locally.
#
# GIC ICDIPTR byte = 0x12C11800 + INTID.
#   0x12C11800 INTID0   local-CPU self mask (RAO)
#   0x12C1195B INTID347 MSG4_NS  CR8-1 responder RX
#   0x12C1195C INTID348 MSG9_NS  CR8-0 initiator  RX
#   0x12C11967 INTID359 RSP4_NS  CR8-0 initiator  TX
#   0x12C11968 INTID360 RSP9_NS  CR8-1 responder TX
set pagination off
monitor halt
printf "RUN_PC=%#x CPSR=%#x\n", $pc, $cpsr
bt
printf "SELF_MASK:\n"
x/1bx 0x12C11800
printf "ICDIPTR 347/348/359/360:\n"
x/1bx 0x12C1195B
x/1bx 0x12C1195C
x/1bx 0x12C11967
x/1bx 0x12C11968
monitor go
detach
