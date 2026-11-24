# R-Car V4H CR52 IPC: OpenAMP and ICCOM

There are two IPC paths for the Sparrow Hawk CR52 NuttX images. They
follow the RZ/V2H layering in
[`../ipc-architecture.md`](../ipc-architecture.md): a doorbell underneath,
the transport on top, and a character device for applications.

| Path | Peers | Transport | Doorbell | Device | Status |
|---|---|---|---|---|---|
| OpenAMP | CR52-0 ↔ CR52-1 | NuttX `rptun`/RPMsg, shared window `0x40A00000` | GICv3 SGI 8, plus a poll | `/dev/ipcc0`, `rptun ping` | build-clean |
| ICCOM | CR52-0 ↔ CA76 Linux | ICCOM channel 0, MFIS mailbox + CTA | MFIS interrupt (off by default) or poll | `/dev/iccom0` | build-clean, host-simulated |

Nothing here has run on a board. The board steps are listed under
[Not yet proven](#not-yet-proven).

## Configs

| Config | Core | Adds |
|---|---|---|
| `openamp` | CR52-0 | RPTUN master `cr52-0`, `/dev/ipcc0`, `rptun ping` |
| `openamp-cr52_1` | CR52-1 | RPTUN remote `cr52-1`, `/dev/ipcc0`, `rptun ping` |
| `iccom` | CR52-0 | `/dev/iccom0` (ICCOM channel 0) |

Build them with `platforms/nuttx/NuttX/build_rcarv4h.sh <config>`.
OpenAMP needs both images: load `openamp` on CR52-0 and `openamp-cr52_1`
on CR52-1.

Kconfig lives in the `R-Car OpenAMP/ICCOM` menu of
`arch/arm/src/rcar/Kconfig`:

| Option | Default | Meaning |
|---|---|---|
| `RCAR_OPENAMP` | n | RPTUN lower half; selects `OPENAMP`, `RPTUN` and `SCHED_LPWORK` |
| `RCAR_OPENAMP_POLL_MS` | 10 | Period of the fallback doorbell poll (0 turns it off) |
| `RCAR_OPENAMP_ATTACH_TIMEOUT_MS` | 5000 | How long CR52-1 waits for CR52-0 |
| `RCAR_OPENAMP_IPCC` | n | `/dev/ipcc0`; needs `EXPERIMENTAL` (NuttX IPCC upper half) |
| `RCAR_ICCOM` | n | `/dev/iccom0`; CR52-0 only, needs `EXPERIMENTAL` |
| `RCAR_ICCOM_IRQ` | 0 | Incoming mailbox GIC INTID; 0 = poll only |
| `RCAR_ICCOM_SERVICE_MS` | 10 | Period of the ICCOM service and poll work |
| `RCAR_ICCOM_ACK_TIMEOUT_MS` | 100 | How long a send waits for its ACK |

## Memory

Both regions are mapped Normal non-cacheable in the EL1 MPU
(`rcar_mpu_regions.c`), so ordering needs barriers only and never cache
maintenance.

| Region | Range | Mapped on |
|---|---|---|
| OpenAMP shared window | `0x40A00000`–`0x40AFFFFF` | Both CR52 images |
| ICCOM CTA, channel 0 | `0x47FC7000`–`0x47FCEFFF` | CR52-0 with `RCAR_ICCOM` |

Neither region overlaps an image window, including the free CR52-2 window
(`0x40700000`–`0x409FFFFF`). The allowlist manifest does not cover them,
so the build window check rejects any ELF segment placed there.

### Shared-window layout

`arch/arm/src/rcar/rcar_ipc_shm.h` owns the layout. Its `static_assert`s
and `test/rcarv4h-cr52-ipc-shm-layout-test.py` hold it in place.

| Offset | Size | Content |
|---|---|---|
| `+0x00000` | 4 KiB | Control record |
| `+0x01000` | 4 KiB | Resource table (one RPMsg vdev, two vrings) |
| `+0x02000` | `0x3000` | VRING0, host → remote |
| `+0x05000` | `0x3000` | VRING1, remote → host |
| `+0x08000` | `0x40000` | RPMsg buffer pool, 2 × 256 × 512 B |
| `+0x48000` | — | Unused to the end of the window |

The geometry is 256 buffers per direction, 512-byte buffers (496-byte
payload) and a vring alignment of `0x1000`.

The host writes the vrings with `da = 0`. NuttX `rptun` then places them
straight after the table and the pool straight after the vrings. The
offsets above are exactly that placement.

### Control record

```c
struct rcar_ipc_ctrl_s
{
  uint32_t magic;       /* 0x50494352 "RCIP" once the host is ready */
  uint32_t version;     /* 1 */
  uint32_t host_epoch;  /* new on every host start, never 0 */
  uint32_t reserved;
  uint32_t mpidr[2];    /* runtime MPIDR of CR52-0, CR52-1 */
  uint32_t ready[2];    /* epoch each core attached to, 0 = none */
};
```

The host writes every field and writes `magic` last. The remote reads
`magic` first and writes only its own slots.

## OpenAMP

### Start handshake

1. **CR52-0 (host) prepares the window.**
   - It clears `magic` and zeroes the used area (`+0` to `+0x48000`).
   - It fills the resource table and writes `version`, `mpidr[0]` and a
     new `host_epoch`.
   - It registers RPTUN.
2. **RPTUN places the rings.** It sets up the vrings and the pool, then
   calls the `start` op. Only that op writes `magic`, so CR52-1 never
   reads a half-built table.
3. **CR52-1 (remote) attaches.**
   - A work item polls `magic`, `version` and `host_epoch` for up to
     `RCAR_OPENAMP_ATTACH_TIMEOUT_MS`. NSH comes up either way.
   - On a match it writes `mpidr[1]` and then `ready[1] = host_epoch`.
   - It then registers RPTUN.
4. **The host sees the remote.** Until `ready[1]` equals its epoch, the
   host's notify only records a pending kick; the data already sits in the
   rings. The next notify or fallback poll after the attach reads
   `mpidr[1]` and sends the SGI. With `RCAR_OPENAMP_POLL_MS = 0`, only the
   next notify delivers it.

Start order does not matter, as long as CR52-0 starts within the attach
timeout. On a timeout, CR52-1 logs `rcar_openamp: no host after … ms` and
runs without RPMsg.

### Doorbell

- **Send:** notify is a DSB followed by Group 1 SGI 8
  (`RCAR_IRQ_IPC_SGI`) to the MPIDR the peer published in the control
  record. There is no hard-coded affinity: the SDK notes disagree on the
  CR52 MPIDR values.
- **Receive:** the SGI handler calls the RPTUN callback.
- **Fallback poll:** an LPWORK item calls the same callback every
  `RCAR_OPENAMP_POLL_MS`, so a lost SGI costs latency, not data.

### Restart limit

Restarting one core alone is not supported; restart both. The host takes
a new `host_epoch` on every RPTUN start, so both a CR52-0 reset and an
`rptun stop`/`start` on CR52-0 change it. CR52-1's fallback poll detects
the change (so not with `RCAR_OPENAMP_POLL_MS = 0`) and then:

- logs `host epoch … gone, rings stopped; restart both cores`;
- sets a stale flag that stops its poll;
- makes every notify return `-ECONNRESET`;
- makes `/dev/ipcc0` sends fail with `-ECONNRESET`, and skips returning
  received buffers.

It never touches the rings again. Between the host restart and the next
CR52-1 poll (`RCAR_OPENAMP_POLL_MS`), CR52-1 can still write to the new
rings; this short window is why a one-core restart is unsupported.

### `/dev/ipcc0` and `rptun ping`

- **`/dev/ipcc0`** is the NuttX IPCC upper half (buffered) on the
  `rcar-ipcc` RPMsg endpoint. It carries a byte stream:
  - Writes are sent in packets of up to 496 bytes.
  - A write is queued while the ring is full or the peer has not bound
    the endpoint yet; an LPWORK retry sends it later. OpenAMP's own
    `RPMSG_ERR_*` codes never reach `write()`: they become `-EAGAIN`
    (queued) or `-EIO`.
  - A received packet stays in its RPMsg buffer until it is read. A slow
    reader therefore runs the sender out of buffers (back-pressure); data
    is never dropped. The 256 receive slots match the 256 buffers the
    peer can have in flight.
  - A packet that the reader drains before its receive callback returns
    is not held: OpenAMP returns it when the callback ends. Every other
    packet is held, and the reader returns it. A buffer that goes back
    twice would corrupt the peer's free list. After a return outside the
    callback, the driver kicks the peer, because OpenAMP does not, and
    a sender waiting for a free buffer would otherwise sleep until the
    next doorbell.
  - The IPCC overflow flag only means the upper half's RX buffer is full;
    the remaining packets wait in their RPMsg buffers.
- **`rptun ping`** (`CONFIG_RPTUN_PING`) runs from NSH on either core.
  The device names are `cr52-0` and `cr52-1`.

## ICCOM

ICCOM is the Renesas CR52 ↔ CA76 Linux message channel. This driver is a
clean-room implementation: no Renesas CDD code is used.

It offers only CR52-0 channel 0, because the CR52-1 channel facts are not
sourced yet. No CA76 peer exists in this port, since Linux does not run
alongside. Everything below is therefore build-clean and host-simulated.

### Registers and CTA (channel 0)

| Item | Address |
|---|---|
| Incoming control / message (CA76 → CR52-0, "x") | `0xE6261400` / `0xE6261440` |
| Outgoing control / message (CR52-0 → CA76, "y") | `0xE6269404` / `0xE6269460` |
| CTA RX upper / bottom | `0x47FC7000` / `0x47FC7800` |
| CTA TX upper / bottom | `0x47FC8000` / `0x47FC8800` |

Each CTA slot is 2 KiB, and a message holds 1–2048 bytes.

### Wire words

| Bit | Name |
|---|---|
| `0x01` | INT, the doorbell bit |
| `0x02` | DATA |
| `0x04` | DBOT, which marks the bottom slot |
| `0x08` | ABOT, an ACK of the bottom slot |
| `0x10` | INITEND |
| `0x20` | FATAL |

| Word | Control | Message register |
|---|---|---|
| Data, upper slot | `0x03` | Length |
| Data, bottom slot | `0x07` | Length |
| ACK, upper slot | `0x01` | — |
| ACK, bottom slot | `0x09` | — |
| INITEND | `0x11` | — |

### Engine

`rcar_iccom_proto.c` is plain C11 behind an ops table. It has no NuttX
include, so the host test compiles it unchanged.

**Incoming words:**
- The engine reads the control register, then the message register, then
  clears INT in the control register.

**Outgoing words:**
- There is a single outgoing register, so the engine posts at most one
  word per pump. Priority order: INITEND, then ACKs, then data.
- A word is posted only when INT in the outgoing control register is
  clear, which means the peer has taken the previous word.

**Receive:**
- A message stays in its CTA slot until `read()` copies it out. The ACK
  goes out after the copy, which gives flow control.
- When a data word names a slot that is still held, the engine counts a
  bad message and does not ACK.
- A length of 0 or more than 2048, or data before the link is up, is
  counted as bad and ACKed, so the peer is not stuck.

**Send:**
- Sends alternate between the upper and bottom slots, so a late ACK can
  never match the next send.
- A slot that was posted but not ACKed is never reused: the peer may still
  be reading it. After two timeouts in a row with no late ACK, `send`
  fails at once with `-ETIMEDOUT` until an ACK or a new INITEND frees a
  slot.
- One deadline covers both the wait for the outgoing register and the
  wait for the ACK.
- An ACK for the wrong slot, or one arriving after a timeout, is dropped
  and counted.

**Peer state:**
- **FATAL** returns the link to wait-for-INITEND. It drops held messages
  and pending ACKs, and fails an active send with `-ECONNRESET`.
- **INITEND while waiting** brings the link up. If a FATAL came first,
  the engine answers with its own INITEND.
- **A repeated INITEND while up** resets the link state without
  answering, so two engines cannot ping-pong INITENDs.

**Glue (`rcar_iccom.c`):**
- Every engine call runs in thread context under one mutex.
- With `RCAR_ICCOM_IRQ` set, the interrupt masks itself and queues HPWORK.
  The worker handles the word and then unmasks the interrupt.
- An LPWORK item runs every `RCAR_ICCOM_SERVICE_MS`. It expires sends,
  retries a busy outgoing register, and polls the mailbox when there is no
  interrupt.
- Barriers are full-system DSBs, because the CA76 sits outside the CR52
  inner-shareable domain.

### `/dev/iccom0`

Each `read()` or `write()` call carries exactly one message.

| Call | Behaviour |
|---|---|
| `write` | Sends 1–2048 bytes and blocks until the ACK arrives. Errors: `-EINVAL` (bad length), `-ENOTCONN` (no INITEND yet), `-ECONNRESET` (after FATAL), `-ETIMEDOUT`. Writers are serialised. A signal (`-EINTR`) after the word is posted does not cancel the message: it may still be delivered, so a retry can duplicate it. |
| `read` | Returns one message. `-EMSGSIZE` if the buffer is too small; the message stays queued. Blocks unless `O_NONBLOCK`, and also blocks while the link is down. `-ECONNRESET` after FATAL. |
| `poll` | `POLLIN` when a message is queued; `POLLOUT` when the link is up, no send is in flight and the peer has ACKed at least one slot; `POLLERR` after FATAL. Up to two waiters. A late ACK that frees a slot wakes them. |
| `ioctl(RCAR_ICCOMIOC_STATUS)` | Fills `struct rcar_iccom_status_s`: channel, send and receive state, reset flag, IRQ, last send result and counters. |

### Host test

`test/rcarv4h-cr52-iccom-protocol-test.py` compiles the engine with
`test/rcarv4h-cr52-iccom-host-fixture.c`. The fixture simulates the
register pair, the CTA, the clock and the peer.

It covers:
- the golden words;
- INITEND in either order, including while the outgoing register is busy;
- INT cleared only after both reads;
- slot alternation;
- an ACK for the wrong slot;
- a timeout followed by a late ACK, with a deadline across the clock wrap;
- a timeout while the outgoing register stays busy;
- two timeouts in a row: no unACKed slot is reused, and late ACKs free
  only their own slot;
- lengths of 0, 2049 and `0x10000`;
- both RX slots held, then `-EMSGSIZE`;
- a deferred ACK;
- FATAL followed by recovery;
- a repeated INITEND;
- data before INITEND.

## Departures from the plan

| Plan | Built | Why |
|---|---|---|
| The SGI ISR queues HPWORK, and the worker calls the RPTUN callback | The ISR calls the callback directly | `rptun_callback` only posts a semaphore or queues work, so it is interrupt-safe; one hop less. |
| The host bumps the epoch stored in the window | `arm_timer_count() >> 8`, forced non-zero | Old window content may not hold valid ECC after reset, so it is never read. |
| The remote stops the rptun device on a stale epoch | Stale flag: notify returns `-ECONNRESET` and the poll stops | Avoids tearing RPTUN down from its own callback path. |
| `rcar_mfis.c/.h` accessors | Static ops in `rcar_iccom.c` plus `hardware/rcar_mfis.h` | Only one user. |
| ICCOM IRQ 156 | `RCAR_ICCOM_IRQ`, default 0 (poll) | Unverified whether 156 is an INTID or an SPI number (INTID 188). |
| `RCAR_ICCOM_CH0` option | Not added | Only channel 0 exists. |
| `RCAR_ICCOM` | Also depends on `EXPERIMENTAL` | No peer has run against it. |
| `RCAR_RPMSG_RX_QUEUE_DEPTH` copy queue | Removed; received RPMsg buffers are held until read | A full copy queue had to drop packets (OpenAMP asserts on a negative callback status). |

## Not yet proven

| Item | Needs |
|---|---|
| OpenAMP attach, both start orders, `rptun ping`, `/dev/ipcc0` echo | Board run of `openamp` + `openamp-cr52_1` |
| SGI delivery between the CR52 cores (MPIDR, Group 1 routing) | Board run; poll-only latency as a comparison |
| Both CR52 cores share one inner-shareable domain (the doorbell uses `dsb ishst`; the window is non-cacheable) | Board run; otherwise a full-system `dsb` before the SGI |
| The CTA accepts byte and unaligned CR52 accesses | CA76 peer or the SoC manual |
| Behaviour after a one-core restart | Board run (expected: stale message, `-ECONNRESET` on notify and on `/dev/ipcc0` writes) |
| ICCOM against a real CA76 | Linux on the CA76 with the ICCOM driver |
| MFIS direction (which register pair is incoming) | CA76 peer or a Renesas confirmation; the SDK journal and the CDD disagree, and this driver follows the CDD wire table |
| Mailbox interrupt number | Confirm 156 vs INTID 188 |
| Whether the CA76 clears INT in the outgoing control register | CA76 peer |
| CR52-1 ICCOM channel | Sourced register and CTA facts |
