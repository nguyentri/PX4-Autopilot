# Read-only health sample of the PX4 io-cr8_1 image: IO loop rates, output
# lease state and raw IPC timeouts. CR8-1 has no console; its boot log is the
# SCI1 xmit ring (see the dump line at the end). No target remote here.
#
#   JLINK_SERIAL=<probe-sn> ../jlink-gdb-oneshot.py cr8_1 <cr8_1.elf> -x rzv2h-px4-cr8_1-io-health.gdb
#   ... -ex 'dump binary memory /tmp/sci1.bin g_sci1port.xmit.buffer g_sci1port.xmit.buffer+g_sci1port.xmit.size'
#
# Sample twice and diff the loop counters to get rates. The attach halts
# CR8-1 for about 1-3 s, which stops its lease and IO health reports to
# CR8-0: never attach to either core while armed.
p g_system_timer
p ((Px4IoCr8*)ModuleBase<Px4IoCr8>::_object._value)->_loop_count
p ((Px4IoCr8*)ModuleBase<Px4IoCr8>::_object._value)->_esc_loop_count
p ((Px4IoCr8*)ModuleBase<Px4IoCr8>::_object._value)->_lease._state
p g_raw[0].stats
p g_sci1port.xmit.head
p g_sci1port.xmit.size
