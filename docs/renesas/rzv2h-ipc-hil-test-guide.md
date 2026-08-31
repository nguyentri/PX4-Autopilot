# RZ/V2H Raw IPC — HIL Test Guide (`/dev/ipcc1` CR8-0 ↔ CR8-1)

Repeatable hardware-in-the-loop procedure to bring up the CR8-0 ↔ CR8-1 raw
IPC link and run the `ipctest` ping/echo acceptance (100/100, both directions)
on live silicon. Companion to the address-contract proof in
[rzv2h-three-core-ipc-artifacts.md](./rzv2h-three-core-ipc-artifacts.md) and the
probe/reset rules in
[rzv2h-three-core-jlink-contract.md](./rzv2h-three-core-jlink-contract.md).

## What the link does

- `/dev/ipcc1` = raw MHU-B-NS doorbell IPC, Link 1, CR8-0 ↔ CR8-1.
- CR8-0 is the **initiator** (owns the recovery epoch), CR8-1 the **responder**
  (adopts the initiator epoch). The responder converges automatically on the
  doorbell/poll path — no manual `--recover` on CR8-1.
- Boot auto-echo waits for a ready, non-degraded link before echoing, so it
  does not spin on a half-open link.

## Prerequisites

- Built images for both cores, verified against the address contract first
  (see the artifacts doc's Repro Commands). Load order matters — verify both
  before touching the target.
- `gdb-multiarch` on the host. Do **not** use `arm-none-eabi-gdb` here; its
  bundled Python is broken in this environment.
- SEGGER J-Link tools: `JLinkGDBServerCLExe` (for the volatile load) and
  `JLinkExe` (for RTT bridging). Know your probe serial number and use SWD.
- Core device selectors: CR8-0 = `R9A09G057H44_R8_0`, CR8-1 =
  `R9A09G057H44_R8_1`.
- RTT control blocks: CR8-0 `0x081A0000`, CR8-1 `0x081E0000`.

Helper GDB scripts live in `platforms/nuttx/Debug/`:

| Script | Purpose | Mutating? |
|---|---|---|
| `rzv2h-ipc-hil-readonly.gdb` | Attach, dump regs/bt, read GIC SPI target bytes | no |
| `rzv2h-ipc-hil-loadstart.gdb` | Volatile RAM load + PC=`__start` + `go`, no reset | yes (RAM + run) |
| `rzv2h-ipc-hil-verify-resume.gdb` | Brief halt to confirm a core is running + SPIs retargeted, then resume | no lasting change |
| `rzv2h-ipc-hil-rtt-hold.gdb` | Point the probe at the RTT block and hold it so an RTT client can drive NSH | no |

## Procedure

### 1. Verify the address contract (read-only, off-target)

Run the three `--expect-sha256` commands from the artifacts doc. Each must print
`RESULT=ADDRESS_CONTRACT_VERIFIED`. A mismatch means the image is not the one
under review — stop and rebuild/re-hash.

### 2. Load CR8-0 first (initiator)

The initiator must publish the recovery headers before the responder boots so
the responder adopts them at bring-up. Start one J-Link GDB server for the
CR8-0 device selector, then:

```sh
gdb-multiarch -q -batch <cr8_0-elf> -x platforms/nuttx/Debug/rzv2h-ipc-hil-loadstart.gdb
```

This writes the PT_LOAD segments to core-local RAM, sets PC to `__start`,
resumes, and detaches — **no `monitor reset`** (a reset here has unmeasured
SoC-wide scope while a peer image may already be resident).

### 3. Load CR8-1 last (responder)

Restart the GDB server for the CR8-1 device selector and repeat the loadstart
with `<cr8_1-elf>`. On boot the responder finds the initiator's RECOVERING
headers and adopts the epoch, coming up ready with a live auto-echo.

### 4. Drive `ipctest` over RTT

RTT is bridged with **`JLinkExe`** on `127.0.0.1:19021`, not JLinkGDBServer
(the GDB server cannot bridge RTT). Use `rzv2h-ipc-hil-rtt-hold.gdb` to point
the probe at the CR8-0 RTT control block (`0x081A0000`) and hold it while a
separate `JLinkExe` session connects on port 19021 to drive NSH. On the CR8-0
NSH prompt over RTT:

```sh
ipctest --recover -d /dev/ipcc1
ipctest --ping    -d /dev/ipcc1 -n 100 -s 64
```

`--recover` performs the bounded two-sided rendezvous (initiator publishes a
fresh epoch and doorbells; the responder adopts). Running `--recover` again on
an already-healthy link returns immediately — it does not re-arm the wait.

### 5. Expected output

```
IPCTEST_RESULT core=CR8-0 mode=recover dev=/dev/ipcc1 status=pass
...
ipctest ping: 100/100 pass, 0 timeout
IPCTEST_RESULT core=CR8-0 mode=ping dev=/dev/ipcc1 status=pass pass=100 expected=100 timeouts=0
```

Final stats: `epoch=2 ready=1 degraded=0 tx=100 rx=100 invalid_headers=0
invalid_entries=0`, and no data abort / stack-pointer fault.

## Interpreting failures

| Symptom | Likely cause |
|---|---|
| `--recover` returns `ETIMEDOUT` (116), link `degraded=1` | Responder never adopted — check load order (CR8-0 before CR8-1) and that both images carry the convergence fix. |
| Echo prints `echo transport error` and exits | Poll returned `POLLERR` — the link diverged in a way that is not a clean recovery. Re-run `--recover` on the initiator. |
| Unexpected-IRQ panic on a core | MHU SPI not retargeted to the local core. Confirm with `rzv2h-ipc-hil-verify-resume.gdb` that the SPI target bytes (INTID 347/348/359/360) hold the local CPU mask, not `0x01`. |
| Data abort / `User Stack pointer is not within the stack` on `--ping` | Demo task stack too small. `CONFIG_EXAMPLES_RZV_IPC_DEMO_STACKSIZE` must be 4096 for the two-buffer ping frame. |

## Safety

Treat the target as live hardware: verify the address contract before any load,
attach read-only first, and never issue `monitor reset` after an image is
resident until the reset scope is measured. Detach at the end and leave the
cores running. Do not copy ELF contents, memory dumps, RTT buffers, or probe
serial numbers outside the workspace.
