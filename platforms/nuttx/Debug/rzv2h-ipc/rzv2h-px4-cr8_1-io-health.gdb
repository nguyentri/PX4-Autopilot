# Read-only health sample of the PX4 CR8-1 `default` image (`rzv2h_io` v3
# output supervisor): worker report, control status words and raw IPC link
# stats. This image logs to RTT; it has no SCI console. No target remote here.
#
#   JLINK_SERIAL=<probe-sn> ../jlink-gdb-oneshot.py cr8_1 <cr8_1.elf> -x rzv2h-px4-cr8_1-io-health.gdb
#
# _worker_status words (src/apps/output-worker.hpp): flags, sequence,
# generation, loops, time_us lo, time_us hi, epoch. Sample twice and diff the
# loops word to get rates. The attach halts CR8-1 for about 1-3 s, which stops
# its worker and status reports to CR8-0: never attach to either core while armed.
p g_system_timer
p ModuleBase<IoSupervisor>::_object._value
p ModuleBase<IoSupervisor>::_object._value->_worker_status._record
p ModuleBase<IoSupervisor>::_object._value->_control_status._record
p g_raw[0].stats
