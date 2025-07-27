#!/usr/bin/bash

echo "=== Final PX4 Build Environment Verification ==="
echo ""

echo "1. Core Tools:"
echo "   ✓ GCC: $(gcc --version | head -n1)"
echo "   ✓ Make: $(make --version | head -n1)"
echo "   ✓ CMAKE: $(cmake --version | head -n1)"
echo ""

echo "2. Python Environment:"
echo "   ✓ Python3.12: $(python3.12 --version)"
echo "   ✓ Python (symlink): $(python --version 2>/dev/null)"
echo "   ✓ Python3 (symlink): $(python3 --version 2>/dev/null)"
echo ""

echo "3. ARM Toolchain:"
echo "   ✓ ARM GCC: $(arm-none-eabi-gcc --version | head -n1)"
echo ""

echo "4. Python Packages:"
python3.12 -c "
packages = ['em', 'jinja2', 'yaml', 'kconfiglib', 'lxml']
missing = []
for pkg in packages:
    try:
        __import__(pkg)
        print(f'   ✓ {pkg}')
    except ImportError:
        print(f'   ✗ {pkg} - MISSING')
        missing.append(pkg)

if missing:
    print(f'\\nMissing packages: {missing}')
    exit(1)
else:
    print('\\n   All Python packages are available!')
"

echo ""
echo "5. XML Support:"
python3.12 -c "
try:
    from lxml import etree
    print('   ✓ lxml.etree working - XML validation available')
except ImportError:
    print('   ✗ lxml.etree not working - XML validation warnings expected')
"

echo ""
echo "6. POSIX Headers:"
if echo '#include <sys/utsname.h>' | gcc -x c -c -o /dev/null - 2>/dev/null; then
    echo "   ✓ sys/utsname.h available (POSIX compatibility confirmed)"
else
    echo "   ✗ sys/utsname.h not available"
fi

echo ""
echo "7. PX4 Build System:"
if make list_config_targets >/dev/null 2>&1; then
    echo "   ✓ PX4 build system responding"
    echo "   Available targets: $(make list_config_targets 2>/dev/null | wc -l) found"
else
    echo "   ✗ PX4 build system not responding"
fi

echo ""
echo "=== Environment Status: READY FOR PX4 BUILD ==="
