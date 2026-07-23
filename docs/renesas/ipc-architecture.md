# RZ/V2H IPC Architecture

**Date:** 2026-07-11  
**Current as of:** Commit 289f3203ec6 ("Refactor IPC communication for CR8-0 and CR8-1 using NuttX IPCC")  
**Branch:** px4_ra_rzv

---

## 1. Core Topology

### System Partition

| Core | RTOS | Role | Private DDR (CR8/CM33 view) | Boot Vector |
|------|------|------|--------------|-------------|
| **CR8-0** | NuttX | Flight stack (PX4) | 0x40800000–0x41800000 (SRAM$ 0x08180000; TCM local 0x0) | ITCM local 0x0 (reset) |
| **CR8-1** | NuttX | IO co-processor | 0x41800000–0x42800000 (SRAM$ 0x081C0000; TCM local 0x0) | ITCM local 0x0 (reset) |
| **CM33** | NuttX | IO co-proc / boot mgr | code SRAM 0x08002800 (CM33-S); DDR-S 0x80000000 | BOOTPARAM 0x08001E00 (ROM) |

> Authoritative addresses: see [multicore-memory-map.md](./multicore-memory-map.md). The prior
> 0x40000000 / 0x40100000 rows were placeholders and did not match linker/HWM truth.

### IPC Transport

- **Mechanism:** NuttX IPCC (Inter-Processor Communication Controller) character device.
- **Hardware:** MHU (Message Handling Unit) with register-based doorbell + response channels.
- **Protocol:** RPMsg framing over MHU; uORB bridge message serialization.

---

## 2. MHU Channel Mapping

### Hardware Channels (from `rzv_mhu_core.c` and `hardware/rzv_mhu.h`)

**MHU Register Layout:**
- Base address: 0x82B00000 (system MHU) + per-channel offsets.
- Per channel: MSG_SET (doorbell send), MSG_STAT (status), RSP_SET (response), RSP_STAT (response status).
- DSB (Data Synchronization Barrier) required before/after register writes.

**Channel Allocation:**

| Channel | Direction | Source → Dest | Purpose | Driver |
|---------|-----------|----------------|---------|--------|
| **0** | CR8-0 → CR8-1 | Primary → IO co-proc | Flight commands (armed, throttle) | rzv_rproc.c / rzv_rpmsg.c |
| **1** | CR8-1 → CR8-0 | IO co-proc → Primary | Sensor telemetry (IMU, GPS) | rzv_rpmsg.c |
| **2** | CR8-0 → CM33 | Primary → CM33 | (Alternative path if CR8-1 absent) | rzv_rproc.c (TBD) |
| **3** | CM33 → CR8-0 | CM33 → Primary | (Alternative telemetry) | (TBD) |

**Doorbell Register Access:**

```c
/* Send interrupt to peer on channel N */
rzv_mhu_send(base, channel, 0x1);  /* DSB + write to MSG_SET */

/* Acknowledge response on channel N */
rzv_mhu_ack(base, channel, 0x1);   /* DSB + write to RSP_SET */

/* Clear received message on channel N */
rzv_mhu_clear(base, channel);      /* DSB after clear */
```

---

## 3. NuttX IPCC Character Device Layout

### Device File Registration

**Configuration:** `CONFIG_RZV_IPC_IPCC` in Kconfig.

**Driver:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_ipcc.c`

**Device Semantics:**

```bash
/dev/ipcc0          # CR8-0 ↔ CR8-1 link
/dev/ipcc1          # (future) CR8-0 ↔ CM33 link
```

**Character Device Operations:**

| Operation | Semantics | Returns |
|-----------|-----------|---------|
| **open()** | Register RX callback; enable MHU IRQ | File descriptor (≥0) |
| **read()** | Blocking receive from IPCC RX buffer | Bytes read; -EINTR on signal |
| **write()** | Send frame via IPCC TX (RPMsg endpoint) | Bytes written; -EAGAIN if buffer full |
| **poll()** | Wait for IPCC RX ready (pollin) | Poll event mask |
| **close()** | Unregister callback; disable IRQ | 0 on success |

**Buffer Configuration (compile-time):**

```c
CONFIG_RZV_IPCC_RXBUFSIZE = 2048  /* RX circular buffer */
CONFIG_RZV_IPCC_TXBUFSIZE = 2048  /* TX circular buffer */
```

**Upper-half Driver:** `nuttx/drivers/ipcc/` (generic, registered via `ipcc_register()`).

---

## 4. uORB Bridge Framing

### Frame Structure

**Location:** `boards/renesas/rdk-rzv2h/px4io_cr8_0/px4io_bridge.cpp`

**Serialization Format:**

```
+--------+--------+--------+--------+--------+--------+--------+...+--------+
| Magic  | Seq    | Len    | Topic  | Payload[0..N-1]           | CRC16  |
| (0xAA) | (u16)  | (u16)  | (u16)  |                           | (u16)  |
| 1 byte | 2 byte | 2 byte | 2 byte | Len bytes                 | 2 byte |
+--------+--------+--------+--------+--------+--------+--------+...+--------+
```

**Field Definitions:**

| Field | Size | Purpose |
|-------|------|---------|
| Magic | 1 byte | Sync marker (0xAA); detects frame boundary corruption. |
| Seq | 2 bytes | Sequence number (0x0000–0xFFFF); wraps; detects drops/reordering. |
| Len | 2 bytes | Payload size in bytes (0–2048 typical). |
| Topic | 2 bytes | uORB topic ID (e.g., ORB_ID(sensor_accel) = 0x1234). |
| Payload | Var | Serialized message (e.g., struct accel_s). |
| CRC16 | 2 bytes | CCITT CRC-16 (poly 0x1021) over Magic–Payload. |

**CRC16 Calculation:**

```c
uint16_t crc16_ccitt(const uint8_t *buf, size_t len);
/* Polynomial: 0x1021, init 0xFFFF, no final XOR */
```

---

## 5. Error / Recovery Paths

### Sequence Number Mismatch

**Scenario:** `Seq_new > Seq_last + 1` (gap detected).

**Recovery:**
1. Log warning: `"IPC seq gap: expected N, got M"`.
2. Update `Seq_last = Seq_new`.
3. Continue processing (messages may have been dropped in flight; no resync available in current implementation).

**Future Mitigation:** NAK or retransmit handshake on large gaps.

---

### CRC Failure

**Scenario:** Computed CRC ≠ received CRC16.

**Recovery:**
1. Log error: `"IPC CRC fail; frame dropped"`.
2. Discard frame; do NOT update Seq_last.
3. Continue scanning for next Magic (0xAA) in stream.

**Root Cause Diagnosis:**
- Check MHU channel enable (ISR context).
- Verify DMAC (if used) alignment and cache coherency.
- Inspect baud rate / timing on UART fallback paths.

---

### Timeout / Stall

**Scenario:** No RX for >100 ms; application polls /dev/ipcc0.

**Detection:** Application-level watchdog (e.g., PX4 failsafe manager).

**Recovery:**
1. Log alert: `"IPC timeout"`.
2. Trigger remote core reboot (via WDT or manual reset via ICU).
3. Reinitialize IPCC character device (close/open cycle).

---

### Mutual Resync (Future)

If CR8-0 and CR8-1 become out-of-sync (e.g., CR8-1 crashes):

1. CR8-0 sends **SYNC** marker (magic 0xBB) with timestamp.
2. CR8-1 upon re-boot sends **SYNC_ACK**.
3. Both reset Seq counters to 0.
4. Resume message exchange.

(Currently not implemented; reserved for production hardening.)

---

## 6. OpenAMP / RPMsg Integration

### Current Usage (Commit 289f3203)

**Driver Files:**
- `rzv_openamp.c` — OpenAMP platform hooks (stub; RPMsg already integrated via NuttX IPCC).
- `rzv_rpmsg.c` — RPMsg endpoint layer (sends/receives over MHU + IPCC).
- `rzv_rproc.c` — Remote processor control (load image, trigger core boot, register virtual device).

**Initialization Flow:**

```
PX4 boot (CR8-0)
  → rzv_rproc_initialize()  [register rproc device /dev/remoteproc0]
  → rproc_load(image_path)  [load CR8-1 image from /fs/microsd]
  → rproc_start()           [kick CR8-1 via MHU channel 0]
  → ipcc_register()         [register /dev/ipcc0 character device]
  → rpmsg_create_ept()      [create RPMsg endpoint; send/recv callbacks]
  → uORB bridge listen()    [wait for uORB messages on /dev/ipcc0]
```

**Message Flow (uORB → IPC → uORB):**

```
PX4 APP (CR8-0)
  → orb_publish(ORB_ID(vehicle_command))  [sensor_accel data]
  → uORB bridge task sees update
  → serialize to frame (Magic, Seq, Topic, payload, CRC16)
  → ipcc_write(/dev/ipcc0)
  → MHU ISR triggers CR8-1
  → rzv_rpmsg.c sends frame via RPMsg endpoint
  → CR8-1 receives via /dev/ipcc0
  → NuttX IPCC driver buffers frame
  → CR8-1 app reads and deserializes
  → orb_publish(ORB_ID(sensor_accel))  [now available to CR8-1 apps]
```

---

## 7. Availability & Future Paths

### For Current RDK-RZ/V2H (CR8-0 + CR8-1)

- **IPCC/MHU:** Production-ready; used by default.
- **OpenAMP:** Available but deprecated in favor of direct IPCC.
- **RPMsg:** Wrapped by IPCC for compatibility.

**Recommended for new code:** Use `/dev/ipcc0` read/write directly; no need to manage OpenAMP endpoints.

---

### For Future Linux on CA55 (Multi-OS)

- **Linux kernel:** Will use OpenAMP + RPMsg over MHU (standard ARM solution).
- **NuttX on CR8-0:** Can coexist if Linux is booted on CA55 (separate SoC region).
- **uORB bridge:** Extended to also publish to Linux via shared memory or socket (TBD).

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — IPC drivers (rzv_ipc*.c, rzv_mhu_core.c, rzv_rpmsg.c, rzv_rproc.c).
- [System Architecture](../system-architecture.md) — CR8-0/CR8-1/CM33 role definitions.
- [Validation Checklist](validation-checklist.md) — IPC-specific test cases (seq numbering, CRC, timeout).
