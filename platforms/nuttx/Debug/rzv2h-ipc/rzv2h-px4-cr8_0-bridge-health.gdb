# Read-only health sample of the PX4 dualcr8 CR8-0 image: HRT, raw IPC link
# and the px4io_bridge view of CR8-1. Prints only; no target remote here.
#
#   JLINK_SERIAL=<probe-sn> ../jlink-gdb-oneshot.py cr8_0 <cr8_0.elf> -x rzv2h-px4-cr8_0-bridge-health.gdb
#
# The attach halts CR8-0 for about 1-3 s, which starves the CR8-1 output
# lease (50 ms): never run it while armed. Sample twice and diff the counters
# to get rates (g_system_timer counts NuttX ticks).
p g_system_timer
p g_hrt.accum_ticks
p g_raw[0].stats
p/x g_raw[0].tx_hdr->state
p/x g_raw[0].rx_hdr->state
p ((Px4IoBridge*)ModuleBase<Px4IoBridge>::_object._value)->_bridge._stats
p ((Px4IoBridge*)ModuleBase<Px4IoBridge>::_object._value)->_bridge._link_down
p ((Px4IoBridge*)ModuleBase<Px4IoBridge>::_object._value)->_bridge._io_alive
