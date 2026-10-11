# Deployment Guide: Build, Flash, Debug

**Date:** 2026-10-04
**Scope:** End-to-end workflow for RDK-RZ/V2H (NuttX + PX4) build, volatile RAM load, RTT console, and debug. No persistent flash/cold-boot recipe is approved yet.

---

## 1. Build Tools & Environment Setup

### Setup

```bash
cd /path/to/PX4-Autopilot
source ./build_setup.sh   # checks toolchain/deps, scrubs e2studio CMAKE_* vars, inits submodules
```

Required: `arm-none-eabi-gcc` 9+ on `PATH`, CMake 3.20+, Ninja, Python 3 with
`kconfiglib`, `gdb-multiarch`, SEGGER J-Link software (`JLinkExe`,
`JLinkGDBServer`). `build_setup.sh` reports anything missing.

`refs/` (FSP reference, EVK samples) is **not** a submodule; it is a local,
gitignored directory. See [renesas/reference-source-map.md](./renesas/reference-source-map.md).

---

## 2. Build Targets

The compact bench target is `renesas_rdk-rzv2h_simple`: RTT, HRT, work queues,
volatile params, uORB, four-channel PWMOut and SPI0 ICM20948 accel/gyro.
It excludes flight/payload modules, serial consumers, MAVLink and IPC. Outputs
remain inactive until a finite explicit actuator command. Full default and
multicore targets remain available. The retired core-only target's resources
and evidence are historical. Fresh simple/default/DShot/SIH builds and artifact
audits pass; no target load/cold-boot/electrical proof is claimed. See the
[simple bench guide](renesas/simple-pwm-icm20948-validation.md).

### NuttX-only builds (driver bring-up)

```bash
platforms/nuttx/NuttX/build.sh --list              # nsh, nsh-rtt, ipcc, adc, canfd, ...
platforms/nuttx/NuttX/build.sh nsh-rtt             # distclean + configure + build
platforms/nuttx/NuttX/build.sh --no-clean nsh-rtt  # incremental
# ELF: platforms/nuttx/NuttX/nuttx/nuttx
```

### PX4 builds

**Primary build entry point:**
```bash
./build.sh renesas_rdk-rzv2h_simple
```

**Simple artifacts:**
```bash
./build.sh renesas_rdk-rzv2h_simple
./build.sh --no-clean renesas_rdk-rzv2h_simple  # same profile only
# Output: build/renesas_rdk-rzv2h_simple/
#   ├── renesas_rdk-rzv2h_simple.elf
#   ├── renesas_rdk-rzv2h_simple.px4
#   ├── NuttX/nuttx/.config
#   └── renesas_rdk-rzv2h_simple.bin  (artifact only; not a flashing contract)
```

The simple image is built from
`boards/renesas/rdk-rzv2h/simple.px4board`,
`boards/renesas/rdk-rzv2h/nuttx-config/simple/defconfig`, and
`ROMFS/rdk-rzv2h-simple`.

---

## 3. Load Routes

Only **volatile RAM load** over J-Link/GDB is in use (no reset, image lost on
power cycle). It is proven for NuttX configs (e.g. `nsh-rtt`, IPC raw demo):

```bash
# JLinkGDBServer running for R9A09G057H44_R8_0, then:
gdb-multiarch -q -batch <elf> -x platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-hil-loadstart.gdb
```

Step-by-step and two-core order: [renesas/rzv2h-ipc-hil-test-guide.md](./renesas/rzv2h-ipc-hil-test-guide.md).
There is still no approved raw-`.bin`/xSPI flashing recipe or cold-boot
sequence. RAM load, reset, and target writes require explicit authorization.

---

## 4. Debug: JLink + VS Code

### Configuration

Use the exact simple ELF, the exact device name `R9A09G057H44_R8_0`, and
the user-provided probe serial. The generated VS Code RZV profile is
read-only attach. Reset, load, and continue require explicit authorization.
This is a debug attachment contract, not a validated cold-load recipe. Before
halting the core, stop PWMOut and measure inactive outputs; software actuator
timeouts do not run while halted.

### VS Code Launch Configurations

**File:** `.vscode/launch.json`

Building the target generates `Attach RZV2H CR8 (Core0,
renesas_rdk-rzv2h_simple, read-only)`. Select that profile and enter the
exact authorized probe serial when prompted. The variant appears in the
profile name and its executable is the matching target ELF. The profile uses
`request: "attach"` and only `monitor halt`; it has no reset, load, or
continue command.

For a bounded command-line snapshot, identify the same probe explicitly:

```bash
JLINK_SERIAL=<probe-serial> \
  cmake --build build/renesas_rdk-rzv2h_simple \
  --target jlink_gdb_backtrace
```

The RZ/V2H build does not generate `jlink_upload`, `jlink_debug_gdb`,
`jlink_debug_ozone`, or raw-binary flash targets.

---

## 5. Serial Console (UART Debug)

### Simple CR8-0

**Role:** RTT0 console/debug only.

The simple image has no payload serial consumers and starts PWMOut/ICM20948 asynchronously. Use the RTT shell and the
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
simple uORB proof.

### Full Default PX4

The full default image carries SCI4 LiDAR, SCI5 MAVLink/QGroundControl,
SCI6 RC, and SCI9 GPS. This guide does not document those payload console
routes.

---

## 6. Real-Time Transfer (RTT) Console

### RTT Setup

`JLinkGDBServer` **cannot** bridge RTT on the CR8 cores (its terminal port is
semihosting only). Use JLinkExe, which attaches to the running core without
reset/halt and serves RTT channel 0 as raw TCP on `127.0.0.1:19021`:

```bash
JLINK_SERIAL=<probe-sn> platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 <elf>
platforms/nuttx/Debug/nsh_console_exec.py 'uname -a' 'free' 'dmesg'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop    # before starting JLinkGDBServer
```

- `_SEGGER_RTT` control block: discover it from the exact image with
  `arm-none-eabi-nm <elf>`; do not assume an address from another profile.
- One probe = one owner: stop the bridge before GDB, and vice versa.
- Long NSH lines can hit `CONFIG_NSH_MAXARGUMENTS` or drop an input byte;
  keep commands short.

### Register reads

```bash
platforms/nuttx/Debug/svd_register_tool.py --svd rzv2h.svd info R_SCI4
```

---

## 7. Storage and Logs

The simple image mounts volatile TMPFS at `/fs`. `/fs/params` is available
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
  build/renesas_rdk-rzv2h_simple/renesas_rdk-rzv2h_simple.elf \
  | grep _SEGGER_RTT

# If missing, rebuild the checked-in simple configuration
./build.sh renesas_rdk-rzv2h_simple
```

### Submodule Desynchronization

**Error:** `fatal: index file corrupt; no matching version for ...`

**Solution:**
```bash
git submodule status
git submodule update --init --recursive
./build.sh renesas_rdk-rzv2h_simple
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
     cmake --build build/renesas_rdk-rzv2h_simple \
     --target jlink_gdb_backtrace
   ```

---

## 9. Validation Checklist

Before qualification:

- [x] `renesas_rdk-rzv2h_simple` builds cleanly (2026-10-04 software checkpoint).
- [ ] The exact `renesas_rdk-rzv2h_simple.elf` attaches read-only through J-Link.
- [ ] J-Link uses `R9A09G057H44_R8_0` plus the user-provided probe serial.
- [ ] RTT shows `ver all`, `dmesg`, `system_time`, `work_queue status`, `top`, `uorb top`, and `param show`.
- [ ] No raw `.bin` flashing route is used until the boot-consumer/address contract is authoritative.
- [ ] Raw topics, FIFO acquisition, P94 callbacks and four PWM waveforms are
  recorded independently; no flight-readiness claim is made.

---

## Related Docs

- [System Architecture](system-architecture.md) — CR8-0/CR8-1/CM33 topology.
- [Code Standards](code-standards.md) — Build system and conventions.
- [NuttX Port Status](renesas/port-status-nuttx.md) — Driver status per core.
