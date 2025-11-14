# ICM20948 DRDY Quick Verification Checklist

## Current Status: ✅ DRDY is Properly Configured

### Configuration Verification

#### ✅ 1. DRDY Pin Passed to Driver
**Location**: `boards/renesas/fpb-ra8e1/src/spi.cpp` (Line 78)
```cpp
initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
             SPI::CS{GPIO::Port4, GPIO::Pin8},
             SPI::DRDY{GPIO::Port4, GPIO::Pin9}),  // ← Correctly configured
```
**Status**: CORRECT - DRDY parameter is included

#### ✅ 2. Hardware Pin Definition
**Location**: `boards/renesas/fpb-ra8e1/src/board_config.h` (Line 110)
```c
#define GPIO_SPI1_IMU_DRDY  GPIO_IRQ6_P409
```
**Status**: CORRECT - Maps to external IRQ6

#### ✅ 3. Pin Initialization
**Location**: `boards/renesas/fpb-ra8e1/src/init.c` (Line 145)
```c
px4_arch_configgpio(GPIO_SPI1_IMU_DRDY);
```
**Status**: CORRECT - Pin is configured during board init

#### ✅ 4. Platform Function Available
**Location**: `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_gpio.c` (Line 655)
```c
int ra_gpiosetevent(uint32_t pinset, bool rising, bool falling, ...)
```
**Status**: CORRECT - Function is implemented

#### ✅ 5. SPI Configuration Callback
**Location**: `boards/renesas/fpb-ra8e1/src/spi.cpp` (Line 205)
```cpp
extern "C" const struct ra_spi_ext_dev_config_s *ra_spi_get_dev_config(...)
```
**Status**: CORRECT - Per-device SPI settings configured (7 MHz, Mode 3)

## Testing Commands

### Build and Flash
```bash
cd /home/tringuyen/px4_ra8/PX4-Autopilot
make distclean
make renesas_fpb-ra8e1_default
# Flash to board
```

### Test Sequence

#### Step 1: Start ICM20948 Driver
```bash
nsh> icm20948 start -s
```

**Expected Output**:
```
INFO [SPI_I2C] Running on SPI Bus 1
INFO [ICM20948] Configured DRDY interrupt on GPIO 0x... (if debug added)
```

#### Step 2: Check Driver Status
```bash
nsh> icm20948 status
```

**Expected Output**:
```
INFO [SPI_I2C] Running on SPI Bus 1
icm20948:
  - FIFO empty interval: XXX us (should be > 0)

Performance Counters:
  - DRDY missed: 0 (or very low number)
  - FIFO empty: XXX events
  - FIFO overflow: 0
```

**❌ If "FIFO empty interval: 0"**: DRDY interrupt is NOT working

#### Step 3: Monitor Data Flow
```bash
nsh> listener sensor_accel
```

**Expected Output**:
```
TOPIC: sensor_accel
timestamp: <incrementing>
x: <value>
y: <value>
z: ~9.8 (when level)
```

**Frequency**: Should update at ~4500 Hz

```bash
nsh> listener sensor_gyro
```

**Expected Output**:
```
TOPIC: sensor_gyro
timestamp: <incrementing>
x: ~0 (when stationary)
y: ~0
z: ~0
```

**Frequency**: Should update at ~9000 Hz

#### Step 4: Check uORB Publishing Rates
```bash
nsh> uorb top
```

**Expected Output**:
```
sensor_accel0    4500 Hz    # ← Should be around this
sensor_gyro0     9000 Hz    # ← Should be around this
```

## Debug Enhancement (Optional)

If DRDY is not working, add debug output to verify interrupt setup:

### Add to ICM20948.cpp

**Location**: After line 492 in `DataReadyInterruptConfigure()`

```cpp
bool ICM20948::DataReadyInterruptConfigure()
{
    if (_drdy_gpio == 0) {
        PX4_ERR("DRDY GPIO is not configured (zero)");
        return false;
    }

    PX4_INFO("Configuring DRDY: GPIO=0x%08x, pin=P409, IRQ6", _drdy_gpio);

    int ret = px4_arch_gpiosetevent(_drdy_gpio, true, false, true,
                                    &DataReadyInterruptCallback, this);

    if (ret == 0) {
        PX4_INFO("DRDY interrupt configured successfully");
    } else {
        PX4_ERR("DRDY interrupt configuration failed: %d", ret);
    }

    return ret == 0;
}
```

**Add to DataReady()** (after line 478):

```cpp
void ICM20948::DataReady()
{
    static uint32_t interrupt_count = 0;
    static hrt_abstime last_log_time = 0;

    interrupt_count++;

    // Log every 1000 interrupts or every second
    hrt_abstime now = hrt_absolute_time();
    if (interrupt_count % 1000 == 0 || (now - last_log_time) > 1000000) {
        PX4_INFO("DRDY IRQ count: %u, rate: ~%.1f Hz",
                 interrupt_count,
                 interrupt_count * 1000000.0f / (now - last_log_time));
        last_log_time = now;
        interrupt_count = 0;
    }

    // Original code
    if (++_drdy_count >= _fifo_gyro_samples) {
        _drdy_timestamp_sample.store(hrt_absolute_time());
        _drdy_count -= _fifo_gyro_samples;
        ScheduleNow();
    }
}
```

## Troubleshooting Decision Tree

### Issue: No sensor data
```
Check 1: Does driver start?
  YES → Check 2
  NO  → Verify SPI configuration (ra_spi_get_dev_config)

Check 2: Does "icm20948 status" show FIFO interval > 0?
  YES → Check 3
  NO  → DRDY interrupt not working - see below

Check 3: Does "listener sensor_accel" show data?
  YES → SUCCESS! ✅
  NO  → Check SPI communication (frequency, mode)
```

### Issue: DRDY Interrupt Not Working

**Symptom**: `icm20948 status` shows "FIFO empty interval: 0 us"

**Diagnosis Steps**:

1. **Check Pin State**:
   ```bash
   nsh> gpio -l | grep 409
   ```
   Expected: Pin configured as input with interrupt

2. **Verify ICU/IRQ Setup**:
   ```bash
   nsh> cat /proc/interrupts | grep IRQ6
   ```
   Should show IRQ6 if available in NuttX

3. **Add Debug Output**: See "Debug Enhancement" section above

4. **Check Sensor INT Pin Configuration**:
   The ICM20948 must be configured to assert DRDY. This is done in register setup:
   - `INT_ENABLE_1`: RAW_DATA_0_RDY_EN bit must be set
   - `INT_PIN_CFG`: Configure pin polarity

5. **Hardware Check**:
   - Use oscilloscope on P409
   - Should see pulses at ~9 kHz when sensor is running
   - Voltage should toggle between 0V and 3.3V

## Expected Behavior Summary

### ✅ When DRDY is Working Correctly

1. **Driver Startup**:
   - `DataReadyInterruptConfigure()` called during CONFIGURE state
   - `_data_ready_interrupt_enabled` set to true
   - No error messages

2. **Runtime Operation**:
   - `DataReady()` ISR called at sensor sample rate (~9 kHz for gyro)
   - `ScheduleNow()` triggers FIFO read when enough samples accumulated
   - Data flows to uORB topics at configured rates

3. **Status Output**:
   - FIFO empty interval > 0 (typically ~1250 µs = 800 Hz)
   - DRDY missed count = 0 or very low
   - sensor_accel publishes at ~4500 Hz
   - sensor_gyro publishes at ~9000 Hz

### ❌ When DRDY is NOT Working

1. **Driver Falls Back to Polling**:
   - Uses periodic timer instead of interrupts
   - Less efficient, higher CPU usage
   - May miss samples

2. **Status Indicators**:
   - FIFO empty interval might be 0
   - May see "DRDY missed" counter incrementing
   - Publishing rates may be irregular

## Architecture Summary

```
Hardware:          ICM20948 → DRDY Pin (active HIGH when data ready)
                      ↓
Pin:              P409 (PORT4, PIN9)
                      ↓
IRQ:              External IRQ6
                      ↓
ICU:              Interrupt Control Unit
                      ↓
NuttX:            ra_gpio_irq_handler()
                      ↓
Callback:         DataReadyInterruptCallback()
                      ↓
ISR:              ICM20948::DataReady()
                      ↓
Schedule:         ScheduleNow() → work queue
                      ↓
Read:             FIFORead() via SPI (7 MHz, Mode 3)
                      ↓
Publish:          sensor_accel, sensor_gyro uORB topics
```

## Conclusion

✅ **Configuration is CORRECT** - All components are properly set up:
- DRDY pin (P409/IRQ6) is defined
- Pin is passed to driver via `initSPIDevice()`
- Interrupt handler is implemented
- SPI settings are configured (7 MHz, Mode 3)

🔍 **Testing Required** - Build and test to verify:
- Interrupt registration succeeds
- DRDY ISR is being called
- Data flows to uORB topics

If issues persist after testing, the problem is likely in the ICU routing or sensor configuration, not the DRDY pin setup itself.
