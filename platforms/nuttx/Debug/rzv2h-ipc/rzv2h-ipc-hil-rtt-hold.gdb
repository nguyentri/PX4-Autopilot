# Resume a loaded RZ/V2H CR8 core and hold the J-Link probe so an external
# RTT client (JLinkGDBServer Terminal I/O / telnet port) can drive the NSH
# console over SEGGER RTT while the core runs.
#
# Non-destructive: halt (already halted by server connect), point the GDB
# server at the known RTT control block, resume with J-Link "go", then hold
# the session open with a shell sleep so the probe stays owned and RTT stays
# bridged.  Detach at the end, leaving the core running.
#
# CR8-0 _SEGGER_RTT control block: 0x081A0000
# CR8-1 _SEGGER_RTT control block: 0x081E0000
#
# Usage:
#   gdb-multiarch -q -batch <elf> -x rzv2h-ipc-hil-rtt-hold.gdb
set pagination off
target remote :50000
monitor halt
printf "RTT_HOLD_PC=%#x\n", $pc
monitor exec SetRTTAddr 0x081A0000
monitor go
shell sleep 55
detach
