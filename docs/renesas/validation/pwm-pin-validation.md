# Standalone GPT PWM pin validation

**Updated:** 2026-10-12

Scope: CR8-0 NuttX `pwm` / `pwm-oneshot` configurations and `rzv_gpt.c`, not
the separate PX4 `io_timer` adapter. Source/host checks and timer-register
readback are not physical pin proof. Electrical measurements remain pending.

## Behavior and limits

Continuous duty accepts Q16 values from zero through `0x10000` inclusive.
Exact 100% selects GPT forced-high output; fractional near-full values remain
compare-driven. Values above 100% return `EINVAL`. Finite pulse trains reject
0% and 100% because there are no falling pulse edges to count.

GPT setup enables software group start/stop/clear through GTSSR, GTPSR and
GTCSR bit 31 before issuing those commands. Finite compare interrupts use
CR8 IRQSEL source numbers and edge-triggered GIC delivery. IRQSEL identifiers
are distinct from ELC event identifiers; the GPT header defines both unit
compare-source bases from the core-matched FSP `bsp_irq_id.h` table.

Running period/compare updates inhibit GTBER.BD0/BD1, stage all numeric buffers,
then restore transfer enable. The timer continues counting. A boundary during
staging repeats the complete old numeric configuration rather than transferring
an incomplete period/compare pair. Prescaler changes still return `ERANGE`.

Forced-duty mode bits latch independently at overflow. A simultaneous period
change and transition into/out of 0%/100% is **not** guaranteed to commit in one
cycle. Startup uses an initially low output; steady forced duty is established
at overflow. Measure after startup and also capture transitions separately.

Authority: [Renesas hardware manual](https://www.renesas.com/en/document/mah/rzv2h-group-users-manual-hardware),
R01UH1032EJ0140, §§5.7.2.2.13, 5.7.2.2.17, 5.7.8.2. FSP `R_GPT_PeriodSet`
warns about overflow during its separate buffer writes; its full-duty helper
selects forced-high mode.

## Bench setup

Disconnect ESCs/motors and other loads before PWM output. Use a high-impedance
scope/logic-analyzer input referenced to board ground; verify compatible probe
voltage limits. Resolve connector contacts from the RDK reference when doing
physical qualification: GPIO labels below are not connector contact numbers.
Do not use EVK pin assignments. Software source, host checks, and builds can
proceed from the named RDK mappings while physical connector and waveform
qualification remains pending.

| Device | RDK GPIO | Alternate function | Output |
|--------|----------|--------------------|--------|
| `/dev/pwm0` | PA4 / P10_04 | 11 | GPT6 A |
| `/dev/pwm1` | PA7 / P10_07 | 11 | GPT7 B |
| `/dev/pwm2` | P96 | 9 | GPT9 A |
| `/dev/pwm3` | P53 | 11 | GPT10 B |

Build with `platforms/nuttx/NuttX/build.sh pwm`. Flash/load requires separate
approval. These profiles use the serial NSH (SCI5) at 115200, not the RTT console.

For the full command lines below, configure `CONFIG_NSH_MAXARGUMENTS=16`.
CPU-side register reads also require `CONFIG_NSH_DISABLE_MW` to be unset;
its NuttX default disables `mw`. Use read-only `mw <address>` commands.

## Steady duty and period checks

Run one command at a time on each device; capture during its ten-second window:

```text
pwm -p /dev/pwm0 -f 1000 -d 25 -n 0 -t 10
pwm -p /dev/pwm0 -f 1000 -d 50 -n 0 -t 10
pwm -p /dev/pwm0 -f 1000 -d 75 -n 0 -t 10
pwm -p /dev/pwm0 -f 400 -d 25 -n 0 -t 10
pwm -p /dev/pwm0 -f 50 -d 50 -n 0 -t 10
pwm -p /dev/pwm0 -f 1000 -d 0 -n 0 -t 10
pwm -p /dev/pwm0 -f 1000 -d 100 -n 0 -t 10
```

`-n 0` is essential: the profiles default to ten finite pulses.

| Frequency / duty | Expected period | Expected high time |
|------------------|-----------------|--------------------|
| 1000 Hz / 25% | 1 ms | 250 µs |
| 1000 Hz / 50% | 1 ms | 500 µs |
| 1000 Hz / 75% | 1 ms | 750 µs |
| 400 Hz / 25% | 2.5 ms | 625 µs |
| 50 Hz / 50% | 20 ms | 10 ms |
| 0% / 100% | No steady edges | Constant low / high |

Nominal values assume the configured 200 MHz P4CLK. Record actual clock error,
instrument resolution and tolerance; do not infer them from register readback.
For finite completion, `pwm -p /dev/pwm0 -f 1000 -d 50 -n 10` should emit ten
complete pulses and return. Finite `-d 0` / `-d 100` should fail with `EINVAL`.

## Live transition check

Separate `pwm` invocations stop and close the device: they do not exercise the
running update path. A live harness must keep one descriptor open, set/start
continuous 50 Hz/50%, then issue `PWMIOC_SETCHARACTERISTICS` with 400 Hz/25%
without STOP, START or close between requests. Reverse the transition too.

Trigger on the transition and inspect individual cycles, not averaged duty.
Compare-driven cycles should retain the old complete tuple or use the new
complete tuple; no new short period may contain the old oversized compare.
Record endpoint-mode transitions separately under the limitation above.

Archive board/core, ELF hash, command transcript, probe GPIO, clock and high/low
levels, screenshots/raw captures and measured period/high-time/pulse count.

## Bounded command/register evidence

The [2026-10-12 CR8-0 transcript](../evidence/rzv2h-pwm-register-transcript-261012.txt)
records 16 passing cases on an RTT diagnostic image: four devices, continuous
frequency/duty and forced endpoint registers, stopped outputs, ten-pulse
software completion, finite endpoint rejection and post-test shell liveness.
Its exact ELF hash and RAM-load/recovery provenance are recorded there.

For PWM0 at 1 kHz/25%, CPU reads showed GTCR.CST=1, GTPR=199999 and
GTCCRA=49999, with a changing GTCNT. After the bounded run, CST=0 and
GTIOR=0. This proves timer configuration and software lifecycle, without
establishing electrical pin levels, waveform accuracy or physical pulse count.
Separate commands exercised stop/restart; live-update ioctl transitions were
not tested. The board was not reset or cold-cycled during this run.

The [oneshot startup transcript](../evidence/rzv2h-pwm-oneshot-transcript-261012.txt)
adds the stock `pwm-oneshot` wrapper's successful ten-pulse return and 36 RTT
shell/register cases. Each device completed counts 1/2/10/100, rejected finite
endpoint duty, and ran continuous PWM after finite completion. CPU reads
confirmed the slower finite run's compare interrupt, period and compare value;
every case ended with CST=0, GTIOR=0, GTINTAD=0 and no PWM task. Both exact
images and their load provenance are recorded in the transcript. The earlier
GPT fixes were retained; no new firmware change was needed for this run.

## Unresolved questions

Physical pin results and transition captures remain pending.
