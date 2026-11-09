# Read-only health sample of the rzv2h_heartbeat module in the PX4 demo pair.
# Works on either core: CR8-0 renesas_rdk-rzv2h_demo (initiator) or CR8-1
# renesas_rdk-rzv2h-io-cr8_1_demo (responder). No target remote here.
#
#   JLINK_SERIAL=<probe-sn> ../jlink-gdb-oneshot.py cr8_1 <cr8_1 demo.elf> -x rzv2h-px4-demo-heartbeat-health.gdb
#
# Sample twice and diff the counters. The attach halts the sampled core for
# about 1-3 s, so the PEER legitimately reports "lost" during the sample.
# Prefer `rzv2h_heartbeat status` on the console (CR8-0: MAVLink shell on SCI5,
# CR8-1: RTT NSH) and use this only when the console is unavailable.
p g_system_timer
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_loop_count
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_monitor._epoch
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_monitor._sequence
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_monitor._last_rx_us
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_monitor._peer
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_monitor._counters
p ((IpcHeartbeat*)ModuleBase<IpcHeartbeat>::_object._value)->_stats
p g_raw[0].stats
