#! /bin/sh

if command -v gdb-multiarch > /dev/null 2>&1
then
	GDB_CMD=$(command -v gdb-multiarch)

elif command -v arm-none-eabi-gdb > /dev/null 2>&1
then
	GDB_CMD=$(command -v arm-none-eabi-gdb)

else
	echo "gdb arm-none-eabi or multi-arch not found"
	exit 1
fi

: "${1:?usage: upload_jlink_gdb.sh <elf>}"
file "$1"

gdb_cmd_file=$(mktemp) || exit 1
trap 'rm -f "${gdb_cmd_file}"' EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

cat >"${gdb_cmd_file}" <<EOL
target remote localhost:2331
monitor reset 0
load
monitor reset 0
monitor go
EOL

for i in 1 2 3;
do
	"${GDB_CMD}" -silent --nh --nx --nw -batch -x "${gdb_cmd_file}" "$1"
	gdb_ret=$?

	if [ $gdb_ret -ne 0 ]; then
		echo "GDB error on attempt ${i}"
		[ "${i}" -eq 3 ] || sleep 5
	else
		exit 0
	fi
done

exit 1
