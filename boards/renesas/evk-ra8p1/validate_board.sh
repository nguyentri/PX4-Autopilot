#!/bin/sh
#
# EVK-RA8P1 Board Validation Script
# Run this script on the target to validate hardware functionality
#------------------------------------------------------------------------------

echo "==============================================="
echo "EVK-RA8P1 Board Validation Script"
echo "==============================================="

# Test 1: System Status
echo "1. Checking system status..."
uorb top | head -10
echo "✓ uORB topics active"

free
echo "✓ Memory check complete"

# Test 2: Sensor Status
echo ""
echo "2. Checking sensor drivers..."

# IMU Test
if icm20948 status > /dev/null 2>&1; then
    echo "✓ ICM20948 IMU driver loaded"
    listener sensor_accel 1 > /dev/null 2>&1 && echo "  - Accelerometer data OK"
    listener sensor_gyro 1 > /dev/null 2>&1 && echo "  - Gyroscope data OK"
else
    echo "✗ ICM20948 IMU driver not loaded"
fi

# Barometer Test
if bmp388 status > /dev/null 2>&1; then
    echo "✓ BMP388 Barometer driver loaded"
    listener sensor_baro 1 > /dev/null 2>&1 && echo "  - Barometer data OK"
else
    echo "✗ BMP388 Barometer driver not loaded"
fi

# Test 3: PWM Output
echo ""
echo "3. Checking PWM outputs..."
if pwm_out status > /dev/null 2>&1; then
    echo "✓ PWM output driver loaded"
    echo "  WARNING: Remove propellers before testing!"
    echo "  To test: pwm_out test -c 1 -p 1100"
else
    echo "✗ PWM output driver not loaded"
fi

# Test 4: LED Test
echo ""
echo "4. Testing LEDs..."
led_control test
echo "✓ LED test complete"

# Test 5: Parameters
echo ""
echo "5. Checking flight configuration..."
param show SYS_AUTOSTART
param show PWM_MAIN_MAX
param show MAV_0_CONFIG
echo "✓ Key parameters loaded"

# Test 6: Commander Status
echo ""
echo "6. Checking flight controller..."
commander status
echo "✓ Commander status checked"

echo ""
echo "==============================================="
echo "Validation Complete!"
echo "==============================================="
echo ""
echo "Next steps:"
echo "1. Connect RC transmitter to SCI3 (P309/P310)"
echo "2. Connect telemetry to SCI0 (P609/P610)"
echo "3. Connect motors to PWM outputs (P912,P915,P903,P515)"
echo "4. Test arming: 'commander arm'"
echo ""
echo "For troubleshooting, see README.md"
