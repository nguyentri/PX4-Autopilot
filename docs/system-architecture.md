# RDK-RZ/V2H System Architecture

**Date:** 2026-07-11  
**Status:** Foundational (Phase 1)

---

## 1. Layered Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                    PX4 Modules                       │
│  (Attitude Control, Position Control, EKF2, etc.)   │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              PX4 Hardware Abstraction Layer          │
│  (board_config.h, sensors, timers, storage)         │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                  NuttX RTOS                          │
│  (Task scheduler, memory management, device layer)  │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│           NuttX Driver Port (RZ/V2H)                │
│  GPIO | UART | SPI | I2C | Timers | DMA | Clock    │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│       RZ/V2H Hardware & Peripherals                 │
│ GIC/ICU | CPG | MHU | DMAC | SDHI | XSPI | etc.    │
└─────────────────────────────────────────────────────┘
```

---

## 2. Multicore Topology

### Core Roles

**CR8-0 (Primary Flight Control)**
- Cortex-R8 @ 1.5 GHz
- NuttX kernel + PX4 flight stack
- Runs: attitude control, nav, sensor fusion, MAVLink
- Boot: internal SRAM reset vector 0x00000000

**CR8-1 (IO Co-Processor)**
- Cortex-R8 @ 1.5 GHz
- NuttX + PX4-IO firmware (px4io_bridge)
- Runs: PWM output, RC input, sensor buffering
- Boot: shared DRAM reset vector 0x40000000
- Firmware loaded by CR8-0 via linker script

**CM33 (Alternative IO)**
- Cortex-M33 @ 200 MHz
- Optional: boots from DRAM, runs same px4io role
- Used when CR8-1 unavailable or for debug features
- Boot vector: 0x40100000

### Core Synchronization

**IPC Transport:** NuttX IPCC (Inter-Processor Communication Controller) over MHU (Message Handling Unit)

- **IPCC:** Character device `/dev/ipcc0`, `/dev/ipcc1` (one per core pair)
- **MHU:** Hardware message unit for core-to-core signaling
- **Protocol:** uORB message framing (see `px4io_bridge.cpp`)
  - Frame: `[msg_id (2B) | seq_num (2B) | length (2B) | payload | crc16 (2B)]`
  - Sequence check prevents stale/reordered messages
  - CRC validation detects corruption

**Files:**
- NuttX driver: `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_ipcc.c`, `rzv_mhu_core.c`
- PX4 bridge: `boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp`, `px4io_bridge.cpp`

---

## 3. PX4 Board Directory Map

```
boards/renesas/
├── rdk-rzv2h/                          (CR8-0 PX4 flight stack)
│   ├── Kconfig                         (board variant Kconfig)
│   ├── board_config.h                  (GPIO/UART/SPI/I2C assignment)
│   ├── board_init.cpp                  (early init, sensor probe)
│   ├── nuttx-config/                   (NuttX defconfig per profile)
│   │   ├── nsh/defconfig               (shell + debugging)
│   │   ├── ipcc/defconfig              (IPC enabled)
│   │   └── ipcc-multi/defconfig        (dual-core IPC stress test)
│   ├── px4io_cr8_0/                    (uORB bridge to CR8-1/CM33)
│   │   ├── px4io_bridge.cpp
│   │   ├── uorb_bridge.cpp
│   │   ├── uorb_bridge.h
│   │   ├── protocol.h                  (message frame defs)
│   │   └── sharedmem_transport.cpp/h   (IPCC wrapper)
│   ├── src/
│   │   ├── board.cpp, board.h
│   │   ├── CMakeLists.txt
│   │   └── init_modules.cpp            (PX4 app list)
│   └── init/
│       └── rc.board_defaults.cmds      (startup script)
│
├── rdk-rzv2h-io-cr8_1/                 (CR8-1 px4io firmware)
│   ├── px4io_cr8_1/
│   │   ├── px4io_cr8.cpp               (CR8-1 main)
│   │   ├── uorb_bridge.cpp
│   │   ├── sharedmem_transport.cpp
│   │   └── protocol.h
│   └── nuttx-config/
│       ├── nsh/defconfig
│       └── ipcc/defconfig              (IPCC in reverse role)
│
└── rdk-rzv2h-io-cm33/                  (CM33 alternative IO)
    ├── px4io_m33/
    │   ├── px4io_m33.cpp
    │   ├── sharedmem_transport.cpp
    │   └── protocol.h
    └── nuttx-config/
```

---

## 4. Build Orchestration

**Entry Point:** PX4 CMake system

```
1. User calls: ./build.sh renesas_rdk-rzv2h_default
2. PX4 CMake finds board def in boards/renesas/rdk-rzv2h/
3. CMake reads nuttx-config/ and generates NuttX Kconfig includes
4. NuttX build inherits:
   - arch/arm/src/rzv/ drivers (GPIO, UART, SPI, etc.)
   - boards/arm/rzv/rdk-rzv2h/configs/ (board-specific config)
5. NuttX libnuttx.a links against PX4 board/src/ modules
6. Final ELF: px4 (CR8-0 image)
7. Optional: build px4io_bridge into separate CR8-1 firmware
```

**Kconfig Hierarchy:**
```
boards/renesas/rdk-rzv2h/Kconfig
  └─> boards/renesas/rdk-rzv2h/nuttx-config/<profile>/Kconfig
      └─> NuttX arch/arm/src/rzv/Kconfig
          ├─> Platform drivers (GPIO, UART, SPI, I2C, Timers, DMA, Clock)
          ├─> Board-specific pins & muxing
          └─> RZ/V2H NuttX drivers; ADC/WDT/CAN-FD/SDHI remain optional
              and are not active in the checked-in drone FSP reference
```

---

## 5. Memory Topology (Single-Core CR8-0)

| Region | Start | Size | Purpose |
|--------|-------|------|---------|
| **SRAM** | 0x00000000 | 1 MB | Vector table, stack, boot code |
| **TCM (I/D)** | 0x0C000000 | 256 KB | Tightly-coupled instruction/data cache |
| **Code Flash** | 0x20000000 | 8 MB | NuttX kernel + PX4 code |
| **Shared DRAM** | 0x40000000 | 2 MB | IPC buffers, CR8-1/CM33 firmware |
| **Peripheral I/O** | 0x41000000+ | various | GIC, ICU, GPIO, UART, SPI, I2C, DMA, etc. |

---

## 6. IPC Message Flow

**Scenario: CR8-0 sends PWM setpoint to CR8-1**

```
CR8-0 (PX4 motor_control app)
  │
  └─> uorb_bridge_send(motor_cmd_t msg)
      │
      ├─> frame: [msg_id=0x0042 | seq=42 | len=32 | payload | crc]
      │
      └─> sharedmem_transport::write() via /dev/ipcc0
          │
          └─> NuttX IPCC driver reads from shared DRAM ring buffer
              │
              └─> Signals CR8-1 via MHU doorbell interrupt
                  │
                  CR8-1 (px4io bridge)
                  │
                  └─> Handler: rx_message_from_cr8_0()
                      │
                      ├─> Parse frame, validate CRC & seq_num
                      │
                      └─> GPIO/GPT PWM register update
                          │
                          └─> Motor ESC PWM pulse output
```

---

## 7. Device Tree & Linker Scripts

**Linker Scripts** (in NuttX submodule):
- `boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld` — CR8-0 text/data/bss layout
- `boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_1.ld` — CR8-1 firmware placement (DRAM)

**PX4 Linker Integration:**
- `boards/renesas/rdk-rzv2h/nuttx-config/scripts/script.ld` — overlay for IPC regions

---

## 8. Related Documentation

- **Project Overview:** [project-overview-pdr.md](./project-overview-pdr.md)
- **Codebase Summary:** [codebase-summary.md](./codebase-summary.md)
- **Hardware Details:** [renesas/hardware.md](./renesas/hardware.md)
- **Pinmap:** [renesas/pinmap.md](./renesas/pinmap.md)
- **IPC Architecture (detailed):** [renesas/ipc-architecture.md](./renesas/ipc-architecture.md) (Phase 3)
- **Canonical Plan:** [plans/rzv2h_nuttx_px4_unified_port_plan.md](../plans/rzv2h_nuttx_px4_unified_port_plan.md)

---

## Notes

- Single-core (CR8-0 only) is production stable; dual-core IPC experimental.
- Linker scripts must reserve DRAM for CR8-1 firmware even if CR8-1 unused.
- IPCC driver handles message queuing; IPCC does not guarantee order on loss.
- CRC16 polynomial: 0x1021 (standard CCITT).
