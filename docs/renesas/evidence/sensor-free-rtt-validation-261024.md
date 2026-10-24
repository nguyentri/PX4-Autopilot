# Sensor-free native RTT validation, 2026-10-24

The RDK-RZ/V2H campaign executed all 94 admitted native RTT profiles. The
[128-profile result matrix](sensor-free-rtt-matrix-261024.json) records 92 PASS,
two NOT-PASS, six BLOCKED and 28 OUT-OF-SCOPE, preserving 149 attempts. The
[transcript bundle](sensor-free-rtt-transcripts-261024.json) retains named board
captures, exact image/config/source hashes, resource cleanup and CPU observations.
This is bounded native NuttX evidence; integrated PX4, external peripherals,
electrical timing, cold-cycle behavior and production use remain unqualified.

No sensors were connected. Scope covered register identity, IRQ delivery and
internal functions. Serial-primary, sensor/known-source, external traffic and
PWM waveform profiles were excluded. One CM33 RTT profile was blocked because
attachment is unsupported; five watchdog checks were blocked by CPU-observed
clear inhibition bits. No watchdog was started/fed, and CM33 was never attached.

Passing checks include all nine RIIC and ten SCI-I2C controller identities,
all ten SCI-SPI identities, native SPI0/1/2, 32 GPT A/B identities, all 80 DMAC
channels, SDHI0/1/2 identities and idle cancellation, local SGI IPC and separate
raw CR8-0/CR8-1 IPC. Registration does not qualify external bus transfers.
Raw IPC completed 100 byte-exact 64-byte echoes with zero timeouts, independent
peer RTT confirmation and completed echo-task/heap checks. SCIF completed both
128-byte loopback/reopen cases with RXI=248, TXI=235, loop=0 and no case IRQs/files.
Three ADC scans delivered four channels each and released the task/open/IRQ;
IRQ delivery is inferred from the sole callback path, without a counter.
Unknown floating input values do not establish analog accuracy or known-source
qualification, so the canonical ADC source profile remains excluded.

Target-discovered repairs were rebuilt and retested: RTT early output no longer
uses stale SCI3 state; output-only RTT also owns early diagnostics without a
serial console. SCIF no longer waits for transmit completion before a frame has
been queued on a driver-owned non-console port, while console/inherited/post-write
drains remain checked. SDHI snapshots require implemented interrupt-mask bits
instead of reserved all-one readback. Legacy SPI internal demo startup yields
external registration to its internal owner. SCI-SPI/serial assertions now match
actual handles, absent CS routing and disabled-channel errors. Automatic GDB
verification uses bounded PC/GIC reads instead of an unbounded assembly unwind.

Both Ethernet units remain supported. Two target failures are unresolved:

- GBETH1 RX/RX_180 clock admission fails with CLKMON5=`0x7fffffff` and
  CLKMON6=`0xfffffffd`; parent PLL lock does not prove physical RX clock handoff.
- GBETH0 MAC loopback retains RX ownership with DMA status=`0x003f1102` and
  TX/RX descriptors still owned. DMA/bus accessibility is a candidate, not a
  proven root cause. No clock guard or result oracle was bypassed.

All 92 latest passing images were re-admitted: 90 native receipts replayed and
two images used the repository's specialized paired-IPC autotest. Exact archived
source snapshots remain unchanged. The bundle includes explicit preprocessor
and source-impact checks for unchanged compiled paths in earlier source variants;
full equality with the final working-tree source hashes is not asserted. The
ELF/build archives and full earlier attempt logs remain local; this committed
snapshot records their hashes and current outcome rather than embedding binaries.

CR8-0 was restored to `nsh-rtt-interactive`, SHA256
`b18999ea444884bcff2bd6e243a994da051d89dcf09b1eb9fe807a2cb34ee77b`, with
only Idle/NSH tasks and responsive heap reporting. CR8-1 retains raw IPC image
`d47cc5ad9d920ea943628a6cdab3601c07145fb1db3f0d26e6d12279abc433b9`; its
bounded echo task finished. Final host inspection found no probe owner,
bridge/server, campaign process or occupied debug port. This status update
reuses those captures and performs no new board operation.

Pre-commit host verification ran 79 portable regression scripts. All now pass.
The first run retained local-socket sandbox failures in two debug suites and a
stale indexed-SDHI fixture missing mask constants. Socket-capable host reruns
passed; the fixture now uses the real register header, modeled reserved-bit
readback and negative mask checks. No additional target run was needed. The
[regression catalog](../../../Tools/rzv2h-regression-catalog.json) owns the script
inventory and host-only execution contracts.

Source delivery commits are NuttX `3ed2a4555c475c81207a031489205728d18d6abc`,
apps `804b11196c3d1d62249f666e73708246381925c5`, and parent code
`060aeef3fdb58e59434e553c34515056494c2392`. Hardware captures retain their
original exact ELF and archived source-state identities; recording these commits
is not a new on-target run or a rewrite of the older build receipts.
