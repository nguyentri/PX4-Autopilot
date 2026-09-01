#!/bin/sh
#
# Shared helpers for the RZ/V2H IPC-demo single-probe loaders
# (rzv2h-ipc-demo-load-both-auto.sh, rzv2h-ipc-demo-load-both-manual.sh).
#
# Sourced, not executed. Provides:
#   resolve_tools           locate JLinkGDBServerCLExe + gdb-multiarch
#   preflight_probe_free    drop stale J-Link owners of our probe / GDB port
#   port_listening <port>   true if a TCP listener is up on the port
#   load_core   <dev> <elf> <label>   volatile RAM load via loadstart.gdb
#   verify_core <dev> <elf> <label>   non-destructive halt/PC/resume check
#
# Callers set (before sourcing or before each call): JLINK_SERIAL, GDB_PORT,
# LOADSTART, VERIFY, LOG_DIR, VERBOSE (0/1). resolve_tools sets JLINK_GDB_BIN
# and GDB_BIN. Server + gdb chatter goes to per-core logs under LOG_DIR; only
# VERBOSE=1 tees it to stderr so the default run stays quiet.

# --- tool discovery ---------------------------------------------------------
resolve_tools() {
	if [ -n "${JLINK_GDB:-}" ]; then
		JLINK_GDB_BIN="${JLINK_GDB}"
	elif command -v JLinkGDBServerCLExe >/dev/null 2>&1; then
		JLINK_GDB_BIN=$(command -v JLinkGDBServerCLExe)
	elif [ -x /opt/SEGGER/JLink/JLinkGDBServerCLExe ]; then
		JLINK_GDB_BIN=/opt/SEGGER/JLink/JLinkGDBServerCLExe
	else
		echo "JLinkGDBServerCLExe not found (set JLINK_GDB)" >&2
		return 2
	fi

	if [ -n "${GDB:-}" ]; then
		GDB_BIN="${GDB}"
	elif command -v gdb-multiarch >/dev/null 2>&1; then
		GDB_BIN=$(command -v gdb-multiarch)
	else
		echo "gdb-multiarch not found (set GDB)" >&2
		return 2
	fi
	return 0
}

# --- listener probe (portable; original /dev/tcp form is dash-unsafe) --------
port_listening() {
	if command -v ss >/dev/null 2>&1; then
		ss -ltn 2>/dev/null | grep -q "[:.]${1}[[:space:]]"
	else
		# /proc fallback: match the port as the 2nd column's hex suffix.
		hex=$(printf '%04X' "${1}")
		grep -qi ":${hex} " /proc/net/tcp 2>/dev/null
	fi
}

# --- free the probe before we grab it ---------------------------------------
# The demo runs one active J-Link owner at a time. A stale GDB server (crashed
# load) or an open JLinkExe RTT bridge keeps the USB claimed and makes the next
# "Connecting to J-Link..." fail. Drop any owner tied to *our* serial, then any
# leftover listener on our GDB port. Matches on "usb=<serial>" so it never
# touches a probe the user is using for something unrelated.
preflight_probe_free() {
	killed=0
	for pat in "usb=${JLINK_SERIAL}" "-select ${JLINK_SERIAL}"; do
		if pgrep -f "${pat}" >/dev/null 2>&1; then
			echo "-- preflight: releasing stale J-Link owner (${pat})"
			pkill -f "${pat}" 2>/dev/null || true
			killed=1
		fi
	done
	# A GDB server still holding our TCP port would collide with -port.
	if port_listening "${GDB_PORT}"; then
		echo "-- preflight: GDB port ${GDB_PORT} still bound; clearing"
		pkill -f "port ${GDB_PORT}" 2>/dev/null || true
		killed=1
	fi
	[ "${killed}" -eq 1 ] && sleep 1
	# Wait (up to ~5s) for the port to actually free.
	tries=0
	while port_listening "${GDB_PORT}"; do
		tries=$((tries + 1))
		[ "${tries}" -gt 50 ] && { echo "GDB port ${GDB_PORT} still busy after preflight" >&2; return 1; }
		sleep 0.1
	done
	return 0
}

# --- launch a single-run GDB server and wait until it listens ---------------
# Echoes the server PID on success; server output is appended to $log.
# Drops -strict and uses a longer -timeout than the original loader so a slow
# SWD bring-up does not abort the connect.
_start_server() {
	dev="$1"; log="$2"
	"${JLINK_GDB_BIN}" -device "${dev}" -select "usb=${JLINK_SERIAL}" \
		-if SWD -speed auto -LocalhostOnly 1 -singlerun \
		-timeout 15000 -powertarget 0 -port "${GDB_PORT}" -nogui \
		>>"${log}" 2>&1 &
	srv_pid=$!
	tries=0
	while ! port_listening "${GDB_PORT}"; do
		kill -0 "${srv_pid}" 2>/dev/null || return 1
		tries=$((tries + 1))
		[ "${tries}" -gt 150 ] && { kill "${srv_pid}" 2>/dev/null || true; return 1; }
		sleep 0.1
	done
	echo "${srv_pid}"
	return 0
}

# --- volatile RAM load of one core (mutating), with connect retry -----------
# Returns 0 on a clean loadstart (ENTRY/SET_PC seen), 1 otherwise.
load_core() {
	dev="$1"; elf="$2"; label="$3"
	log="${LOG_DIR}/load-$(echo "${label}" | tr ' /()' '____').log"
	: >"${log}"

	attempt=0
	while [ "${attempt}" -lt 3 ]; do
		attempt=$((attempt + 1))
		echo "== ${label}: load attempt ${attempt} (log: ${log}) =="
		preflight_probe_free || { sleep 1; continue; }

		srv_pid=$(_start_server "${dev}" "${log}") || {
			echo "-- ${label}: J-Link connect failed (attempt ${attempt})"
			sleep 1; continue
		}

		out=$("${GDB_BIN}" -q -batch "${elf}" -x "${LOADSTART}" 2>&1)
		echo "${out}" >>"${log}"
		[ "${VERBOSE:-0}" = "1" ] && echo "${out}" >&2

		wait "${srv_pid}" 2>/dev/null || true

		if echo "${out}" | grep -q 'SET_PC='; then
			echo "== ${label}: loaded, probe released =="
			return 0
		fi
		echo "-- ${label}: load did not report SET_PC (attempt ${attempt})"
		sleep 1
	done
	echo "!! ${label}: load FAILED after ${attempt} attempts (see ${log})" >&2
	return 1
}

# --- non-destructive post-load verify (halt/PC/resume) ----------------------
# Re-attaches to the running core, halts briefly, checks the PC is sane, then
# resumes via loadstart's peer (verify-resume.gdb already does monitor go), so
# the demo keeps running. Returns 0 = PASS, 1 = FAIL.
verify_core() {
	dev="$1"; elf="$2"; label="$3"
	log="${LOG_DIR}/verify-$(echo "${label}" | tr ' /()' '____').log"
	: >"${log}"

	preflight_probe_free || return 1
	srv_pid=$(_start_server "${dev}" "${log}") || {
		echo "!! ${label}: verify connect failed" >&2; return 1
	}
	out=$("${GDB_BIN}" -q -batch "${elf}" -x "${VERIFY}" 2>&1)
	echo "${out}" >>"${log}"
	[ "${VERBOSE:-0}" = "1" ] && echo "${out}" >&2
	wait "${srv_pid}" 2>/dev/null || true

	pc=$(echo "${out}" | sed -n 's/^RUN_PC=\([0-9a-fA-Fx]*\).*/\1/p' | head -n1)
	case "${pc}" in
		""|0x0|0x00000000|0xffffffff)
			echo "== ${label}: VERIFY FAIL (RUN_PC='${pc:-none}', see ${log}) =="
			return 1 ;;
		*)
			echo "== ${label}: VERIFY PASS (running at PC=${pc}) =="
			return 0 ;;
	esac
}
