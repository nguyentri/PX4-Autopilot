# Connection is supplied by the guarded shell loader using GDB_PORT.
# Halt a running RZ/V2H CR8 core briefly, capture PC + GIC SPI targeting,
# then resume it with J-Link "go" and detach.  Used to confirm a peer image
# is actually running after load and that MHU SPIs were retargeted locally.
#
# GIC ICDIPTR byte = 0x12C11800 + INTID.
#   0x12C11800 INTID0   local-CPU self mask (RAO)
#   0x12C11962 INTID354 MSG28_NS CR8-1 responder RX
#   0x12C11963 INTID355 MSG34_NS CR8-0 initiator  RX
#   0x12C1196A INTID362 RSP15_NS CR8-0 initiator  TX
#   0x12C11970 INTID368 RSP40_NS CR8-1 responder TX
set pagination off
monitor halt
printf "RUN_PC=%#x CPSR=%#x\n", $pc, $cpsr
# Assembly cache-maintenance frames can stall ARM's prologue unwinder.
# Keep automatic verification to bounded PC/GIC reads; capture a backtrace
# separately when diagnosing a fault in an identified running image.
printf "SELF_MASK:\n"
x/1bx 0x12C11800
printf "ICDIPTR 354/355/362/368:\n"
x/1bx 0x12C11962
x/1bx 0x12C11963
x/1bx 0x12C1196A
x/1bx 0x12C11970
monitor go
detach
