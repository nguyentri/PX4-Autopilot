# Firmware Audit Mission 1 — RZ/V2H ADC, Ethernet, PHY, and SCIF

**Date:** 2026-08-09  
**Target:** RDK-RZ/V2H R9A09G057H, CR8-0 NuttX  
**Scope:** active ADC_E, GBETH0/1 MAC, Ethernet PHY, and SCIFA0 lower halves plus RDK board integration  
**References:** user-supplied ADC e² studio/FSP example, GBETH bare-metal MAC/PHY example, and polling SCIF UART example  
**Mission:** audit baseline plus autonomous source remediation  
**Verdict:** **PARTIALLY REMEDIATED / BLOCKED** — 12 of 20 findings source-fixed; 8 remain open. No target behavior was validated.

## Remediation update — 2026-08-09

The finding descriptions below preserve the pre-fix audit evidence. Current source status:

| Status | Findings | Result |
|---|---|---|
| Source-fixed; automated regression proof | ADC-F01, ADC-F02, ETH-F01, ETH-F03, ETH-F06, ETH-F08, PHY-F01, SCIF-F01, SCIF-F03, SCIF-F04, SCIF-K01, SCIF-K03 | 12/20 |
| Open; behavior/sequencing needs authoritative design plus HIL | ETH-F04, ETH-F05, SCIF-F02 | 3/20 |
| Blocked by SoC/board/PHY authority and HIL | ETH-F02, ETH-F07, ETH-K01, ETH-K02, SCIF-K02 | 5/20 |

Applied changes:

- ADC writes byte-wide `ADELCCR` through `putreg8`; its live specification now records the eight-channel ADC_E, `ANIOC_TRIGGER`, selectable IRQ, and `0x11c00000` contract.
- Ethernet uses exact 16-byte DMA descriptors in existing non-cacheable SRAM. Explicit `dmb sy` barriers order descriptor ownership and tail publication. IRQ bottom-half network access now holds `net_lock()`.
- PHY resolution no longer invents 100FD and accepts valid 1000BASE-T local-master or local-slave results while rejecting master/slave fault. Bit-31 masks are unsigned.
- SCIFA preserves signed ICU results with ordered rollback, validates baud before clock/MMIO mutation, replaces formatted ISR logging with counters, uses its distinct P1CLK/clock/reset/module-stop path, and no longer makes SCIF console configuration touch SCI3 during early setup.
- SCIFA module-stop authority is the integrated CR8 FSP override (`CPG_BUS_3_MSTOP`, bit 14). The legacy CA55 reference conflicts (`BUS_7`, bit 14), so target register readback remains required.
- Ethernet admin-down cancels every queued work path; IRQ and timeout workers recheck `bifup` under `net_lock` before ring access or recovery.
- SCIF `TCSETS` configures from local candidate values and publishes persistent state only after success. Setup failure and shutdown reassert module reset before clock gating.

Verification completed:

- New source-contract suite: 16/16 passed on edited source and all 16 checks failed against archived pre-fix NuttX source.
- Broader RZ/V2H contract discovery: 85/85 passed.
- ADC Cortex-R8 syntax check passed. Isolated clean Ethernet build compiled/linked MAC and PHY, generated a 207,788-byte image, and placed configured descriptors in `.noncache_buffer`; a separate max-ring object proved a 4096-byte, 64-byte-aligned descriptor section.
- Isolated clean `nsh-scif` build compiled/linked clock, lowputc, and SCIF changes and generated 106,976-byte `nuttx.bin` and `nuttx.srec` artifacts.
- Focused Cppcheck no longer reports the Ethernet signed bit-31 diagnostics. No HIL validation claimed.
- Independent adversarial re-review: `PASS_WITH_RISK`; no source-level blocker remains in the applied-fix scope. Final artifact gate: `WARN`, solely for missing target/HIL proof.

## Scout context

- **Verified in source:** Active driver code is under `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`; board registration is under `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/`. The listed `refs/` trees are read-only parity evidence.
- **Recorded:** ADC, Ether, Ether PHY, and SCIF are already marked `blocked` in `docs/renesas/port-status-nuttx.md`; no linked target transcript promotes any of them beyond source/build evidence.
- **Verified in source:** ADC has one selectable scan-end IRQ and no worker; `ANIOC_TRIGGER` is task context. GBETH uses an ISR plus HPWORK, LPWORK, and watchdog paths. SCIF uses selectable RXI/TXI IRQs and the NuttX serial upper half.
- **Verified in source:** ADC reference is 12-bit, eight-channel, Group-A software scan. `ADELCCR=0` is a valid Group-A ELC selection; the older concern that zero disables scan-end routing is invalid.
- **Verified in source:** GBETH reference exposes separate SDB, per-channel TX, and per-channel RX interrupt lines. NuttX attaches only SDB/MACIRQ while servicing DMA channel status.
- **Verified in source:** SCIF reference is polling-only. It confirms the register layout and BRR/MDDR values, but not NuttX IRQ lifecycle or FIFO error semantics.
- **Recorded:** SCIF is sample-only; shipping PX4 targets use SCI-B or RTT. This lowers current flight-product reachability but does not make defects in the maintained sample safe.
- **Static analysis:** Cppcheck 2.13.0 was run with active symbols and NuttX include roots. Actionable SCIF unsigned-ID diagnostics and Ethernet signed-shift diagnostics were triaged; header/style noise was not promoted.

## Findings index

| ID | Severity | File:line | Defect class | Summary | Confidence |
|---|---|---|---|---|---|
| ADC-F01 | High | `rzv_adc.c:167-170,217` | contract/MMIO | Byte-wide ADELCCR is written by an odd-address 16-bit store | Verified |
| ADC-F02 | Low | `docs/renesas/peripherals/adc.md:14,56-58,101,120-123,153-160` | documentation integrity | ADC specification conflicts with active and FSP contracts | Verified |
| ETH-F01 | Critical | `rzv_ether.h:64-71`; `rzv_ether.c:853-855` | DMA/contract | CPU descriptors stride 64 bytes while DMA strides 16 | Verified |
| ETH-F02 | Critical | `rzv_clock.h:105,207`; `rzv_clock.c:587-605` | clock/contract | ETH0 clock ID aliases SCI7, so Ethernet remains stopped | Verified |
| ETH-F03 | High | `rzv_ether.c:715-759` | concurrency | IRQ bottom half enters network stack without `net_lock` | Verified |
| ETH-F04 | High | `rzv_ether.c:1000-1027` | state/contract | Link polling changes SYSC clock but leaves MAC mode stale | Verified |
| ETH-F05 | Med | `rzv_ether.c:304-359,867-910` | state machine | Cable absent at ifup prevents later recovery | Verified |
| ETH-F06 | Med | `rzv_ether_phy.c:461-489` | numeric/contract | Unknown negotiated mode is invented as 100FD | Verified |
| ETH-F07 | High | `rzv_ether_phy.c:308-375`; reference `r_phy.c:103-168` | hardware contract | Reference RGMII skew setup is absent | Suspected |
| PHY-F01 | High | `rzv_ether_phy.c:428-440`; `gmii.h:240-245` | contract/numeric | Gigabit is accepted only when local PHY resolves master | Verified |
| ETH-K01 | High | `rzv2h_ether.c:48-115` | pin/contract | RGMII pinmux is still a stub | Verified |
| ETH-K02 | High | `rzv_ether.c:1123-1124`; reference IRQs 765/768/772 | interrupt routing | DMA uses per-channel TX/RX IRQs but driver attaches SDB | Verified |
| SCIF-F01 | High | `rzv_scif.c:92-94,678-695,717-727` | resource/lifecycle | 385+ INTIDs and negative errors truncate into `uint8_t` | Verified |
| SCIF-F02 | Med | `rzv_scif.c:597-642,854-870` | FIFO/contract | Error path may dequeue FRDR after generic drain | Suspected |
| SCIF-F03 | Med | `rzv_scif.c:255-258,349-408` | numeric/bounds | Baud 0 divides by zero; unsupported baud reports success | Verified |
| SCIF-F04 | Med | `rzv_scif.c:625-642` | ISR timing | RX error ISR performs formatted logging per event | Verified |
| SCIF-K01 | High | `rzv_scif.c:172,434-440` | clock/contract | SCIFA0 enables SCI-B clock instead of SCIFA clock/stop path | Verified |
| SCIF-K02 | High | `rzv_scif.c:429-432` | pin/contract | SCIFA0 TX/RX pins remain unconfigured | Verified |
| SCIF-K03 | Med | `rzv_lowputc.c:102-113`; `rzv_start.c:448` | integration | SCIF console configuration makes early setup claim SCI3 | Verified |
| ETH-F08 | Med | `hardware/rzv_ether.h:214,271,288,294`; `rzv_ether.c:272` | portability/numeric | Bit 31 masks use signed left shift | Verified by analyzer |

## Finding descriptions

### ADC-F01 — ADC reset uses an unaligned halfword access for ADELCCR (High)

## Summary
ADC registration writes byte-wide `ADELCCR` through an odd-address 16-bit MMIO store.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source:** `rzv_adc_putreg()` always calls `putreg16()` (`rzv_adc.c:167-170`). `rzv_adc_reset()` passes `RZV_ADC_E_ADELCCR_OFFSET`, defined as `0x007d`, at line 217. With base `0x11c00000`, normal `adc_register()` reset writes a halfword at `0x11c0007d`. The Renesas CMSIS type is `uint8_t`; FSP writes `(uint8_t)p_cfg_extend->adc_elc_ctrl` in `r_adc_e.c:727`.

## What is the expected correct behavior?
Access `ADELCCR` byte-wide at `0x11c0007d`; value zero validly selects Group-A scan ELC without touching offset `0x7e`.

## Relevant logs and/or screenshots/pictures/videos
`rzv_adc.c:167-170,217`; `hardware/rzv_adc.h:36-40,58`; reference `adc_e_iodefine.h:193-204`; reference `r_adc_e.c:727`.

## Impact to the customer
ADC bring-up may data-abort before `/dev/adc0` registers. If unaligned access is tolerated, it still violates the peripheral width contract and may affect an adjacent reserved byte.

# Root cause
One 16-bit accessor is used for both halfword ADC registers and byte-wide `ADELCCR`.

# Solution
Use an 8-bit accessor for `ADELCCR`. Bench/HIL must prove no alignment abort, correct byte-lane access, scan-end delivery, and known-voltage sampling; build-only is insufficient.

# Similar Check Required?
Yes — future `ADGCTRGR`, `ADERCR`, and `ADERCLR` use; category `adc-register-width`.

# Reason of Invalid
(NA)

### ETH-F03 — Ethernet IRQ bottom half runs outside net_lock (High)

## Summary
RX/TX interrupt work mutates NuttX network and ring state concurrently with LP-work transmit polling.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source:** `rzv_work()` calls `rzv_receive()` and `rzv_txdone()` without `net_lock()` (`rzv_ether.c:715-742`). Those paths call protocol input and `devif_poll()` and mutate `d_buf`, `d_len`, ring indices, inflight count, and descriptors. `rzv_txavail_work()` correctly locks around its own `devif_poll()` (`rzv_ether.c:955-965`), so HPWORK and LPWORK can enter shared network/ring state concurrently.

## What is the expected correct behavior?
All deferred network-stack and shared-ring operations must follow the NuttX network-lock contract and serialize with txavail, timeout reset, ioctl, ifup, and ifdown.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether.c:467-539,678-680,715-759,955-965`; peer NuttX pattern `imxrt_enet.c:1222-1234`.

## Impact to the customer
Normal bidirectional load can cause packet/ring corruption, lost accounting, or unsafe descriptor reuse.

# Root cause
The interrupt handler was deferred to work context without adding the standard network-driver lock.

# Solution
Guard bottom-half RX/TX work and audit teardown ordering. Bench/HIL must combine ping flood, UDP/TCP TX, repeated ifdown/up, forced completion/timeout, and long ring-state soak; build-only is insufficient.

# Similar Check Required?
Yes — timeout, PHY poll, ioctl, and teardown contexts; category `ether-netlock-concurrency`.

# Reason of Invalid
(NA)

### ETH-F04 — PHY polling leaves MAC speed/duplex stale (High)

## Summary
Renegotiation updates the board clock divider but not MAC `DM/FES/PS` fields.

## Steps to reproduce
1. Bring link up at one mode. 2. Change partner advertisement without ifdown. 3. Wait for polling.

## What is the current bug behavior?
**Verified in source:** initial `rzv_configure_link()` computes/writes `MAC_CONF.DM/FES/PS` (`rzv_ether.c:314-362`). `rzv_phy_poll_work()` later updates only cached state and `rzv_ether_board_set_speed()` (`rzv_ether.c:1000-1027`). A 1000FD→100FD transition changes SYSC timing but leaves MAC configured for gigabit.

## What is the expected correct behavior?
Apply resolved MAC mode and SYSC speed coherently while safely sequencing MAC/DMA and carrier state.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether.c:314-368,984-1031`.

## Impact to the customer
Cable/switch renegotiation can stop or corrupt traffic until manual interface cycling or reset.

# Root cause
The poll path duplicates link decoding but omits MAC reconfiguration.

# Solution
Centralize link-mode application under the correct lock and hardware sequencing. Bench/HIL must force 1000FD↔100FD↔10HD transitions and verify PHY, MAC_CONF, SYSC, and traffic; build-only is insufficient.

# Similar Check Required?
Yes — initial and polled link paths, both ports; category `ether-link-mode-sync`.

# Reason of Invalid
(NA)

### ETH-F05 — Interface cannot recover when cable is absent at ifup (Med)

## Summary
Carrier-down aborts administrative ifup before the polling mechanism exists.

## Steps to reproduce
1. Boot or ifup without a cable. 2. Insert cable after initialization.

## What is the current bug behavior?
**Verified in source:** PHY link-down becomes `-ENETDOWN` in `rzv_configure_link()` (`rzv_ether.c:304-359`). `rzv_ifup()` returns at lines 867-871 before MAC/DMA start, `bifup=true`, or PHY poll scheduling at lines 905-910. Later insertion is never observed.

## What is the expected correct behavior?
Administrative ifup should permit carrier-down and arm bounded link monitoring/recovery.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether.c:304-374,863-912`.

## Impact to the customer
A device booted before its switch/cable remains offline until manual cycling or reboot.

# Root cause
Administrative state and carrier state are conflated; monitoring depends on initial carrier success.

# Solution
Represent link-down as a valid ifup state and schedule recovery. Bench/HIL must cold-boot unplugged, hot-plug at varied delays, obtain DHCP/ping, and repeat unplug/replug; build-only is insufficient.

# Similar Check Required?
Yes — autoneg timeout/down handling and both ports; category `ether-linkdown-ifup`.

# Reason of Invalid
(NA)

### ETH-F06 — Unknown PHY mode is forced to 100FD (Med)

## Summary
Link-up without a recognized common AN ability silently becomes 100 Mbps full duplex.

## Steps to reproduce
Review code; runtime trigger is link-up with `ANAR & ANLPAR` lacking bits 8/7/6/5.

## What is the current bug behavior?
**Verified in source:** after `ability = anar & anlpar`, the final branch assigns `PHY_LINK_100FD` (`rzv_ether_phy.c:461-489`). Incomplete negotiation, parallel detection, forced/vendor mode, or malformed reads can therefore program MAC/SYSC to an invented mode.

## What is the expected correct behavior?
Keep the mode unresolved/down or obtain it from a validated PHY-specific resolved-status register.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether_phy.c:385-491`.

## Impact to the customer
PHY/MAC mismatch can produce collisions, packet loss, or total traffic failure.

# Root cause
An unsafe fallback substitutes a plausible mode for missing evidence.

# Solution
Return an explicit unresolved/error result or use proven PHY status. Bench/HIL must cover forced 10/100 half/full modes, autoneg-disabled partners, incomplete negotiation, and MDIO faults; build-only is insufficient.

# Similar Check Required?
Yes — all PHY mode fallback paths; category `phy-mode-resolution`.

# Reason of Invalid
(NA)

### ETH-F07 — Board-reference RGMII skew setup is absent (High)

## Summary
The active PHY path omits the reference MMD delay/skew profile used by the RDK example.

## Steps to reproduce
Review code; confirm PHY revision/straps and measure RGMII timing.

## What is the current bug behavior?
**Verified mismatch / Suspected failure:** active autoneg programs standard registers only (`rzv_ether_phy.c:308-375`). The supplied RDK reference compiles delay setup and writes MMD device 2 registers: `0x0004=0x0070`, `0x0008=0x0307`, and `0x0006=0x7777` (`r_phy.c:103-168`). Active code defines MMD access registers 13/14 but never uses them. Whether straps/layout provide equivalent timing is **Unverified**.

## What is the expected correct behavior?
Apply the board/PHY-approved RGMII timing profile at the correct reset phase, or prove and record that strap/layout delay ownership makes it unnecessary.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether_phy.c:308-375`; `rzv_ether_phy.h:48-51`; reference `r_phy.c:103-168`.

## Impact to the customer
If required, MDIO/link may appear healthy while RGMII data violates setup/hold, causing CRC errors or complete failure, especially at 1 Gbps and PVT corners.

# Root cause
PHY-specific board initialization was not ported; necessity depends on unverified hardware ownership.

# Solution
Confirm PHY model/revision, straps, and schematic first; then port the validated sequence or close with evidence. Bench/HIL must scope TXC/RXC versus data/control, read back MMD registers, and run CRC traffic soak; build-only is insufficient.

# Similar Check Required?
Yes — reset persistence, both ports, and supported PHY revisions; category `phy-rgmii-skew`.

# Reason of Invalid
(NA)

### PHY-F01 — Gigabit detection rejects the PHY slave role (High)

## Summary
1000BASE-T full duplex is recognized only when the local PHY resolves as master.

## Steps to reproduce
Review code; runtime trigger is successful 1000BASE-T negotiation with the local PHY selected as slave.

## What is the current bug behavior?
**Verified in source:** `rzv_phy_linkstatus()` requires bit 14 named `PHY_1000BTSR_MS_RESOLVED` before returning 1000FD (`rzv_ether_phy.c:428-440`). NuttX's canonical `gmii.h:244` defines the same bit as `GMII_1000BTSR_MASTER`: configuration resolved **to master**, not “resolution completed.” A valid slave result has bit 14 clear, so the code falls into 10/100 ANAR/ANLPAR logic and commonly configures 100FD while the physical link is 1000FD. The reference recognizes gigabit from partner bit `0x0800` without requiring local-master bit 14 (`r_phy.c:171-179`).

## What is the expected correct behavior?
Accept 1000FD for either master or slave when local/partner gigabit advertisements and valid link/receiver status prove the mode; bit 14 reports role only.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether_phy.c:421-440`; `rzv_ether_phy.h:113-120`; `include/nuttx/net/gmii.h:235-245`; reference `r_phy.c:171-179`.

## Impact to the customer
Roughly role-dependent gigabit links can be misprogrammed as 100 Mbps, causing deterministic traffic failure despite link-up indication.

# Root cause
IEEE register bit 14 was misnamed and treated as a negotiation-complete predicate instead of the resolved master/slave role.

# Solution
Remove bit 14 from gigabit-validity gating and separately reject bit 15 master/slave fault. Bench/HIL must force/observe both local-master and local-slave resolutions, verify MAC/SYSC mode, and sustain 1 Gbps traffic; build-only is insufficient.

# Similar Check Required?
Yes — PHY status bit names and every use of register 10; category `phy-1000-role-resolution`.

# Reason of Invalid
(NA)

### ETH-K01 — RGMII pinmux remains a stub (High)

## Summary
GBETH0 RGMII and MDIO pads are never configured by the board layer.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source / previously recorded:** board pin macros are zero placeholders and every `rzv_gpioconfig(GPIO_ETH0_*)` call is inside a TODO/comment (`rzv2h_ether.c:48-115`).

## What is the expected correct behavior?
Configure schematic-confirmed MDC, MDIO, TX/RX clock, data, and control functions before PHY access.

## Relevant logs and/or screenshots/pictures/videos
`rzv2h_ether.c:48-115`; prior audit F2.

## Impact to the customer
MDIO cannot reach the PHY and RGMII traffic cannot leave the SoC.

# Root cause
Board-specific pin mapping was never completed.

# Solution
Port schematic/FSP-confirmed PFC settings. Bench/HIL must verify pad mux readback, PHY ID over MDIO, and RGMII waveforms; build-only is insufficient.

# Similar Check Required?
Yes — GBETH1 and all referenced RGMII signals; category `ether-rgmii-pinmux`.

# Reason of Invalid
(NA)

### ETH-K02 — Driver attaches the wrong Ethernet interrupt line (High)

## Summary
The DMA handler attaches SDB/MACIRQ while channel-0 TX and RX have distinct physical interrupt events.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source / previously recorded:** NuttX attaches event `0x2fd`/765 (`rzv_ether.c:1123-1124`; `rzv2h_irq.h:523-528`) and handles DMA channel TI/RI. The supplied reference defines port-0 SDB=765, TX channel 0=768, and RX channel 0=772; its SDB handler is MAC/PTP-oriented while RX channel handler increments the LAN receive count (`r_ether.c:1435-1461,1538-1543`).

## What is the expected correct behavior?
Attach the actual per-channel TX/RX events, or prove a documented aggregator routes them to SDB.

## Relevant logs and/or screenshots/pictures/videos
Active paths above; reference `rzv2h_irq.h:716-742` and `r_ether.c:1435-1461,1520-1543`.

## Impact to the customer
TX completions and RX readiness never schedule the NuttX bottom half; watchdog resets and no ingress result.

# Root cause
SDB was mislabeled “combined MAC/DMA” despite separate channel event topology.

# Solution
Represent/attach both channel-0 TX/RX events with correct teardown. Bench/HIL must count exactly one IRQ per injected RX/TX completion and pass ring-wrap traffic; build-only is insufficient.

# Similar Check Required?
Yes — both ports and all enabled DMA channels; category `ether-dma-irq-routing`.

# Reason of Invalid
(NA)

### SCIF-F01 — GIC interrupt IDs truncate to eight bits (High)

## Summary
385+ physical INTIDs and negative attach errors are narrowed into unsigned eight-bit fields.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source:** `irq_rxi`, `irq_txi`, and `irq_eri` are `uint8_t` (`rzv_scif.c:92-94`). `rzv_icu_attach()` returns signed physical INTIDs starting at 385. Assignment converts 385 to 129, and `priv->irq_rxi < 0` / `irq_txi < 0` can never detect failure. Negative errors wrap. Shutdown later detaches the truncated unrelated ID (`rzv_scif.c:678-695,717-727`). Cppcheck independently reports `unsignedLessThanZero` at lines 681 and 690.

## What is the expected correct behavior?
Preserve the signed `int` return, validate it, publish it only on success, and detach the same full INTID.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:92-94,678-695,717-727`; `rzv_icu.h:42-51`; Cppcheck 2.13.0 log.

## Impact to the customer
After clock/pin repair, attach errors can masquerade as success and close/reopen can leak routes, detach the wrong IRQ, deliver duplicates, and exhaust ICU slots.

# Root cause
A signed physical IRQ contract was narrowed to `uint8_t`.

# Solution
Use signed `int` storage with ordered rollback. Bench/HIL must repeatedly open/transfer/close/reopen while recording INTR8SEL/GIC state and exactly one RXI/TXI delivery; build-only is insufficient.

# Similar Check Required?
Yes — every RZ/V2H lower half storing `rzv_icu_attach()` output; category `icu-intid-width`.

# Reason of Invalid
(NA)

### SCIF-F02 — RX error cleanup may dequeue an extra byte (Med)

## Summary
The RXI handler can read FRDR after the generic receive loop has already drained FIFO data.

## Steps to reproduce
Review code; bench confirmation requires an errored byte followed immediately by a known valid byte.

## What is the current bug behavior?
**Suspected:** RXI captures FSR, then calls `uart_recvchars()` (`rzv_scif.c:608-615`). Generic receive repeatedly invokes `rzv_scif_receive()`, which reads FRDR (`rzv_scif.c:854-870`). The ISR then uses its pre-drain PER/FER snapshot and reads FRDR again at lines 625-632. That read can consume a newly arrived valid byte or access an empty FIFO. Exact PER/FER clearing semantics remain hardware-unverified.

## What is the expected correct behavior?
Each FIFO entry must be dequeued exactly once with error status handled coherently in the same drain path.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:597-642,854-870`; `drivers/serial/serial_io.c:149-243`.

## Impact to the customer
Noise/parity/framing events can drop an adjacent valid shell/protocol byte; frequency is timing-dependent.

# Root cause
Post-drain error cleanup acts on a pre-drain status snapshot.

# Solution
Confirm per-entry error semantics and integrate discard/status into one dequeue path. Bench/HIL must inject isolated/back-to-back parity and framing errors and compare byte sequences/FIFO counts; build-only is insufficient.

# Similar Check Required?
Yes — SCI-B and FIFO UARTs with post-drain cleanup; category `uart-error-double-dequeue`.

# Reason of Invalid
(NA)

### SCIF-F03 — Invalid baud divides by zero or silently succeeds (Med)

## Summary
Baud zero reaches integer division by zero, while other unsupported rates install a fallback and return success.

## Steps to reproduce
Review code; configure `CONFIG_SCIF0_BAUD=0` once clock access works.

## What is the current bug behavior?
**Verified in source:** Kconfig has no range. With baud zero, candidate selection fails and the error path later evaluates `(1000000U / baud) + 1U` (`rzv_scif.c:255-258,279-358,406-412`). For nonzero unachievable rates, `rzv_scif_setbaud()` installs BRR=0/CKS=0, returns `void`, and setup returns `OK` (`rzv_scif.c:516-540`).

## What is the expected correct behavior?
Reject zero/out-of-range rates before mutation and propagate a negative errno while retaining prior valid configuration.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:255-258,279-358,406-412,516-540`; `Kconfig:764-766`.

## Impact to the customer
A bad static config can fault; an unsupported nonzero config reports success but produces total serial link failure.

# Root cause
The baud calculator has no input contract and no status return.

# Solution
Validate inputs and make calculation/setup status-returning. Bench/HIL must cover invalid limits and measured 9600/115200/230400/460800 baud; build-only is insufficient.

# Similar Check Required?
Yes — SCI-B, SCI-I2C, and SCI-SPI rate calculators; category `serial-baud-validation`.

# Reason of Invalid
(NA)

### SCIF-F04 — Formatted logging runs in the RX error ISR (Med)

## Summary
Every frame/parity/break/overrun event can execute formatted logging at interrupt priority.

## Steps to reproduce
Review code; drive a sustained malformed/noisy RX stream with debug info enabled.

## What is the current bug behavior?
**Verified in source:** RXI calls `_info("SCIF%d: Frame error ...")` and `_info("SCIF%d: Overrun")` (`rzv_scif.c:625-642`). `nsh-scif` enables debug info/full options, so a floating/noisy line can format and transport a message per interrupt at GIC priority `0xa0`.

## What is the expected correct behavior?
ISR work should be bounded to status capture, FIFO service, and counters; diagnostics should be deferred/rate-limited.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:597-645`; `nsh-scif/defconfig:67-73`; `rzv_irq.c:54-57,100-107`.

## Impact to the customer
A noisy line can monopolize interrupt time, worsen overruns, and starve equal/lower-priority work.

# Root cause
Diagnostics were placed directly in the hot ISR without bounding.

# Solution
Record counters/status in ISR and emit deferred/rate-limited diagnostics. Bench/HIL must inject sustained errors at maximum baud and measure ISR duration, responsiveness, and log rate; build-only is insufficient.

# Similar Check Required?
Yes — RZ/V2H serial/CAN/Ethernet/timer ISRs; category `isr-formatted-logging`.

# Reason of Invalid
(NA)

### SCIF-K01 — SCIFA0 enables the SCI-B clock path (High)

## Summary
SCIFA0 is configured with the RSCI/SCI0 clock identifier and remains clock-gated/module-stopped.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source / previously recorded:** SCIF config uses `RZV_CPG_CLK_SCI0` (`rzv_scif.c:172`) and setup calls the generic SCI-B clock path (`rzv_scif.c:434-440`). FSP evidence places SCIFA0 at `CPG_CLKON_8[15]` and requires MCPU2 module-stop handling; SCI0 is a different peripheral.

## What is the expected correct behavior?
Use a distinct SCIFA clock/reset/MSTOP contract and verify monitor state before MMIO.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:90,172,434-440`; `rzv_clock.h:82-107`; prior SCIF audit F1; FSP `bsp_override.h`/`bsp_module_stop.h`.

## Impact to the customer
SCIFA register writes are ineffective and TX readiness never arrives; console/link is dead.

# Root cause
SCIFA was assigned an SCI-B clock ID.

# Solution
Add exact SCIFA clock/reset/MSTOP support. Bench/HIL must capture clock/reset registers, transmit/receive bytes, and measured baud; build-only is insufficient.

# Similar Check Required?
Yes — all SCIFA instances and clock-ID aliases; category `scifa-clock-routing`.

# Reason of Invalid
(NA)

### SCIF-K02 — SCIFA0 pins remain unconfigured (High)

## Summary
No board or driver path muxes SCIFA0 TXD/RXD to physical pads.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source / previously recorded:** `rzv_scif.c:429-432` leaves pin setup as TODO; RDK serial glue configures SCI-B channels only (`rzv2h_serial.c:61-116`).

## What is the expected correct behavior?
Configure package/schematic-confirmed SCIFA0 RXD/TXD PFC functions before enabling the UART.

## Relevant logs and/or screenshots/pictures/videos
`rzv_scif.c:429-432`; `rzv2h_serial.c:61-116`; prior SCIF audit F2.

## Impact to the customer
No physical serial input/output even after clock repair.

# Root cause
Board-specific SCIFA pin ownership was never implemented.

# Solution
Add schematic-confirmed pinmux. Bench/HIL must read back PFC and prove bidirectional waveform/decoded bytes; build-only is insufficient.

# Similar Check Required?
Yes — any future SCIFA channel; category `scifa-pinmux`.

# Reason of Invalid
(NA)

### SCIF-K03 — SCIF console configuration claims SCI3 during early setup (Med)

## Summary
Early low-level setup targets SCI3 while the registered console later targets SCIFA0.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source / previously recorded:** `rzv_lowputc.c` has SCI-B selection only and falls back to SCI3 when no SCIx console symbol is selected (`rzv_lowputc.c:102-113`). Startup still invokes low setup (`rzv_start.c:448`) under the SCIF console configuration.

## What is the expected correct behavior?
SCIF console configuration must either provide SCIFA-aware low setup or explicitly disable early SCI pin/clock mutation.

## Relevant logs and/or screenshots/pictures/videos
`rzv_lowputc.c:102-133`; `rzv_start.c:448`; prior SCIF audit F4.

## Impact to the customer
Early output appears on the wrong pins and SCI3 can be modified despite belonging to another payload.

# Root cause
Low-console selection has no SCIFA branch and uses an unconditional SCI3 fallback.

# Solution
Make early-console selection explicit and non-invasive. Bench/HIL must capture boot output and confirm SCI3 registers/pins remain unchanged when SCIFA is selected; build-only is insufficient.

# Similar Check Required?
Yes — every console combination and integrated PX4 payload ownership; category `serial-early-console-split`.

# Reason of Invalid
(NA)

### ETH-F08 — Ethernet bit-31 masks use signed left shift (Med)

## Summary
Descriptor ownership/interrupt masks and MAC address-valid bit use `1 << 31` with signed `int`.

## Steps to reproduce
Run Cppcheck 2.13.0 with the active Ethernet symbols.

## What is the current bug behavior?
**Verified by analyzer/source:** macros `MAC_PKT_FILT_RA`, `TDES2_IOC`, `TDES3_OWN`, and `RDES3_OWN` plus `rzv_set_macaddr()` use `(1 << 31)`. Cppcheck reports `shiftTooManyBitsSigned` at active uses including `rzv_ether.c:237,272,398,419,420,554,596,643`. Left-shifting signed `1` into the sign bit is not a portable C constant expression; current GCC behavior is **Unverified**, not evidence of a field failure.

## What is the expected correct behavior?
Build register masks with unsigned-width operands, such as `UINT32_C(1) << 31`.

## Relevant logs and/or screenshots/pictures/videos
`hardware/rzv_ether.h:214,271,288,294`; `rzv_ether.c:272`; `/tmp/rzv2h-four-driver-cppcheck.log`.

## Impact to the customer
Current GCC likely emits intended bits, but compiler/toolchain changes or stricter optimization can miscompile or reject ownership/IOC/address-valid operations.

# Root cause
Register masks were defined with a signed literal.

# Solution
Use explicit `uint32_t` constants and compile-time asserts. Verify emitted descriptor words and traffic on target; build-only is insufficient for DMA behavior.

# Similar Check Required?
Yes — all MMIO/descriptor bit-31 macros; category `register-mask-signed-shift`.

# Reason of Invalid
(NA)

### ADC-F02 — ADC documentation records incompatible contracts (Low)

## Summary
The ADC specification contains incompatible channel, API, IRQ, reference, base-address, and register-map claims.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Recorded/Verified in source:** `adc.md` says 16 channels, `adc_read()` trigger, IRQ 183, `r_adc/r_adc.c`, and base `0x110a0000`. Active/FSP contracts are eight channels, `ANIOC_TRIGGER`, selectable NuttX IRQ versus FSP fixed IRQ 353, `r_adc_e/r_adc_e.c`, and base `0x11c00000`. The document also names nonexistent config symbols and registers.

## What is the expected correct behavior?
Document only the active ADC_E contract and label selectable IRQ and physical pin behavior by evidence tier.

## Relevant logs and/or screenshots/pictures/videos
`docs/renesas/peripherals/adc.md:14,50-58,95-103,118-163`; `rzv_adc.c:368-389`; `rzv_adc.h:55-57`; FSP `vector_data.h:15`.

## Impact to the customer
No direct runtime effect, but contributors can configure nonexistent features, use the wrong MMIO map, or build consumers that never trigger/decode ADC data.

# Root cause
The document predates current ADC_E source and was not reconciled with the supplied reference.

# Solution
Correct source-proven claims and validate examples with known-voltage and IRQ captures; build-only is insufficient for behavioral claims.

# Similar Check Required?
Yes — copied ADC claims in port-status and PX4 integration documents.

# Reason of Invalid
(NA)

### ETH-F01 — Cache padding breaks the EQOS descriptor stride (Critical)

## Summary
Software advances 64 bytes per descriptor while EQOS DMA advances 16 bytes into padding.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source:** `struct rzv_eth_desc_s` has four descriptor words plus twelve reserved words and is 64-byte aligned (`rzv_ether.h:64-71`). CPU ring arithmetic therefore advances 64 bytes. `rzv_ifup()` writes only `DMA_CH0_CTRL_PBLX8` (`1 << 16`) and defines/programs no descriptor skip length (`rzv_ether.c:853-855`). The reference `struct dma_desc` is four words/16 bytes. After descriptor zero, DMA interprets `reserved[0..3]` as the next descriptor while CPU/tail pointers refer to the next 64-byte object.

## What is the expected correct behavior?
CPU and DMA must share one proven stride: coherent/noncacheable contiguous 16-byte descriptors, or exact EQOS DSL programming for 64-byte descriptors.

## Relevant logs and/or screenshots/pictures/videos
`rzv_ether.h:56-71`; `rzv_ether.c:844-855`; reference `r_ether.h:164-174`.

## Impact to the customer
Deterministic TX/RX failure after descriptor zero, false OWN/status fields, stalls, and possible DMA access through zero/padding-derived addresses.

# Root cause
The prior cacheline-isolation repair changed the software descriptor ABI without changing DMA stride.

# Solution
Restore a hardware-compatible coherent layout or program/assert exact DSL. Bench/HIL must cover multiple full TX/RX ring wraps, descriptor progression, RBU/TBU/TPS/RPS, and memory canaries; build-only is insufficient.

# Similar Check Required?
Yes — TX/RX rings and both ports; category `ether-dma-descriptor-stride`.

# Reason of Invalid
(NA)

### ETH-F02 — ETH0 clock ID executes SCI7 clock/reset logic (Critical)

## Summary
GBETH0 initialization enables/resets SCI7 and leaves the Ethernet bus interface stopped.

## Steps to reproduce
Review code.

## What is the current bug behavior?
**Verified in source:** `RZV_CPG_CLK_SCI7` and `RZV_CPG_CLK_ETH0` both equal `(8 << 16 | 0)` (`rzv_clock.h:105,207`). Value-based `rzv_cpg_sci_channel()` identifies ETH0 as SCI7, so clock enable and module reset take SCI paths. `g_rzv_mstop_map` explicitly omits GBETH BUS_8 MSTOP5 because of the alias (`rzv_clock.c:757-760`). Board initialization nevertheless calls these generic APIs as Ethernet setup (`rzv2h_ether.c:151-163`).

## What is the expected correct behavior?
Use distinct, hardware-confirmed GBETH clock/reset identifiers, release BUS_8 MSTOP5, enable required CSR/ACLK/RGMII clocks, and leave SCI7 unchanged.

## Relevant logs and/or screenshots/pictures/videos
`rzv_clock.h:105,188-207`; `rzv_clock.c:587-605,757-760,1048-1055,1416-1423`; `rzv2h_ether.c:151-163`; reference `EtherMain.c:318-375`.

## Impact to the customer
Hard GBETH bring-up failure: register/MDIO access stays stopped or unclocked, while SCI7 can be unexpectedly manipulated.

# Root cause
A numeric clock-ID collision is dispatched by value as a peripheral type.

# Solution
Add distinct verified GBETH clock/reset handling and fail configuration until complete. Bench/HIL must read CLKON/CLKMON/RST/RSTMON/BUS_8 MSTOP, prove SCI7 unchanged, read PHY ID, and pass traffic; build-only is insufficient.

# Similar Check Required?
Yes — GBETH1 and all equal clock-ID values; category `cpg-id-alias`.

# Reason of Invalid
(NA)

## Prior audit reconciliation

- **ADC closed/superseded:** current ADC0 clock ID, reset, and module-stop handling are present; `ADELCCR=0` is valid Group-A ELC selection; the older statement that no FSP ADC reference exists is superseded by the supplied ADC_E project.
- **Ether closed in source:** RX queue enable, pointer-width assertion, interrupt-pending serialization, exclusive RX tail handling, MAC baseline setup, PBLx8, periodic PHY polling, and 1000FD advertisement. The prior descriptor cache fix is reopened as ETH-F01 because its 64-byte padding changed DMA stride without DSL programming.
- **Ether still open:** RGMII pinmux (ETH-K01), interrupt topology (ETH-K02), and unsupported/unverified GBETH1 clock identifiers. The latter remains a recorded scope blocker, not duplicated as a new ticket.
- **SCIF closed in source:** polled console transmit-ready guard, TEI removal, stale baud-field clearing, and write-zero-to-clear helpers.
- **SCIF still open:** wrong SCIFA clock path (SCIF-K01), missing pin setup (SCIF-K02), and SCI3 early-console split (SCIF-K03). The currently equal priority constants were not promoted: divergence is only latent until configuration changes.

## Static analysis triage

- Cppcheck 2.13.0 confirmed the SCIF unsigned interrupt-ID error checks cannot work after narrowing and reported eight signed `1 << 31` expressions in the Ethernet path; these map to SCIF-F01 and ETH-F08.
- Style-only findings, unused-function reports caused by partial configuration, and missing-system-include noise were not promoted.
- Analysis stopped after the combined active-file pass produced no additional defect class. It had limited include/value-flow knowledge and does not validate MMIO, concurrency, timing, DMA coherency, or target behavior.

## What was not checked

- No RZ/V2H target, J-Link session, logic analyzer, oscilloscope, packet capture, PHY register dump, or traffic test was available.
- No silicon manual evidence beyond checked-in headers and user-supplied references; exact PHY model/revision, straps, schematic delay ownership, and physical pin routing remain unverified.
- Bootloader ownership of GBETH clocks, resets, BUS_8 MSTOP5, SYS_AOF24, MPU/cacheability, and DMA bus visibility was not established.
- Actual GIC event routing, affinity, and priority on silicon were not measured.
- Remediation builds ran in isolated copies to avoid mutating unrelated worktree state. They prove compilation/linking only, not hardware contracts.
- PX4 consumers outside registration/configuration reachability were not exhaustively audited. GBETH1 runtime was not evaluated because its clock IDs remain unsupported.

## Exact commands run

Representative read-only commands (repeated with narrower ranges and symbols):

```text
sed -n '1,240p' README.md
sed -n '1,260p' docs/renesas/README.md
sed -n '1,280p' docs/renesas/porting-playbook.md
sed -n '1,280p' docs/renesas/port-status-nuttx.md
rg -n "adc_register|ADELCCR|putreg16|ANIOC_TRIGGER|ADC0_SCAN_END" platforms/nuttx/NuttX/nuttx refs docs/renesas
rg -n "RZV_CPG_CLK_ETH|RZV_CPG_CLK_SCI7|PBLX8|DSL|net_lock|MAC_CONF|PHY_LINK|MACIRQ" platforms/nuttx/NuttX/nuttx refs/rzv2h_gb_ether
rg -n "SCIF|SCIFA|rx_irq|tx_irq|uart_recvchars|SCFSR|baud" platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h refs/rzv2h_gb_ether/drivers
git status --short
git -C platforms/nuttx/NuttX/nuttx status --short
cppcheck --version
cppcheck --enable=warning,style,performance,portability --inconclusive --force --std=c11 --suppress=missingIncludeSystem --suppress=missingInclude -DCONFIG_RZV_ADC=1 -DCONFIG_RZV_ADC0=1 -DCONFIG_RZV_ETHERNET=1 -DCONFIG_RZV_ETHER0=1 -DCONFIG_RZV_UART_SCIF=1 -DCONFIG_SCIF0_SERIAL_CONSOLE=1 [NuttX include roots] rzv_adc.c rzv_ether.c rzv_ether_phy.c rzv_scif.c rzv_lowputc.c rzv2h_ether.c
python3 test/rzv2h_adc_ether_scif_contract_test.py -v
python3 -m unittest discover -s test -p 'rzv2h_*_contract_test.py' -v
RZV_NUTTX_ROOT=/tmp/rzv2h-nuttx-baseline-audit python3 test/rzv2h_adc_ether_scif_contract_test.py -v
./build.sh ether
./build.sh nsh-scif
```

## Open questions

1. Does TF-A/U-Boot guarantee every GBETH clock, reset, BUS_8 MSTOP5, and SYS_AOF24 prerequisite before CR8 starts, or must the NuttX driver own the full sequence?
2. What exact PHY model/revision and strap configuration is fitted, and which side owns RGMII delay/skew?
3. What are the validated per-channel TX/RX event IDs, priorities, and handler topology for each GBETH port?
4. Which selectable ADC scan-end route and analog pin set are required by the shipping board configuration?
5. What safe MAC/DMA/carrier sequence should apply live speed changes and recover from cable-absent ifup?
6. Is SCIFA0 intended to remain maintained, and if so, what are its approved pins and PER/FER dequeue semantics?
