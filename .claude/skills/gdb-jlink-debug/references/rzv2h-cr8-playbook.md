# RZ/V2H CR8 J-Link Playbook

Use this reference for R9A09G057H CR8_0/CR8_1 when a manual GDB session is
needed: task-required loads with breakpoints and fault capture, covered by the
project's standing board authorization (see `rzv2h-repo-tooling-and-scripts.md`). For a plain read of a
running core use `platforms/nuttx/Debug/jlink-gdb-oneshot.py` instead.

## Server

Start the J-Link GDB server in its own process. Take the serial from
`jlink-debug-preflight.py --print-serial`; never guess a probe or core.

```bash
/opt/SEGGER/JLink/JLinkGDBServerCLExe \
  -select usb=<probe-sn> \
  -device R9A09G057H44_R8_0 \
  -if SWD -speed auto -LocalhostOnly 1 -powertarget 0 \
  -noreset -noir \
  -port 50000 -swoport 50001 -telnetport 50002 \
  -singlerun -nogui
```

CR8_1 is `R9A09G057H44_R8_1`. Keep `-noreset -noir` unless a diagnosed task
requires a reset: without them the server resets the core and re-initialises its
registers on connect. Wait for "Waiting for GDB connection" before starting
GDB, then grep the server output for `Resetting via Reset pin|cold reset
sequence|DBGEN is not asserted`. A reset marker means the core was reset;
DBGEN alone means the core runs no image. Report either.

## Read-only attach and capture

```bash
gdb-multiarch -q -batch <elf> \
  -ex 'set pagination off' \
  -ex 'target remote :50000' \
  -ex 'monitor halt' \
  -ex 'info registers' \
  -ex 'bt' \
  -ex 'x/1wx 0x12801c08' \
  -ex 'x/1bx 0x12801c1c' \
  -ex 'x/1wx 0x12801c1c' \
  -ex 'x/1wx 0x10420d28' \
  -ex 'detach'
```

For the SCI4 investigation these addresses are:

| Address | Register |
|---|---|
| `0x12801c08` | SCI4 CCR0 |
| `0x12801c1c` | SCI4 CESR, byte and word views |
| `0x10420d28` | CPG BUS11 MSTOP |

Generate/decode such reads from `rzv2h.svd` instead of hand-typing addresses:
`platforms/nuttx/Debug/svd_register_tool.py cmd gdb R_SCI4.CCR0 R_SCI4.CESR`, then pipe the
GDB output through `svd_register_tool.py decode-log`.

The CPU's result from code execution is authoritative. J-Link `0xaa` or
`0xaaaaaaaa` can be debug-port fill when an MMIO access is inaccessible.

## Load and RIST capture

Under the project's standing authorization for the requested debug task, do
not ask for separate load/execution permission. Prefer the linked guarded
loader for ordinary loads. The reset example below applies only when reset is
needed and its effect on peer images has been accounted for. Resolve
the breakpoint from this ELF with `disassemble`, `info line`, or an existing
source breakpoint. The raw address below is an example, not reusable input.

```bash
gdb-multiarch -q -batch <elf> \
  -ex 'set pagination off' \
  -ex 'target remote :50000' \
  -ex 'monitor reset' \
  -ex 'load' \
  -ex 'hbreak *<address-after-rist-loop>' \
  -ex 'continue' \
  -ex 'printf "RIST_DONE_PC=%#x\n", $pc' \
  -ex 'x/1wx 0x12801c08' \
  -ex 'x/1bx 0x12801c1c' \
  -ex 'x/1wx 0x12801c1c' \
  -ex 'x/1wx 0x10420d28' \
  -ex 'detach'
```

Before `continue`, verify `info breakpoints` shows a hardware breakpoint.
Capture the source line, current ELF build, and raw reads in the report.

## Data abort capture

Set a hardware breakpoint on `arm_dataabort`; on hit, record the handler
arguments and saved exception context.

```gdb
hbreak arm_dataabort
continue
printf "REGS=%p DFAR=%#x DFSR=%#x\n", regs, dfar, dfsr
x/17wx regs
printf "FAULT_PC=%#x\n", regs[15]
x/12i regs[15]-24
bt
```

ARMv7-R synchronous permission faults identify their address through DFAR.
For DFSR status `0x16` (asynchronous external abort), delivery can be delayed
and DFAR is not a reliable causal address. Correlate the last memory writes,
MPU region attributes, reset type, and bus/peripheral error state.

## Optional abort-unmask experiment

Changing CPSR is a target-state mutation. Use it under the project grant
only when the debug task requires localizing a delayed asynchronous abort:

```gdb
hbreak arm_boot
continue
printf "BOOT_PC=%#x CPSR_BEFORE=%#x\n", $pc, $cpsr
set $cpsr = $cpsr & ~0x100
hbreak arm_dataabort
continue
```

Do not use this as a production fix. Restore the board with a normal reset or
power cycle after the experiment.

## Interpreting the RZ/V2H MPU result

The working CR8 map includes peripheral region 4:

```text
base 0x10000000, size 256 MiB, Device Shareable, execute-never
```

This covers SCI4 at `0x12801c00`. When peripheral MMIO is inaccessible, audit
MPU setup before editing SCI registers, clock dividers, or UART delays.

## Sources

- GDB remote workflow: <https://opencoursehub.cs.sfu.ca/bfraser/grav-cms/cmpt433/guides/files_byai/DebuggingGuide.pdf>
- Qualcomm GDB-server reference supplied by the user: <https://docs.qualcomm.com/doc/80-70029-12/topic/debug_using_gdbserver.html>
