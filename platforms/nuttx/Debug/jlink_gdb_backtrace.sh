#!/bin/sh

if [ "$#" -ne 1 ] || [ ! -f "$1" ]
then
	echo "usage: $0 <matching-elf>"
	exit 1
fi

if command -v gdb-multiarch >/dev/null 2>&1
then
	GDB_CMD=$(command -v gdb-multiarch)

elif command -v arm-none-eabi-gdb >/dev/null 2>&1
then
	GDB_CMD=$(command -v arm-none-eabi-gdb)

else
	echo "gdb arm-none-eabi or multi-arch not found"
	exit 1
fi

case "${GDB_ARCH_MACROS:-ARMv7M}" in
	ARMv7R)
		arch_macro=ARMv7R
		arch_state_command=armv7rstate
		;;
	ARMv7M)
		arch_macro=ARMv7M
		arch_state_command=vecstate
		;;
	*)
		echo "unsupported GDB architecture macro set: ${GDB_ARCH_MACROS}"
		exit 1
		;;
esac

file "$1"

gdb_cmd_file=$(mktemp)
trap 'rm -f "${gdb_cmd_file}"' EXIT HUP INT TERM

cat >"${gdb_cmd_file}" <<EOL
source ${WORKSPACE}/platforms/nuttx/Debug/${arch_macro}
source ${WORKSPACE}/platforms/nuttx/Debug/NuttX
source ${WORKSPACE}/platforms/nuttx/Debug/PX4

set mem inaccessible-by-default off
set print pretty
set pagination off

target remote localhost:2331

monitor halt
monitor regs

dmesg

perf

showtasks
backtrace

${arch_state_command}

info_nxthreads

nxthread_all_bt

detach
EOL

"${GDB_CMD}" -silent --nh --nx --nw -batch \
	-ix="${WORKSPACE}/platforms/nuttx/NuttX/nuttx/tools/nuttx-gdbinit" \
	-x "${gdb_cmd_file}" "$1"
