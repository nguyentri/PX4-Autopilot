# GY-912 Sensor Board - Quick Test Reference

## Build and Flash
```bash
cd /home/tringuyen/px4_ra8/PX4-Autopilot
make distclean
make renesas_fpb-ra8e1_default
# Flash using J-Link or e² studio
```

## Quick Test Commands

### Test ICM20948 (IMU)
```bash
icm20948 start -s
icm20948 status
listener sensor_accel
listener sensor_gyro
```

**Expected**: Continuous data stream
- Accel Z-axis: ~9.8 m/s² (when level)
- Gyro: ~0 (when stationary)

### Test BMP388 (Barometer)
```bash
bmp388 start -s
bmp388 status
listener sensor_baro
```

**Expected**: Continuous data stream
- Pressure: ~101325 Pa (sea level)
- Temperature: 15-30°C

### Check System
```bash
uorb top                    # Verify publishing rates
dmesg                       # Check for errors
ps                          # Verify drivers running
```

## Success Indicators

### ✅ ICM20948 Working
- `sensor_accel` publishes at ~4500 Hz
- `sensor_gyro` publishes at ~9000 Hz
- FIFO empty interval > 0

### ✅ BMP388 Working
- No "no device on bus" error
- `sensor_baro` publishes data
- Reasonable pressure/temperature values

## Common Issues

### Issue: "no device on bus"
**Solution**: Check SPI configuration in `spi.cpp`
- Verify `ra_spi_get_dev_config()` is implemented
- Check frequency/mode settings

### Issue: No data (FIFO empty)
**Solution**: Check DRDY interrupt
- Verify `GPIO_SPI1_IMU_DRDY` configured
- Check interrupt is triggering

### Issue: Wrong values
**Solution**: Check SPI mode
- Both sensors require Mode 3 (CPOL=1, CPHA=1)
- Verify in `ra_spi_get_dev_config()`

## Debug Commands
```bash
# Check GPIO configuration
gpio -l | grep P40[789]

# Check interrupts
cat /proc/interrupts

# Check SPI bus
ls -l /dev/spi*
```

## Configuration Summary

| Sensor   | Frequency | Mode   | CS Pin | DRDY Pin |
|----------|-----------|--------|--------|----------|
| ICM20948 | 7 MHz     | Mode 3 | P408   | P409     |
| BMP388   | 10 MHz    | Mode 3 | P407   | -        |

## Files Modified
- `boards/renesas/fpb-ra8e1/src/spi.cpp` - Added `ra_spi_get_dev_config()`

## Original Error Messages (Should Be Gone)
- ❌ "bmp388: no instance started (no device on bus?)"
- ❌ "icm20948: FIFO empty: 0 events"
- ❌ No data in `sensor_accel` / `sensor_gyro` topics
