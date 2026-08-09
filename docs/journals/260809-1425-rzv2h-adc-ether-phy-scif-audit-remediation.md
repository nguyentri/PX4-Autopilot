# RZ/V2H ADC, Ethernet, PHY, and SCIF Audit Remediation

**Date**: 2026-08-09 14:25
**Severity**: High
**Component**: RZ/V2H NuttX drivers and board integration
**Status**: Partially remediated, HIL pending

## What Happened

We partially closed out Mission 1 by fixing 12 of 20 findings in ADC, Ethernet, PHY, and SCIF. We only applied changes backed by checked-in Renesas or NuttX evidence, and we left board/PHY authority gaps unresolved instead of inventing literals that would have made the code look finished while still being wrong.

## The Brutal Truth

This was frustrating because the code was close enough to compile but not trustworthy enough to ship on hope. The nasty part is that a lot of the failures were the kind that only show up after real hardware starts arguing back: DMA ownership, clock/reset order, and link-mode transitions. We fixed the source contracts, but we still do not have target proof that the board behaves under stress.

## Technical Details

Key fixes were source-backed:

- ADC now writes `ADELCCR` byte-wide with `putreg8()` instead of a halfword store.
- Ethernet descriptors are 16-byte records in non-cacheable SRAM, with `dmb sy` barriers around CPU/DMA ownership handoffs and tail publication.
- Deferred Ethernet work now takes `net_lock()`, and `ifdown` cancels all queued workers before clearing state.
- PHY link resolution no longer invents `100FD`; gigabit accepts either local-master or local-slave role when advertisement, partner, and receiver evidence agree and no master/slave fault exists.
- SCIF now uses the SCIFA0 clock/reset path, validates baud before mutating registers, preserves signed ICU IDs, and blocks the early SCI-B console fallback.

Verification was not hand-wavy:

- 16/16 source-contract checks passed and failed against the pre-fix source.
- 85/85 broader contract-discovery checks passed.
- Isolated clean Ethernet and `nsh-scif` builds completed, including a `207,788` byte Ethernet image and a `106,976` byte `nuttx.bin`.

## What We Tried

We considered board-specific clock, pinmux, and PHY timing literals, but rejected that path because the authority was not strong enough. We also rejected fake fallback behavior in PHY and SCIF startup.

## Root Cause Analysis

The real failure was mixing verified driver logic with unverified board assumptions. That created wrong access widths, stale mode state, unsafe concurrency, and an early-console path that claimed hardware it did not own.

## Lessons Learned

Do not let build success stand in for runtime proof. If the hardware contract is not authoritative, stop at the source fix and call out the gap. Also: DMA and network work cannot be “probably fine” without explicit locking and barrier points.

## Next Steps

HIL still needs to prove Ethernet descriptor coherency, live link renegotiation, SCIF bring-up on real pins, and the remaining RZ/V2H board timing assumptions. Ownership sits with the RZ/V2H bring-up workstream, and the unresolved board questions must be answered before any claim of runtime closure.

## Unresolved Questions

- Exact GBETH CPG, pinmux, and per-channel event mapping for CR8?
- RDK PHY revision, straps, and RGMII delay ownership?
- SCIFA0 package pins and board routing?
