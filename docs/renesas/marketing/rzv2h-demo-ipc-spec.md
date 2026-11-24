---
title: "RZ/V2H demo: Inter-core communication"
version: 1.0
date: 2026-10-21
status: Approved target contract; software subset delivered, full qualification pending
registry: rzv2h-demo-requirements.md
---

# Inter-core communication

## Purpose and authority

This module owns **Single writer per direction; CR8-0 recovery initiator** for the exact-BOM two-CR8 demo. The user approved this boundary and the [umbrella registry](./rzv2h-demo-requirements.md) on 2026-10-21. Existing parent requirements remain unchanged: SW-IPC-001/002/003; SYS-ARC-003/004. The registry owns allocation; the requirement rows below are synchronized module views, not an independent allocation authority.

Revision 1.0 records the approved target design. “Verified” in requirement evidence means the target contract is documented in the approved design, not that firmware implements it. Every implementation/physical test gap below remains open. Current staging behavior is a migration reference. A55/cameras/CM33 are outside demo runtime. Props-off qualification retains full product-service requirements.

## Module ownership

| Path | Classification | Owner | Notes |
|---|---|---|---|
| [protocol.hpp](../../../src/apps/protocol.hpp) / [protocol.cpp](../../../src/apps/protocol.cpp) | product-owned | Single writer per direction; CR8-0 recovery initiator | Canonical application codec implementation (`WireHeader`, wire codec, CRC32, little-endian framing, static assertions) |
| [raw-link.hpp](../../../src/apps/raw-link.hpp) | product-owned | Single writer per direction; CR8-0 recovery initiator | POSIX `/dev/ipcc1` wrapper (`RawLink`); nonblocking reads, potentially blocking write/RECOVER in transport tasks |
| [protocol.h](../../../boards/renesas/rdk-rzv2h/rzv2h_outputs/protocol.h) | product-owned | Single writer per direction; CR8-0 recovery initiator | CR8-0 board protocol header including `src/apps/protocol.hpp` |
| [protocol.h](../../../boards/renesas/rdk-rzv2h-io-cr8_1/rzv2h_io/protocol.h) | peer/host | Single writer per direction; CR8-0 recovery initiator | CR8-1 board protocol header including `src/apps/protocol.hpp` |
| [protocol.h](../../../boards/renesas/rdk-rzv2h-io-cm33/px4io_m33/protocol.h) | legacy/reference | Single writer per direction; CR8-0 recovery initiator | Legacy mirror only; no demo runtime |
| [rzv_ipc_channels.h](../../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_channels.h) | product-owned | Single writer per direction; CR8-0 recovery initiator | Raw transport shared-memory/channel authority |

Behavioral slices in a shared bridge file do not grant simultaneous write ownership. IPC owns codec/epoch handling, flight control owns producer/readiness consumption, battery owns sample semantics, and actuator safety owns lease/worker inhibition. Integrate those edits sequentially; mirrors have no independent schema authority.

## Interfaces and behavior

The following is the approved target contract with explicit hardware gaps. Exact layouts and block/data-flow/state/sequence diagrams remain in the [engineering design](./rzv2h-dualcr8-demo-design.md); the [architecture](./rzv2h-dualcr8-demo-architecture.md) explains system boundaries without duplicating normative authority.

**Figure 1: Dual-CR8 inter-core communication architecture and shared memory layout**

```mermaid
flowchart LR
    subgraph FC["CR8-0 local state"]
        Producer["PWM_MAIN producer and sender task"]
        Receiver0["Status and battery receiver"]
        Recovery["Sole raw recovery initiator"]
    end
    subgraph DDR["Shared DDR carveout: 0x43800000, 64 KiB"]
        Ring01["0 to 1: low 32 KiB<br/>16 slots, 128 bytes per physical slot<br/>64-byte metadata + 64-byte public payload"]
        Ring10["1 to 0: high 32 KiB<br/>16 slots with the same layout"]
    end
    MHU["MHU MMIO doorbells<br/>CR8-0 TX ch4, CR8-1 TX ch9"]
    subgraph IO["CR8-1 local state"]
        Receiver1["Parser and actuator lease"]
        Tokens["Local token history<br/>20 ms candidate cadence, 50 ms lifetime"]
        Reporter["Status reporter and token publication"]
        Receiver1 --- Tokens
        Tokens --> Reporter
    end
    Producer --> Ring01 --> Receiver1
    Reporter --> Ring10 --> Receiver0
    Producer -.-> MHU
    Reporter -.-> MHU
    MHU -.-> Receiver0
    MHU -.-> Receiver1
    Recovery -.-> DDR
```

| Interface | Direction | Contract / limit |
|---|---|---|
| Raw transport | CR8-0 ↔ CR8-1 | /dev/ipcc1; raw ABI v2; [channel/layout authority](../../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_channels.h); stop-and-wait writes may block 100 ms |
| Application codec | Legacy v2 / demo v3 | Separate layouts; implemented v3 sizes/assertions owned by [protocol.hpp](../../../src/apps/protocol.hpp) |
| Commands and recovery | CR8-0 → CR8-1 | Compatible role/current epoch, coherent snapshot and receiver token |
| Status/power | CR8-1 → CR8-0 | Implemented codecs/receivers; physical battery acquisition remains pending; no v3 RC acquisition stream |

### State and fault transitions

These are target integration states, not claims that enums or handlers already exist.

**Figure 2: IPC link session and epoch recovery state machine**

```mermaid
stateDiagram-v2
    [*] --> No_Session : Power-On / Core Reset

    No_Session --> Negotiating : Raw shared memory epoch established
    note right of Negotiating : Shared memory rings zeroed - no actuator output claimed

    Negotiating --> Compatible : Compatible current-epoch role & resource hello exchanged
    note right of Compatible : Valid session active - enable safe bootstrap and command exchange

    Compatible --> Recovering : Transport fault / Epoch mismatch / CR8-1 rotation request
    note right of Recovering : Output authority revoked - CR8-0 sole recovery initiator

    Recovering --> Negotiating : New epoch observed & buffers flushed
    note right of Negotiating : Fresh handshake required before re-enabling outputs
```

| From | Event / guard | To | Action / recovery constraint |
|---|---|---|---|
| No session | Raw epoch established | Negotiating | No output claim |
| Negotiating | Compatible current-epoch role/resource hello | Compatible | Enable safe bootstrap exchange |
| Compatible | Transport fault/epoch change | Recovering | Invalidate prior command authority |
| Compatible | Pre-wrap sticky rotation request | Recovering | CR8-0 alone initiates RECOVER |
| Recovering | New epoch observed | Negotiating | Fresh role and disarmed handshake |

**Figure 3: Bidirectional IPC message exchange and causal freshness token sequence**

```mermaid
sequenceDiagram
    participant FC as CR8-0 sender and receiver
    participant DDR as Shared DDR rings
    participant MHU as MHU notification
    participant IO as CR8-1 control and reporter
    Note over FC,IO: After compatible hello, backend initialization and fresh disarmed handshake
    IO->>DDR: Publish status with receiver-issued token
    IO->>MHU: Notify CR8-0
    MHU-->>FC: Wake receiver to validate status and extract token
    FC->>FC: Commit new coherent snapshot after token receipt
    Note over FC,IO: CRC-checked, token-bound actuator command
    FC->>DDR: Copy exactly 64 public bytes with current epoch and sequence
    FC->>MHU: Notify CR8-1
    MHU-->>IO: Wake receiver for bounded read and validation
    IO->>IO: Age old authority, then validate token history and command
    IO->>IO: Worker applies only while all output gates remain valid
    Note over FC,IO: A rejected expired or replayed record does not renew authority
    FC->>DDR: Delayed command with expired token
    DDR-->>IO: Read delayed record
    IO->>IO: Reject record, prior valid authority keeps only its existing deadline
```

### Configuration and persistence

| Parameter / contract | Selected value / gap | Owner / persistence boundary |
|---|---|---|
| Entry limit | 64 bytes | Raw transport contract |
| Command lease / heartbeat | 50 ms / 500 ms | Existing thresholds retained |
| Token issuance / lifetime / history | 20 ms candidate / 50 ms / at most 3 | Load qualification pending; events reuse existing token |
| Status expiry | 50 ms proposed receive-local | Advancing valid status required; heartbeat cannot renew |
| Compatibility identities | Phase 1 machine-owned profile catalog | Different authority from requirements registry |

## Requirements registry

| ID | Requirement | Evidence | Confidence |
|---|---|---|---|
| SDS-IPC-001 | The demo codec shall keep each raw entry within 64 bytes. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-002 | The receiver shall reject frames failing the selected codec contract. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-003 | The sender shall bind authority to a snapshot created after token receipt. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-004 | The receiver shall age existing authority before accepting queued commands. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-005 | CR8-0 shall remain the sole raw recovery initiator. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-006 | Event status shall reuse the current freshness-token issue time. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-007 | An epoch change shall invalidate prior command generations. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |
| SDS-IPC-008 | Non-actuator traffic shall leave actuator authority unchanged. | [Approved target design](./rzv2h-dualcr8-demo-design.md#4-proposed-demo-wire-contract-and-freshness-proof) | verified |

## Verification matrix

The methods below define required future proof. Existing source/reference coverage in the evidence ledger is partial and does not close a new-pair test.

| ID | Method | Level | Pass criterion | Existing test/gap | Code-review criterion |
|---|---|---|---|---|---|
| SDS-IPC-001 | analysis + test | integration/system | Static sizes/offsets and every serialized record fit the public entry. | gap: full integration and physical acceptance evidence pending | Separate v2/v3 headers and all consumer layouts |
| SDS-IPC-002 | analysis + test | integration/system | Malformed magic/version/type/length/CRC/reserved/state fields do not dispatch or renew authority. | gap: full integration and physical acceptance evidence pending | Boundary validation before state mutation |
| SDS-IPC-003 | analysis + test | integration/system | Delayed-token replay and cached-control replay cannot extend an armed lease. | gap: full integration and physical acceptance evidence pending | Causal token and control-generation provenance |
| SDS-IPC-004 | analysis + test | integration/system | Queued armed command after expiry cannot bypass fresh disarmed recovery. | gap: full integration and physical acceptance evidence pending | Pre-receipt expiry ordering |
| SDS-IPC-005 | analysis + test | integration/system | CR8-1 requests rotation without issuing initiator-only recovery operations. | gap: full integration and physical acceptance evidence pending | Epoch ownership and sticky request acknowledgement |
| SDS-IPC-006 | analysis + test | integration/system | Bursty status cannot evict a live token early or refresh its lifetime. | gap: full integration and physical acceptance evidence pending | Bounded token issuance/history |
| SDS-IPC-007 | analysis + test | integration/system | Old snapshot/token/sequence cannot reactivate outputs in a new session. | gap: full integration and physical acceptance evidence pending | Session reset and tracker initialization |
| SDS-IPC-008 | analysis + test | integration/system | Battery, RC and diagnostic traffic cannot extend command lease or mask stale backend status. | gap: full integration and physical acceptance evidence pending | Per-stream sequencing, expiry and bounded queues |

## Traceability

| ID | Design or behavior trace | Test trace | Review trace |
|---|---|---|---|
| SDS-IPC-001 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-002 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-003 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-004 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-005 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-006 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-007 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |
| SDS-IPC-008 | [Interfaces and behavior](#interfaces-and-behavior) | [Verification matrix](#verification-matrix) | [Review criteria](#review-criteria) |

## Review criteria

Review each verification-row boundary against the actual selected profile and source change. Reject double ownership, stale data promoted to fresh authority, implicit hardware selection, cross-clock subtraction and promotion of a build/ACK into physical proof. Resolve each test gap with a named artifact before claiming its requirement passed. A hardware-dependent record stays blocked until its ICD is frozen; independent source work remains possible.

## Evidence ledger

| Claim / requirement | Evidence location | Confidence | Status / gap |
|---|---|---|---|
| Approved module requirements | [Engineering design](./rzv2h-dualcr8-demo-design.md) | verified | Target design authority only |
| Current migration and implementation boundaries | [protocol.h](../../../boards/renesas/rdk-rzv2h/rzv2h_outputs/protocol.h) | verified | Source location exists; no integrated new-pair result |
| Related source/test evidence | [Subsystem evidence](../../../plans/reports/research-261021-0230-product-subsystems.md) | verified | Historical source review; rerun affected tests during implementation |
| Full module acceptance | [Verification matrix](#verification-matrix) | unknown | Required test/physical results pending |

V3 codec, causal-token lease, epoch recovery and worker software coverage is recorded in the [software validation receipt](../evidence/dualcr8-software-validation-261021.md). The [legacy lease fixture](../../../test/rzv2h-dual-cr8-output-lease-runtime-test.py) remains a separate regression owner; current-image transport/load/cache and physical qualification remain open.

## Open inputs and acceptance gaps

V3 codecs and causal-token software are implemented and host-tested. Hardware identities remain unconfigured, no actuator pair is admitted, and full-load/physical timing remains unqualified. Receiver-issued tokens establish causality, not cryptographic authentication. Authentication requirements remain in the product release owner.

The [shared hardware-input ledger](./rzv2h-demo-requirements.md#hardware-input-gates) names closure evidence. Unknown hardware remains an input gate rather than a substituted part number or a waived requirement.
