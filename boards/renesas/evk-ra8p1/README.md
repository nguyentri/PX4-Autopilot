## Debugging

### Flash and Erase
```bash
rfp-cli -d RA -tool jlink:1083687676 -if swd -erase-chip
```

### Decode Exception Backtrace
When an exception occurs, use addr2line to decode function addresses:
```bash
arm-none-eabi-addr2line -e build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf -f -i <addresses>
```

Example:
```bash
arm-none-eabi-addr2line -e build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf -f -i 0x02010c1a 0x020abc42 0x020abc86 0x020ab1ee 0x0200c5ee 0x020050ac 0x0200a4b8 0x020037f8
```

### Common Issues

**Invalid PC address (0x020001xx range)**:
- Indicates jump to bootloader/reset vector region
- Usually caused by uninitialized or corrupted function pointer
- Check GPIO configuration macros are defined correctly
- Verify all peripheral initialization completes before use