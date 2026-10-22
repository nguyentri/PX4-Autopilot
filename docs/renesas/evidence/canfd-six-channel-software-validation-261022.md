# Six-channel CAN-FD software validation — 2026-10-22

The NuttX lower half and RDK board integration now support hardware channels
0..5 concurrently. **No hardware operation or physical validation was performed.**
This extends the earlier [connected-test checkpoint](canfd-connected-software-validation-261022.md);
its archived source/build state remains historical. The driver's bounded-on-target
tier still refers only to the historical HW0 internal loopback.

## Cause and repair

The prior implementation declared a hardware bound of six but instantiated
only HW0/HW1/HW3, stored two FIFO owners and scanned two FIFOs. Kconfig and
board registration prohibited HW1 with HW3 because both claimed can1. The
pre-fix all-six production-execution fixture failed at that board `#error`;
its exact output is retained in the plan's `before-tests.log`.

The repair adds HW2/HW4/HW5 instances, capability/config symbols and native
pin selections, removes the HW1/HW3 restriction using unique nodes/FIFOs,
and expands RX ownership/dispatch to six slots. Existing lifecycle, public
status/cancel ABI, generic upper half and sample behavior are preserved.
All optional channels remain default-off.

| Hardware channel | TX / RX, PSEL5 | Device / RX FIFO | Transceiver control |
|------------------|----------------|------------------|---------------------|
| 0 | P80 / P81 | can0 / FIFO0 | Onboard CAN1, PA2 |
| 1 | P82 / P83 | can3 / FIFO3 with HW3; legacy can1 / FIFO1 without HW3 | External owner; exclusive with SCI9 |
| 2 | P84 / P85 | can2 / FIFO2 | External owner |
| 3 | P86 / P87 | can1 / FIFO1 | Onboard CAN2, PA3 |
| 4 | P42 / P43 | can4 / FIFO4 | External owner |
| 5 | P46 / P47 | can5 / FIFO5 | External owner |

HW0/HW3 paths used by `rzv_canfd` are preserved. Pad mux definitions for the
other channels establish SoC selection, not RDK connector routing or fitted
transceivers. Cancellation still requires an owned isolation callback and
one usable TX slot; callback-free expansion channels return ENOTSUP.
See [current usage and wiring](../peripherals/canfd.md).

## Reference verification

The user supplied hardware-manual §7.9's channel n=0..5 register scope.
The implementation was cross-checked against local core-matched primary
sources under `refs/rzv2h_evk/can_fd/can_fd_rzv2h_evk_cr8_0_ep/e2studio/`:

- `rzv/fsp/src/bsp/mcu/rzv2h/cr/bsp_feature.h`: six channels, one instance,
  64-entry TX channel stride.
- CMSIS `R9A09G057H/cr/iodefines/canfd_iodefine.h`: every channel's nominal,
  control, status, error and FD register offsets; TX control/status/access,
  enable-bank and AFL-count locations. These compile as static assertions.
- `bsp_irq_sense.h`: channel error IRQSEL354..359 and TX368..373, compared
  with native IRQ aliases for all six channels. No ELC namespace substitution.
- Native `hardware/rzv2h/rzv2h_pinmap.h`: expansion pad mux definitions.
  EVK `pin_data.c` was not used for RDK pins.

The controller has eight global RX FIFOs; this implementation uses six.
All-six count registers `[0..2]` are `0x00010001`. AFL entries remain ordered
by hardware channel and map to descriptor-selected FIFOs, including sparse
sets with high channels and absent lower channels.

## Host and review evidence

| Test command under `test/` | Passed |
|--------------------------|--------|
| `rzv2h-canfd-tx-lifecycle-runtime-test.py` | 16 |
| `rzv2h-canfd-sample-contract-test.py` | 8 |
| `rzv2h-register-base-contract-test.py` | 2 |
| `rzv2h-driver-unwind-runtime-test.py` | 4 |
| `rzv2h_board_gpio_contract_test.py` | 7 |
| `rzv2h-optional-config-contract-test.py` | 3 |

Run each with `python3 test/<name>`. Total: **40 cases across six suites**.
The new lifecycle variants execute the production driver, board glue and
real upper-half write/completion/close code with modeled MMIO/IRQs:
all-six external mode, all-six internal loopback, HW4/HW5-only, sparse
HW2/HW5, and legacy HW0/HW1. They verify unique nodes/FIFOs, AFL layout,
IRQ sources, all six 64-byte FD TX/RX paths and sibling-preserving close/reopen.
The previous missing-IRQ, reset-timeout, stale-event, quarantine, error and
bounded cleanup regressions continue to pass. The app harness uses real
public headers with CAN_ERRORS both disabled and enabled.

The incremental source received a local code-review-skill pass; documentation
received a separate delegate review. Native NuttX style checks pass for the
touched C/board/API files; the scoped repository driver checker reports zero
findings. Diff whitespace checks pass. Existing register-header style debt
is not expanded by this repair. No independent full code-review-agent pass
or target execution is claimed for this extension.

## Clean build receipts

Four unchanged shipping profiles were rebuilt cleanly through the repository
build script, followed by a temporary validation configuration containing all
six channel selections. All five commands exited zero. Only the existing
recursive-make jobserver warning appears; there are no compiler/linker warnings.

| Archive | Selected hardware channels | ELF bytes | ELF SHA-256 |
|---------|----------------------------|-----------|-------------|
| `canfd` | 0 | 1743916 | `826ae27045b6343dc78324ac14e71f3786073fc486ef950fb8d1bbc64b0ff32f` |
| `canfd-rtt` | 0 | 1773204 | `6a1f3d39e713e9693ec1820c4695b126378a991ae9cee5c5efe60eba5bf1f37a` |
| `canfd-dual` | 0, 3 | 1771128 | `12e68105f2557e582bd6d5b820f84b8124efd647b2873ab2f2e7ca65dd7bc457` |
| `canfd-ext` | 0, 3 | 1786440 | `da3521e95cb30a47696fb0d4424ed366e66d821087ce15021569e40085767848` |
| `all-six` | 0, 1, 2, 3, 4, 5 | 1775456 | `4b65554203328fdf74c45a8a219da99dd15cf2157b09ad5917adada328ef95fa` |

The all-six image contains all six `g_rzv_canfdN_priv` instance symbols.
The connected `rzv_canfd_main` symbol is present only in `canfd-ext`. Its
resolved config still selects HW0/HW3, external mode, one usable software
TX slot, extended IDs and RTT input/output.

Local archive: `plans/261022-0603-canfd-six-channels/artifacts/<archive>/`.
Each retains exact ELF, binary/hex/S-record/map and resolved config, complete
log, command, compiler/linker version, parent/submodule revisions and dirty
state, actual tracked binary patches, and copies/hashes of untracked build
inputs. All five have identical production tracked patches and common input
hashes. The temporary `canfd-six-validation/defconfig` is retained in its
receipt, then removed from the board source tree; no shipping profile was
added. The temporary build stamp was removed too. The mutable build tree
contains that validation image; run a normal clean profile build before an
incremental build. For any approved connected test, use the retained
`artifacts/canfd-ext/nuttx.elf` and its hash above.

Toolchain: arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009. Source baseline
plus retained dirty patches:

| Tree | HEAD |
|------|------|
| parent | `b2383bb2f42e28589a7766095de95c5b28218eaa` |
| nuttx | `cc10d09f984d993e39b7ba04cfba9b15425cf75c` |
| apps | `8b191ab6887ce0f2ce093055b5c1342438428e42` |

`plans/` is gitignored. Preserve or transfer its artifact archive explicitly
when handing off physical testing. No commit/push occurred. The supplied RDK
CAN schematic was preserved.

## Physical gates

The source/build result does not qualify external transceivers, pad access,
termination, normal-mode IRQ delivery or measured bitrate. The prior approved
CAN1/CAN2 physical test procedure remains pending separate authorization.
Other channels additionally require fitted-board routing and externally
owned transceiver integration. No production-readiness claim is made.
