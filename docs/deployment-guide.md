# Deployment Guide: Build, Flash, Debug

**Date:** 2026-07-26
**Scope:** End-to-end workflow for RDK-RZ/V2H (NuttX + PX4) build, flash, and debug.

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

The current critical path builds and deploys CR8-0 only. CR8-1 and CM33
artifacts are optional G11 work after the CR8-0 PX4 drone path and required
reliability gates pass. Do not treat their absence as a CR8-0 deployment
failure.

### Build Script

**Primary build entry point:**
```bash
./build.sh rdk-rzv2h_default
```

**Available targets:**
```bash
./build.sh --list | grep rdk-rzv
# Outputs:
# - renesas_rdk-rzv2h_default      (CR8-0 flight stack)
# - renesas_rdk-rzv2h-io-cr8_1     (CR8-1 IO co-processor)
# - renesas_rdk-rzv2h-io-cm33      (CM33 IO co-processor)
```

### Build Individual Cores

**CR8-0 (Flight Stack):**
```bash
./build.sh renesas_rdk-rzv2h_default
# Output: build/renesas_rdk-rzv2h_default/
#   ├── bin/px4
#   ├── src/modules/px4iofirmware/px4io.elf
#   └── nuttx/nuttx.bin  (embedded NuttX kernel)
```

**CR8-1 (IO Co-processor):**
```bash
./build.sh renesas_rdk-rzv2h-io-cr8_1
# Output: build/renesas_rdk-rzv2h-io-cr8_1/nuttx/nuttx.bin
```

**CM33 (Alternative IO):**
```bash
./build.sh renesas_rdk-rzv2h-io-cm33
# Output: build/renesas_rdk-rzv2h-io-cm33/nuttx/nuttx.bin
```

### Custom Board Config

**Override defconfig:**
```bash
./build.sh renesas_rdk-rzv2h_default -DBOARD_CONFIG=nsh-leds
# Selects configs/nsh-leds/ instead of default
```

---

## 3. Flash Routes

### Option A: SD Card Boot (Recommended for CR8-0)

**Preparation:**

1. Build the CR8-0 image. Build CR8-1/CM33 only when executing the final
   multicore milestone.
2. Format microSD card (FAT32):
   ```bash
   sudo mkfs.vfat /dev/sdX1
   mkdir /mnt/sd
   sudo mount /dev/sdX1 /mnt/sd
   ```

3. Copy bootloader (u-boot) and kernels:
   ```bash
   # Obtain u-boot.bin from Renesas BSP
   sudo cp /path/to/u-boot.bin /mnt/sd/u-boot.bin
   
   # Copy CR8-0 (primary)
   sudo cp build/renesas_rdk-rzv2h_default/nuttx/nuttx.bin /mnt/sd/nuttx_cr8_0.bin
   
   # Optional G11 only: copy CR8-1
   sudo cp build/renesas_rdk-rzv2h-io-cr8_1/nuttx/nuttx.bin /mnt/sd/nuttx_cr8_1.bin
   
   # Optional G11 only: copy CM33
   sudo cp build/renesas_rdk-rzv2h-io-cm33/nuttx/nuttx.bin /mnt/sd/nuttx_cm33.bin
   ```

4. Sync and eject:
   ```bash
   sync
   sudo umount /mnt/sd
   ```

5. Insert SD card into RDK-RZ/V2H and power on.

**Verification:** The `nsh-rtt` configuration exposes the CR8-0 NuttX shell
on SCI4 (115200 8N1); boot and syslog diagnostics appear on SEGGER RTT.

---

### Option B: eMMC Flash (Factory)

**Prerequisites:**
- Renesas eMMC flashing tool (Renesas BSP documentation).
- JTAG or serial bootloader mode.

**Flow:**
1. Enter bootloader mode (DIP switch configuration; consult board manual).
2. Run Renesas flash utility:
   ```bash
   renesas-flash-tool --device /dev/ttyUSB0 \
     --addr 0x00000000 --file build/.../nuttx.bin
   ```
3. Power cycle; kernel boots from eMMC.

(Detailed tool usage beyond scope; refer to Renesas board documentation.)

---

### Option C: xSPI/QSPI Parameter Storage

**Status:** Board paramfs/MTD source exists; on-target persistence validation is pending.

**Plan:** LittleFS on xSPI for parameter storage. Keep ULog on a separately
validated SDHI mount.

**Blocker:** Partition-boundary proof, mount, parameter save/reboot/load, and
power-loss recovery. Do not treat source presence as validated persistence.

---

## 4. Debug: JLink + VS Code

### Configuration (commit a3c58b73a52)

**JLink Setup:**

1. Install JLink EDU/commercial license (Segger).
   ```bash
   # macOS
   brew install segger-jlink
   
   # Linux
   wget https://www.segger.com/downloads/jlink/JLink_Linux_x86_64.deb
   sudo dpkg -i JLink_Linux_x86_64.deb
   ```

2. Verify JLink connection:
   ```bash
   JLinkExe -device RZV2H -if SWD -speed 4000
   # Output: Connected to RZV2H via SWD at 4 MHz
   ```

### VS Code Launch Configurations

**File:** `.vscode/launch.json`

**CR8-0 (NuttX + PX4):**
```json
{
  "name": "Attach CR8-0 (JLink)",
  "type": "cppdbg",
  "request": "launch",
  "program": "${workspaceFolder}/build/renesas_rdk-rzv2h_default/nuttx/nuttx.elf",
  "cwd": "${workspaceFolder}",
  "MIMode": "gdb",
  "miDebuggerPath": "arm-none-eabi-gdb",
  "miDebuggerArgs": "-q -ex 'target remote localhost:2331'",
  "preLaunchTask": "jlink-server",
  "stopAtEntry": true,
  "externalConsole": false
}
```

**CR8-1 (IO co-processor):**
```json
{
  "name": "Attach CR8-1 (JLink)",
  "type": "cppdbg",
  "request": "launch",
  "program": "${workspaceFolder}/build/renesas_rdk-rzv2h-io-cr8_1/nuttx/nuttx.elf",
  "MIMode": "gdb",
  "miDebuggerPath": "arm-none-eabi-gdb",
  "miDebuggerArgs": "-q -ex 'target remote localhost:2332' -ex 'set mem inaccessible-by-default off'",
  "preLaunchTask": "jlink-cr8_1",
  "stopAtEntry": true
}
```

**Task (`.vscode/tasks.json`):**
```json
{
  "label": "jlink-server",
  "type": "shell",
  "command": "JLinkGDBServer",
  "args": ["-device", "RZV2H", "-if", "SWD", "-speed", "4000", "-port", "2331"],
  "isBackground": true,
  "problemMatcher": { "pattern": { "regexp": "Listening on port" } }
}
```

### OpenOCD (Alternative)

**Configuration:** `.openocd/rdk-rzv2h.cfg`

```tcl
# Renesas RZ/V2H OpenOCD configuration
source [find interface/jlink.cfg]
transport select swd
source [find target/rzv2h.cfg]
```

**Launch:**
```bash
openocd -f .openocd/rdk-rzv2h.cfg
# In GDB: target remote localhost:3333
```

---

## 5. Serial Console (UART Debug)

### Serial Modes

#### Standalone CR8-0 NuttX

**Role:** SCI4 shell + RTT diagnostics.

**Device:** `/dev/ttyUSB0` for the SCI4 adapter on the RDK carrier board.

**Settings:** 115200 baud, 8 data bits, 1 stop bit, no parity.

**Connection:**
```bash
minicom -D /dev/ttyUSB0 -b 115200
# or
picocom -b 115200 /dev/ttyUSB0
# or
screen /dev/ttyUSB0 115200
```

**NuttX Shell Prompt:**
```
nsh> help
nsh> ps
nsh> dmesg
```

#### Integrated PX4 CR8-0

**Role:** RTT0 console/debug with SCI4 LiDAR, SCI5 MAVLink/QGroundControl,
SCI6 RC, and SCI9 GPS.

**Policy:** SCI3 is not an active console on the RDK-RZV2H board.

**First drone-equivalent serial gates:** GPS SCI9 = 115200 8N1. RC SCI6 =
100000 8E2 with the board inversion path verified on target.

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
(gdb) break main
(gdb) continue
(gdb) rtty
# RTT console appears; logs print in real-time
```

**Extraction Script (ref):**
```bash
# Extract RTT base address from ELF
arm-none-eabi-readelf -s build/.../nuttx.elf | grep _SEGGER_RTT
```

---

## 7. Log Collection

### ULog Format (PX4 Native)

**Status:** Post-G9 optional. The first drone-equivalent CR8-0 image keeps
SDHI/ULog disabled because the checked-in FSP drone reference has no SDHI
driver. Use this procedure only after the separate SDHI track passes.

**Path:** `/fs/microsd/` (SD card via SDHI0).

**Capture:**
```bash
nsh> ls /fs/microsd/*.ulg
/fs/microsd/2026-07-11_12-34-56.ulg
```

**Decode:**
```bash
python -m pyulog.tools.export 2026-07-11_12-34-56.ulg --output-file data.csv
```

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
arm-none-eabi-nm build/.../nuttx.elf | grep _SEGGER_RTT

# If missing, re-link with RTT library
./build.sh renesas_rdk-rzv2h_default -DCONFIG_SEGGER_RTT=y
```

### Submodule Desynchronization

**Error:** `fatal: index file corrupt; no matching version for ...`

**Solution:**
```bash
git submodule foreach git reset --hard
git submodule update --init --recursive
./build.sh clean
./build.sh renesas_rdk-rzv2h_default
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
3. Restart JLink daemon:
   ```bash
   killall JLinkGDBServer
   JLinkGDBServer -device RZV2H -if SWD -speed 4000
   ```

---

## 9. Validation Checklist

Before flight qualification:

- [ ] Build completes without warnings.
- [ ] CR8-0 boots to the standalone NuttX shell on SCI4; RTT shows boot diagnostics.
- [ ] Integrated PX4 CR8-0 keeps console/debug on RTT0 and routes MAVLink/QGroundControl on SCI5, not RTT0.
- [ ] CR8-0 boots and runs without CR8-1, CM33, or a remote endpoint.
- [ ] CR8-1/CM33 load and synchronize only when validating optional G11.
- [ ] GDB attaches via JLink; can set breakpoints and step.
- [ ] xSPI parameter save/reboot/load passes.
- [ ] SDHI/ULog remains disabled for the first drone-equivalent baseline.
- [ ] MAVLink heartbeat and telemetry are visible in QGroundControl over SCI5.
- [ ] Stress test: 1 hour continuous flight simulation without crash.

---

## Related Docs

- [System Architecture](system-architecture.md) — CR8-0/CR8-1/CM33 topology.
- [Code Standards](code-standards.md) — Build system and conventions.
- [NuttX Port Status](renesas/port-status-nuttx.md) — Driver status per core.
