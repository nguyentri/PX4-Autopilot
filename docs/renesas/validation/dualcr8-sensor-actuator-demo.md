# Dual-CR8 candidate validation

This procedure covers canonical `renesas_rdk-rzv2h_dualcr8` and the
`renesas_rdk-rzv2h-io-cr8_1_pwm` supervisor candidate. Both are software
candidates with no qualified actuator-pair identity. Unknown ESC, power,
storage and local-kill contracts prevent resource claim and readiness.
The [implementation plan](../../../plans/261021-0230-rzv2h-dualcr8-sensor-demo/plan.md)
retains full product acceptance and the props-off qualification campaign.

## Software checks

Run from the repository root:

```bash
python3 test/rzv2h-demo-protocol-test.py
python3 test/rzv2h-battery-contract-test.py
python3 test/rzv2h-dualcr8-profile-contract-test.py
python3 test/rzv2h-io-core-health-runtime-test.py
python3 test/rzv2h-px4-artifact-test.py
python3 test/rzv2h-px4-ci-test.py
./build.sh renesas_rdk-rzv2h_dualcr8
./build.sh renesas_rdk-rzv2h-io-cr8_1_pwm
python3 test/rzv2h-dualcr8-artifact-contract-test.py
```

Build sequentially because NuttX configuration state is shared. The artifact
test inspects both real ELFs, core/RTT placement, resolved configuration,
builtins, one sensor descriptor, startup hooks, linked ROMFS and packaged
firmware/metadata. It verifies that policy admits no actuator pair. It is
separate from admission of a sealed archive through
[the regression tooling](rzv2h-regression-ci.md).

The production-code host fixtures exercise token deadlines, disarmed recovery,
standby inhibition with nonzero DIS retained, termination, malformed frames,
snapshot concurrency, independent worker faults and reporter freshness. The
battery fixtures test decoding, source age and ordinary warning mapping;
they do not implement acquisition from an unidentified physical device.

## Runtime owners

- CR8-0 `rzv2h_outputs` owns the standard four-channel `PWM_MAIN` mixer and
  one coherent snapshot. Its callback does not perform raw IPC or recovery.
  The sender owns writes/recovery and publishes backend health, rate and
  battery availability. Commander independently expires the selected producer's
  status after 50 ms and checks backend arm readiness/PWM alarms, including
  while a raw write blocks the sender. Legacy status keeps its two-second
  timeout. A rejected future controller timestamp does not
  advance accepted source progress. Motor termination retains the mixer FAIL
  values in transport while the final CR8-1 inhibit prevents pulses.
- CR8-1 `rzv2h_io` separates receive/control, physical worker and status
  reporting tasks. The candidate worker period is 2.5 ms. The reporter uses
  advancing status sequence numbers but reuses the controller's token and
  its original receiver issue time. It revokes READY for stale control or
  worker reports and preserves worker faults. Reporting never renews a lease.
- The compiled [hardware contract](../../../src/apps/hardware-contract.hpp)
  remains unconfigured. Neither startup nor cleanup claims output resources
  in this condition. CR8-1 `default` remains the separate legacy relay.

## Delayed bench hooks

`CONFIG_RZV2H_DUALCR8_FAULT_INJECTION` is a PX4 Kconfig option, default off,
available only to the two RDK CR8 board families. Normal artifact admission
rejects it when enabled. An enabled bench image requires its own explicit
authorization and identity; no hook has been executed on the board in this
software checkpoint.

After separate hardware authorization, props removal, safe power/kill setup
and normal readiness checks, the enabled modules accept:

```text
rzv2h_outputs fault producer-pause --delay-ms 5000 --duration-ms 100
rzv2h_outputs fault heartbeat-drop --delay-ms 5000 --duration-ms 650
rzv2h_outputs fault corrupt-next-frame --delay-ms 5000 --count 1
rzv2h_io fault control-loop-pause --delay-ms 5000 --duration-ms 100
rzv2h_io fault backend-fail --delay-ms 5000 --count 1
rzv2h_io fault status-drop --delay-ms 5000 --duration-ms 100
```

Only one schedule is admitted per module start. Delay must be 5–60 seconds;
duration must be 1–5000 ms; counted faults require exactly one event. Counted
faults expire if the owning operation does not occur within five seconds after
the delay. The module's `status` prints invoked, started and completed counters.
Expired-before-start schedules have completed=1 and started=0. Restart the
module before scheduling another injection; ordinary disarmed negotiation
still applies. Choose a delay that permits detaching the probe before testing.

Hooks suppress only the named operation. A single corrupted command is
ignored without renewing authority or forcing an artificial session reset;
the prior command remains bounded by its ordinary lease. A control pause
leaves the worker and reporter running. Backend failure latches in the worker
and requires safe module reinitialization. Lease expiry cannot be cleared by
resuming cached armed commands; use a fresh current-epoch disarmed handshake.

## Physical qualification gates

Before any load/reset, pin measurement, fault injection, ESC power or motor
command, obtain the explicit authorization required by
[the deployment guide](../../deployment-guide.md). Never use force-arm or
disable expected-device checks. Stop on the J-Link reset/connect-failure
guard, preserve evidence and obtain renewed approval before retrying.

Record fitted sensor identities/rotations, ESC model/protocol/rate/pulse
bounds, harness/motor order, battery interface and policy, persistent medium
and partition, receiver/kill ICD and reset/core-halt containment. Allocate
compatibility/resource identities only from that reviewed contract.

Qualify a capture correlation method and measure scheduler/HAL jitter before
powered timing tests. The required physical bound is the 50 ms lease plus
worker period plus measured scheduling/HAL budget. Probe/core halt is not a
lease timing test. A halted output core requires independent containment.

Externally capture boot, negotiation, standby with nonzero DIS retained,
termination, stop, per-channel zero, rate mismatch, producer/control pauses,
heartbeat/status loss, backend failure and fresh-disarmed recovery. Distinguish
no pulse, ESC power removal and motor stop. Retain exact image/configuration
hashes, transcripts, captures and probe state. Full acceptance also requires
real battery acquisition, durable calibration with power-cut recovery and
command/kill/release proof; TMPFS and manual reload cannot satisfy it.

On duplicate ownership, false readiness, stale armed replay or excess output
duration, inhibit propulsion, preserve failed evidence and restore an
explicitly identified compatible set. No physical qualification or flight
claim follows from the software checks above.
