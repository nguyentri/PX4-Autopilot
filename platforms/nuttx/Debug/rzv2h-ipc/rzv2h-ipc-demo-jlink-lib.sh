#!/bin/sh
#
# Shared helpers for the RZ/V2H IPC-demo single-probe loaders
# (rzv2h-ipc-demo-load-both-auto.sh, rzv2h-ipc-demo-load-both-manual.sh).
#
# Sourced, not executed. Provides:
#   resolve_tools           locate JLinkGDBServerCLExe + gdb-multiarch
#   preflight_probe_free    refuse an occupied GDB port
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

# A port or probe identifier does not establish process ownership.
preflight_probe_free() {
	if port_listening "${GDB_PORT}"; then
		echo "GDB port ${GDB_PORT} is already in use; release its owner first" >&2
		return 1
	fi
	return 0
}

_server_identity() {
	[ -n "${srv_pid:-}" ] && [ -r "/proc/${srv_pid}/stat" ] || return 1
	server_identity=$(awk '{sub(/^.*\) /, ""); if ($1 != "Z") print $2, $20}' "/proc/${srv_pid}/stat") || return 1
	[ "${server_identity}" = "$$ ${srv_start:-}" ]
}

_stop_server() {
	if _server_identity; then
		kill "${srv_pid}" 2>/dev/null || true
		stop_tries=0
		while _server_identity; do
			stop_tries=$((stop_tries + 1))
			if [ "${stop_tries}" -ge 50 ]; then
				kill -KILL "${srv_pid}" 2>/dev/null || true
				break
			fi
			sleep 0.1
		done
	fi
	[ -z "${srv_pid:-}" ] || wait "${srv_pid}" 2>/dev/null || true
	srv_pid=
}

_server_owns_port() {
	_server_identity || return 1
	server_hex=$(printf '%04X' "${GDB_PORT}")
	server_inodes=$(awk -v port="${server_hex}" '$4 == "0A" && toupper($2) ~ (":" port "$") {print $10}' /proc/net/tcp /proc/net/tcp6)
	for server_inode in ${server_inodes}; do
		for server_fd in /proc/"${srv_pid}"/fd/*; do
			[ "$(readlink "${server_fd}" 2>/dev/null)" != "socket:[${server_inode}]" ] || return 0
		done
	done
	return 1
}

# --- launch a single-run GDB server and wait until it listens ---------------
# Retains the owned child PID in this shell; output is appended to $log.
# Drops -strict and uses a longer -timeout than the original loader so a slow
# SWD bring-up does not abort the connect. Extra arguments after <log> go to
# the server (verify_core passes -noreset -noir to attach without side effects).
_start_server() {
	dev="$1"; log="$2"; shift 2
	"${JLINK_GDB_BIN}" -device "${dev}" -select "usb=${JLINK_SERIAL}" \
		-if SWD -speed auto -LocalhostOnly 1 -singlerun \
		-timeout 15000 -powertarget 0 -port "${GDB_PORT}" -nogui "$@" \
		>>"${log}" 2>&1 &
	srv_pid=$!
	srv_start=$(awk '{sub(/^.*\) /, ""); print $20}' "/proc/${srv_pid}/stat") || { _stop_server; return 1; }
	tries=0
	while ! _server_owns_port; do
		_server_identity || { _stop_server; return 1; }
		tries=$((tries + 1))
		[ "${tries}" -gt 150 ] && { _stop_server; return 1; }
		sleep 0.1
	done
	return 0
}

# A failed first connect makes the J-Link DLL pulse the reset pin and cold
# reset the core, which also kills an image this run did not mean to touch.
# Prints the first reset marker in $1 from line $2 (default 1), so a retry
# only judges its own part of an appended log. "DBGEN is not asserted" alone
# means the core was held in reset or never started (normal for a dead core
# before a load; a failure on an attach).
_log_reset_marker() {
	tail -n +"${2:-1}" "$1" | grep -Eo 'Resetting via Reset pin|cold reset sequence|DBGEN is not asserted' | head -n1
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

		from=$(($(wc -l <"${log}") + 1))
		_start_server "${dev}" "${log}" || {
			echo "-- ${label}: J-Link connect failed (attempt ${attempt})"
			sleep 1; continue
		}

		gdb_ret=0
		out=$("${GDB_BIN}" -q -batch "${elf}" -x "${LOADSTART}" 2>&1) || gdb_ret=$?
		echo "${out}" >>"${log}"
		[ "${VERBOSE:-0}" = "1" ] && echo "${out}" >&2

		_stop_server

		case "$(_log_reset_marker "${log}" "${from}")" in
		"") ;;
		DBGEN*) echo "-- ${label}: DBGEN not asserted on connect (core held in reset or not started)" >&2 ;;
		*) echo "!! ${label}: the J-Link log shows a reset-pin / cold reset; check every core's image" >&2 ;;
		esac
		if [ "${gdb_ret}" -eq 0 ] && echo "${out}" | grep -q 'SET_PC='; then
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
	_start_server "${dev}" "${log}" -noreset -noir || {
		echo "!! ${label}: verify connect failed" >&2; return 1
	}
	gdb_ret=0
	out=$("${GDB_BIN}" -q -batch "${elf}" -x "${VERIFY}" 2>&1) || gdb_ret=$?
	echo "${out}" >>"${log}"
	[ "${VERBOSE:-0}" = "1" ] && echo "${out}" >&2
	_stop_server

	[ "${gdb_ret}" -eq 0 ] || return 1
	if [ -n "$(_log_reset_marker "${log}")" ]; then
		echo "== ${label}: VERIFY FAIL (J-Link reset the core while attaching, see ${log}) =="
		return 1
	fi
	pc=$(echo "${out}" | sed -n 's/^RUN_PC=\([0-9a-fA-Fx]*\).*/\1/p' | head -n1)
	# gdb's printf "%#x" prints zero as a bare "0": a core parked at the
	# reset vector must not pass as running.
	case "${pc}" in
		""|0|0x0|0x00000000|0xffffffff)
			echo "== ${label}: VERIFY FAIL (RUN_PC='${pc:-none}', see ${log}) =="
			return 1 ;;
		*)
			echo "== ${label}: VERIFY PASS (running at PC=${pc}) =="
			return 0 ;;
	esac
}
