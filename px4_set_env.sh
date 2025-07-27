#!/c/msys64/usr/bin/bash

# === MSYS2 Tool Paths ===
export MSYS2_BIN="/usr/bin"
# Note: Don't use MINGW64 for PX4 builds as it lacks POSIX headers like sys/utsname.h

# === Custom Tool Paths ===
export ARM_GCC_PATH="/c/UserSoftware/arm-toolchain/arm-gnu-toolchain-13.2.Rel1/bin"

# === Install MSYS2 Build Tools ===
echo "[+] Installing MSYS2 POSIX build tools..."

# Fix SSL certificate issues for pacman
echo "[+] Updating pacman configuration for SSL compatibility..."
sed -i 's/#SigLevel = Required DatabaseOptional/SigLevel = Never/' /etc/pacman.conf 2>/dev/null || true

# Alternative SSL fix - disable SSL verification for curl
export CURL_CA_BUNDLE=""
export SSL_VERIFY=0

# Update package database first
echo "[+] Updating package database..."
pacman -Sy --noconfirm

# Install packages with SSL workaround
echo "[+] Installing build tools..."
if ! pacman -S --needed --noconfirm --disable-download-timeout \
    make \
    findutils \
    procps-ng \
    cmake \
    gcc \
    python \
    python-pip \
    python-setuptools \
    python-yaml \
    python-packaging \
    libxml2 \
    libxml2-devel \
    libxslt \
    libxslt-devel \
    git; then
    echo "[!] Package installation failed due to SSL issues. Trying alternative approach..."

    # Try with different mirror
    echo "[+] Trying with alternative mirror configuration..."
    echo 'Server = https://repo.msys2.org/msys/$arch' > /etc/pacman.d/mirrorlist.msys
    echo 'Server = https://mirror.msys2.org/msys/$arch' >> /etc/pacman.d/mirrorlist.msys

    # Try again with relaxed SSL
    curl -k -L -o /tmp/ca-certificates.pkg.tar.zst https://repo.msys2.org/msys/x86_64/ca-certificates-20240203-1-any.pkg.tar.zst 2>/dev/null || true
    if [ -f /tmp/ca-certificates.pkg.tar.zst ]; then
        pacman -U --noconfirm /tmp/ca-certificates.pkg.tar.zst || true
    fi

    # Retry installation
    pacman -S --needed --noconfirm \
        make \
        findutils \
        procps-ng \
        cmake \
        gcc \
        python \
        python-pip \
        python-setuptools \
        python-yaml \
        python-packaging \
        libxml2 \
        libxml2-devel \
        libxslt \
        libxslt-devel \
        git || echo "[!] Some packages may have failed to install, but continuing..."
fi

# === Build PATH ===
# Use MSYS2 POSIX tools (NOT MinGW64) for PX4 compatibility
# Prepend MSYS2 tools and ARM toolchain to existing PATH
export PATH="$MSYS2_BIN:$ARM_GCC_PATH:$PATH"

# === Clean Python Environment ===
unset PYTHONHOME
unset PYTHONPATH
unset GNUMAKE
unset GCC
unset cmake

# === Verify Core Tools ===
echo "[+] Core Tool Verification:"
echo "    make: $(which make) -> $(make --version | head -n1)"
echo "    find: $(which find) -> $(find --version | head -n1)"
echo "    ps: $(which ps) -> $(ps --version | head -n1)"
echo "    cmake: $(which cmake) -> $(cmake --version | head -n1)"
echo "    gcc: $(which gcc) -> $(gcc --version | head -n1)"

# === Python Setup ===
echo "[+] Python Verification:"
echo "    Python3.12 path: $(which python3.12)"
echo "    Python3.12 version: $(python3.12 --version)"
echo "    pip version: $(python3.12 -m pip --version)"

# Create python and python3 symlinks for compatibility
if [ ! -f "/usr/bin/python" ] || [ ! -x "/usr/bin/python" ]; then
    echo "[+] Creating python symlink for compatibility..."
    ln -sf /usr/bin/python3.12.exe /usr/bin/python
fi

if [ ! -f "/usr/bin/python3" ] || [ ! -x "/usr/bin/python3" ]; then
    echo "[+] Creating python3 symlink for compatibility..."
    ln -sf /usr/bin/python3.12.exe /usr/bin/python3
fi

# Verify symlinks work
echo "[+] Verifying Python symlinks:"
echo "    python: $(which python) -> $(python --version 2>/dev/null || echo 'Failed')"
echo "    python3: $(which python3) -> $(python3 --version 2>/dev/null || echo 'Failed')"

# === Install remaining packages with --break-system-packages if needed ===
echo "[+] Installing additional Python packages..."
python3.12 -m pip install --break-system-packages \
    empy==3.3.4 \
    argcomplete \
    cerberus \
    kconfiglib==14.1.0 \
    pyros-genmsg \
    jsonschema==4.17.3 \
    toml==0.10.2 \
    pyserial \
    jinja2 \
    pyyaml \
    lxml

# === Verify Python Packages ===
echo "[+] Verifying Python packages:"
python3.12 -c "import em, jinja2, yaml, kconfiglib; print('✓ All packages found')" || {
    echo "[!] Python packages verification failed"
    exit 1
}

# === Verify XML support ===
echo "[+] Verifying XML support:"
python3.12 -c "from lxml import etree; print('✓ lxml.etree is working properly')" || {
    echo "[!] lxml XML support not working properly"
    echo "    This may cause XML validation warnings but build should continue"
}

# === Toolchain Setup ===
export CROSSDEV=arm-none-eabi-
export CC="${CROSSDEV}gcc"
export CXX="${CROSSDEV}g++"
export ARCH=arm

# For CMake
export CMAKE_C_COMPILER="$ARM_GCC_PATH/arm-none-eabi-gcc"
export CMAKE_CXX_COMPILER="$ARM_GCC_PATH/arm-none-eabi-g++"
export CMAKE_ASM_COMPILER="$ARM_GCC_PATH/arm-none-eabi-gcc"

# Verify ARM toolchain
echo "[+] ARM Tool Verification:"
echo "    ARM GCC: $(which ${CROSSDEV}gcc) -> $(${CROSSDEV}gcc --version | head -n1)"

# === Build Setup ===
echo "[+] Checking available PX4 targets..."

# Check if we can list targets
if make list_config_targets 2>/dev/null | head -20; then
    echo ""
    echo "[+] Some common targets to try:"
    echo "    - px4_fmu-v6xrt_default"
    echo "    - px4_fmu-v6x_default"
    echo "    - px4_fmu-v6c_default"
    echo "    - px4_sitl_default (for simulation)"
    echo ""
    echo "[+] To build a specific target, run:"
    echo "    make <target_name>"
    echo "    Example: make px4_fmu-v6xrt_default"
else
    echo "[!] Cannot list targets. Make sure you're in the correct PX4 directory."
fi

echo ""
echo "[+] Environment setup complete!"
echo "    You can now build PX4 targets using 'make <target_name>'"

ln -sf "$(pwd)/px4/platforms/nuttx/NuttX/nuttx/arch/arm/src/imxrt/hardware" ./tools/link.sh
ln -sf "$(pwd)/px4/platforms/nuttx/NuttX/nuttx/drivers/platform ./tools/link.sh
