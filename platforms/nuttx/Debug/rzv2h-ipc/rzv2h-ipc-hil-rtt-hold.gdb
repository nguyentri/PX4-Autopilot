# Historical entry point. JLinkGDBServer cannot bridge CR8 RTT.
# Use ../nuttx-rtt-bridge.sh start <cr8_0|cr8_1> <exact-loaded-elf>.
echo CR8 RTT requires nuttx-rtt-bridge.sh and the exact loaded ELF.\n
quit 2
