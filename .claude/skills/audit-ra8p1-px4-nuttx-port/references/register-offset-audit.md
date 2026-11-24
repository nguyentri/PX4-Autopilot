# Parameterized register and channel macro audit

Load for an RA8P1 hardware-header, clock/MSTP, lower-half, or NuttX driver
review involving repeated register offsets or peripheral channels.

## Decision rule

Use a parameterized offset/address macro only for an indexed register series
proven by `refs/ra8p1/R7KA8P1KF_core0.h` and FSP use. Keep a one-off register as
one named offset macro. Do not parameterize across a reserved gap, non-uniform
stride, mixed access behavior, or a special final member.

Before proposing a change, record the device-header struct/member names, index
domain, first offset, stride, width, access direction and reserved entries.
A regular-looking name alone does not prove contiguous hardware.

## Naming in this tree

RA8P1 headers live in `arch/arm/src/ra8/hardware/ra8p1/ra_<ip>.h` and use an
`R_<IP>_` prefix, for example:

```c
#define R_SRAM_SRAMCR_OFFSET(m)   (first_offset + ((m) * stride))
#define R_IIC_CH_BASE(ch)         (R_IIC_BASE + ((uint32_t)(ch) * R_IIC_CH_STRIDE))
#define R_IIC_ICCR1(n)            (R_IIC_CH_BASE(n) + R_IIC_ICCR1_OFFSET)
```

Preserve that convention. Parenthesize each argument and evaluate it once.
State the valid index range at the call site.

## Base aliases

Many RA8P1 headers define `R_<IP>_BASE` twice: `0x4xxxxxxx` by default and
`0x5xxxxxxx` when `CONFIG_RA_TZ_NONSECURE_BUILD` is set. The device header
expresses the same rule as `0x4xxxxxxx + BASE_NS_OFFSET`, where the offset is
`BSP_FEATURE_TZ_NS_OFFSET` only under `_RA_TZ_NONSECURE`. Verify which branch
the selected core/config takes, that every derived address uses the same
alias, and that the NuttX gate matches the image's TrustZone state.

## Channel-address patterns

- Stride form (`R_<IP>_CH_BASE(ch)`): valid only when the device header shows a
  fixed channel stride across all channels in the domain. Check the channel
  domain at callers; the macro accepts runtime values.
- Token-pasted form (`R_<IP>##ch##_BASE`): only for compile-time literal
  channel tokens. If callers may pass a macro, require a two-stage helper and
  test both a literal and a macro-expanded argument.
- Runtime channel without fixed stride: require a validated table, switch, or
  lower-half operation.

## RA8E1 interaction

`hardware/ra8e1/` defines many of the same macro names. Confirm the RA8P1 file
is the one included for the selected build and that a fix in a shared
`ra_<module>.c` does not depend on a macro that differs between the two groups.

## NuttX driver and app boundary

Keep MMIO and RA8 hardware headers in the arch/lower-half layer. NuttX drivers
consume the lower-half/public interface; apps use the device path or public
API. A board bring-up config may touch a private arch interface only when its
defconfig confines it to validation and the report records the exception.
