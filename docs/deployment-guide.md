# Deployment Guide: Build, Flash, Debug

**Date:** 2026-07-30
**Scope:** End-to-end workflow for RDK-RZ/V2H (NuttX + PX4) build, evidence capture, and debug. The exact cold-load/run recipe remains unresolved.

---

## 1. Build Tools & Environment Setup

### Install Build Dependencies

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential cmake ninja-build git wget curl \
  arm-none-eabi-gcc arm-none-eabi-gdb arm-none-eabi-binutils \
  python3 python3-pip python3-dev python3-venv \
  protobuf-compiler
```

**macOS (Homebrew):**
```bash
brew install cmake ninja arm-none-eabi-gcc python3@11
```

### Fetch Submodules

```bash
cd /path/to/PX4-Autopilot
git submodule update --init --recursive
```

(Includes `platforms/nuttx/NuttX/nuttx` and reference FSP in `refs/`.)

---

## 2. Build Targets

The current diagnostic rollback target is `renesas_rdk-rzv2h_core_only`. It
keeps RTT, HRT, work queues, parameters, uORB, and the diagnostic command set,
but excludes payload lower-halves, payload/flight modules, and output init.
Full default and multicore targets still exist for other milestones; this
guide documents the core-only path. The resulting artifacts are build
evidence only and do not prove a cold boot or flashing contract.

### Build Script

**Primary build entry point:**
```bash
./build.sh renesas_rdk-rzv2h_core_only
```

**Core-only artifacts:**
```bash
./build.sh renesas_rdk-rzv2h_core_only
# Output: build/renesas_rdk-rzv2h_core_only/
#   ├── renesas_rdk-rzv2h_core_only.elf
#   ├── renesas_rdk-rzv2h_core_only.px4
#   ├── NuttX/nuttx/.config
#   └── renesas_rdk-rzv2h_core_only.bin  (artifact only; not a flashing contract)
```

The core-only image is built from
`boards/renesas/rdk-rzv2h/core_only.px4board`,
`boards/renesas/rdk-rzv2h/nuttx-config/core_only/defconfig`, and
`ROMFS/rdk-rzv2h-core-only`.

---

## 3. Load Routes

There is no approved raw-`.bin` flashing recipe or authoritative cold-load/run
sequence for the core-only image in this guide. The current debug contract is
attach-only until the boot-consumer/address contract is authoritative.

---

## 4. Debug: JLink + VS Code

### Configuration

Use the exact core-only ELF, the exact device name `R9A09G057H44_R8_0`, and
the user-provided probe serial. The generated VS Code RZV profile is
read-only attach. Reset, load, and continue require explicit authorization.
This is a debug attachment contract, not a validated cold-load recipe.

### VS Code Launch Configurations

**File:** `.vscode/launch.json`

Building the target generates `Attach RZV2H CR8 (Core0,
renesas_rdk-rzv2h_core_only, read-only)`. Select that profile and enter the
exact authorized probe serial when prompted. The variant appears in the
profile name and its executable is the matching target ELF. The profile uses
`request: "attach"` and only `monitor halt`; it has no reset, load, or
continue command.

For a bounded command-line snapshot, identify the same probe explicitly:

```bash
JLINK_SERIAL=<probe-serial> \
  cmake --build build/renesas_rdk-rzv2h_core_only \
  --target jlink_gdb_backtrace
```

The RZ/V2H build does not generate `jlink_upload`, `jlink_debug_gdb`,
`jlink_debug_ozone`, or raw-binary flash targets.

---

## 5. Serial Console (UART Debug)

### Core-only CR8-0

**Role:** RTT0 console/debug only.

The core-only image has no payload serial consumers. Use the RTT shell and the
built-in diagnostic commands:

```text
ver all
dmesg
system_time
work_queue status
param show
top
uorb top
listener parameter_update
perf
```

`listener vehicle_status` belongs the full default image; do not use it as the
core-only uORB proof.

### Full Default PX4

The full default image carries SCI4 LiDAR, SCI5 MAVLink/QGroundControl,
SCI6 RC, and SCI9 GPS. This guide does not document those payload console
routes.

---

## 6. Real-Time Transfer (RTT) Console

### RTT Setup

**Purpose:** Print debug logs without UART overhead; visible in GDB or stand-alone viewer.

**Configuration:**
- JLink RTT address: Extracted at runtime from ELF symbol `_SEGGER_RTT`.
- Viewer: JLinkRTTViewer (Segger) or GDB command `rtty`.

**GDB Commands:**
```bash
(gdb) target remote localhost:2331
(gdb) rtty
# RTT console appears; logs print in real-time
```

Starting the target, changing breakpoints, reset, load, and continue are
outside the default read-only attach procedure and require explicit
authorization.

**Extraction Script (ref):**
```bash
# Extract RTT base address from ELF
arm-none-eabi-readelf -s \
  build/renesas_rdk-rzv2h_core_only/renesas_rdk-rzv2h_core_only.elf \
  | grep _SEGGER_RTT
```

---

## 7. Storage and Logs

The core-only image mounts volatile TMPFS at `/fs`. `/fs/params` is available
for within-boot parameter changes and resets on reboot. This guide does not
document SDHI/ULog or any external storage path.

### System Log (dmesg)

**Real-time:**
```bash
nsh> dmesg
```

**Ringbuffer size:** CONFIG_SYSLOG_BUFFER_SIZE (default 1024).

---

## 8. Common Troubleshooting

### Link Errors (Missing Symbols)

**Error:** `undefined reference to '_SEGGER_RTT'`

**Solution:** Ensure SEGGER RTT symbols included:
```bash
# Check if symbol exists in ELF
arm-none-eabi-nm \
  build/renesas_rdk-rzv2h_core_only/renesas_rdk-rzv2h_core_only.elf \
  | grep _SEGGER_RTT

# If missing, rebuild the checked-in core-only configuration
./build.sh renesas_rdk-rzv2h_core_only
```

### Submodule Desynchronization

**Error:** `fatal: index file corrupt; no matching version for ...`

**Solution:**
```bash
git submodule status
git submodule update --init --recursive
./build.sh renesas_rdk-rzv2h_core_only
```

### JLink Connection Timeout

**Error:** `Can not connect to J-Link via USB.`

**Solution:**
1. Verify USB cable (should show `Bus 001 Device 00X`):
   ```bash
   lsusb | grep Segger
   ```
2. Check device permissions:
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```
3. Stop only the J-Link server started by the current terminal, then rerun
   the serial-bound snapshot helper:
   ```bash
   # Press Ctrl-C in that server's terminal first.
   JLINK_SERIAL=<probe-serial> \
     cmake --build build/renesas_rdk-rzv2h_core_only \
     --target jlink_gdb_backtrace
   ```

---

## 9. Validation Checklist

Before qualification:

- [ ] `renesas_rdk-rzv2h_core_only` builds cleanly.
- [ ] The exact `renesas_rdk-rzv2h_core_only.elf` attaches read-only through J-Link.
- [ ] J-Link uses `R9A09G057H44_R8_0` plus the user-provided probe serial.
- [ ] RTT shows `ver all`, `dmesg`, `system_time`, `work_queue status`, `top`, `uorb top`, and `param show`.
- [ ] No raw `.bin` flashing route is used until the boot-consumer/address contract is authoritative.
- [ ] No hardware proof claims are made for the core-only image.

---

## Related Docs

- [System Architecture](system-architecture.md) — CR8-0/CR8-1/CM33 topology.
- [Code Standards](code-standards.md) — Build system and conventions.
- [NuttX Port Status](renesas/port-status-nuttx.md) — Driver status per core.
