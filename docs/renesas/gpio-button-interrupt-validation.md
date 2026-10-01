# P94 GPIO/TINT Button Interrupt Validation

**Date:** 2026-10-01
**Board/core:** RDK-RZ/V2H, CR8-0
**Config:** `rdk-rzv2h:nsh-leds`
**Evidence tier:** bounded on-target, user-confirmed button interrupt delivery

## Result and Evidence

After building and loading `nsh-leds`, the user initially reported that P94
button presses produced no callback or RTT logs despite successful attachment.
The supplied failing boot capture included:

```text
GPIO IRQ subsystem initialized
Button P94 (pinset=0x94000020) -> toggles LED0 (PB4)
P94 external interrupt (TINT) attached
Buttons initialized
```

After the INTC selector correction and hardware retest, the user confirmed:

> The external interrupt was fixed, record porting status: docs/renesas

This is the named record of that confirmation. The boot excerpt above belongs
to the failing run; no passing RTT transcript, live register capture, or exact
loaded ELF hash was supplied. The confirmation closes the reported P94 button
interrupt-delivery defect within this sample; it does not establish LED toggle
counts, release-edge behavior, timing, or stress reliability.

## Source Corrections

- `rzv_gpio.c` enables P94's GPIO interrupt-input ISEL gate on the TINT path,
  ISEL29_H bit 0 at `0x10412d4c`, keeps PM=`01` input mode and PMC=`0` GPIO
  mode, publishes callback state before GIC delivery, rejects duplicate
  attachments, and cleans up the gate on detach or attachment failure.
- `hardware/rzv_intc.h` corrects all 43 `INTR8SEL0..42` offsets from
  `0x012c..0x01d4` to the CMSIS range `0x0140..0x01e8`.
  At INTC base `0x10400000`, `INTR8SEL0` is `0x10400140`.
- The board sample selects P94 → GPIOINT68 → TINT → INTR8SEL → GIC.
  Its falling-edge callback
  is configured to toggle active-high LED0/PB4. Idle polling and register-dump
  instrumentation were removed.

The scope covers this CR8-0 GPIO/TINT route. Native IRQ peripheral pinmux,
other GPIO/TINT channels and edges, CR8-1 routing, and CM33 routing require
separate validation. Correcting a shared selector map does not validate every
peripheral that consumes it.

## Board Configuration

Use the named `GPIO_TINT_Px_y` input pinsets from `rzv2h_pinmap.h` for GPIO/TINT
board definitions. The 86 aliases cover the valid GP pins; each combines the
port/pin with `RZV_GPIO_INPUT | RZV_GPIO_TINT`. The P94 button definition is:

```c
#define BOARD_BUTTON1_GPIO  GPIO_TINT_P9_4
```

Its encoding remains `0x94000020`, preserving the validated GPIO/TINT route.
The existing `GPIO_IRQn_Px_y` definitions select native IRQ alternate
functions instead: `GPIO_IRQ4_P9_4` remains `0x9440000d` and is a separate route.
Add board-specific pull/filter flags only when required; event attachment
selects the trigger and allocates the TINT channel.

## Remaining Validation

- Archive the passing boot/press transcript, exact ELF SHA-256, source revisions,
  board revision, and load/reset procedure.
- Capture PM, PMC, ISEL, TSSR/TITSR, INTR8SEL, and GIC state for the loaded image.
- Record repeated press/release counts, debounce behavior, and physical PB4
  toggles; test attach/detach and error recovery.
- Validate cold boot, interrupt latency, and stress bounds before production use.

Build the same sample from the repository root with:

```bash
platforms/nuttx/NuttX/build.sh nsh-leds
```

## References

- [NuttX driver status](port-status-nuttx.md)
- [P94 validation checklist](validation-checklist.md#c4-p94-button-tint-retest)
- [GPIO setup fix journal](../journals/261001-p94-button-interrupt-fix.md)
- [INTC register header](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_intc.h)

## Unresolved Questions

Exact passing image/load provenance and measured edge/toggle/stress results
remain unrecorded.
