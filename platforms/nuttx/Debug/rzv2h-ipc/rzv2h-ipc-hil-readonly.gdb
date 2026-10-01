# Read-only RZ/V2H CR8 attach + GIC SPI-target capture.
#
# Non-mutating: halt, capture registers/backtrace, read GIC ICDIPTR target
# bytes for the CR8<->CR8 MHU doorbell SPIs, then detach. No reset, no load,
# no memory or register writes.
#
# GIC distributor base 0x12C10100; ICDIPTR (byte-per-INTID target) at +0x1700.
# Byte address of an SPI's target = 0x12C11800 + INTID.
#
#   INTID 347  MSG4_NS  CR8-1 responder RX   0x12C1195B
#   INTID 348  MSG9_NS  CR8-0 initiator  RX  0x12C1195C
#   INTID 359  RSP4_NS  CR8-0 initiator  TX  0x12C11967
#   INTID 360  RSP9_NS  CR8-1 responder TX   0x12C11968
#   INTID 0    banked SGI target (RAO)       0x12C11800  -> local CPU mask
#
# Usage:
#   arm-none-eabi-gdb -q -batch <elf> -x rzv2h-ipc-hil-readonly.gdb
set pagination off
target remote :50000
monitor halt
printf "== registers ==\n"
info registers
printf "== backtrace ==\n"
bt
printf "== GIC ICDIPTR local-CPU self mask (INTID 0, RAO) ==\n"
x/1bx 0x12C11800
printf "== GIC ICDIPTR target bytes for CR8<->CR8 MHU SPIs ==\n"
printf "INTID347 MSG4_NS:\n"
x/1bx 0x12C1195B
printf "INTID348 MSG9_NS:\n"
x/1bx 0x12C1195C
printf "INTID359 RSP4_NS:\n"
x/1bx 0x12C11967
printf "INTID360 RSP9_NS:\n"
x/1bx 0x12C11968
detach
