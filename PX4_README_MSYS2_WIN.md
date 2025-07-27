## PX4 Development on Windows using MSYS2

This guide will walk you through setting up a fully functional MSYS2 environment on Windows for building PX4 with NuttX. It covers:

- Enabling native symlink support
- Installing and configuring MSYS2 build tools
- Configuring VS Code for MSYS2
- Environment bootstrap script
- Checking out and building PX4 targets
- Common troubleshooting tips

---

### 1. Prerequisites

- Windows 10/11 (64‑bit)
- Administrator privileges for initial setup (optional with Developer Mode enabled)
- Visual Studio Code (latest) installed
- ARM GNU Toolchain (e.g., arm-gnu-toolchain-13.2.Rel1)

---

### 2. Enable Native Symlink Support

Windows restricts symlink creation by default. To avoid `Operation not permitted` errors when PX4/NuttX creates directory links, enable:

1. **Developer Mode** (no admin needed after):

   - Open **Settings → Privacy & Security → For Developers**
   - Turn on **Developer Mode**
   - Restart your MSYS2 terminal

2. **(Alternative)** Run MSYS2 as Administrator

3. **Force NTFS symlinks in MSYS2**

   - In your Windows shell, set:
     ```cmd
     set MSYS=winsymlinks:nativestrict
     ```
   - Then launch `c:\msys64\usr\bin\bash.exe`

---

### 3. Install MSYS2 and Build Tools

1. **Download and install MSYS2** from [https://www.msys2.org](https://www.msys2.org)
2. Open an **MSYS2 MSYS** shell and update core packages:
   ```bash
   pacman -Syuu --noconfirm
   ```
3. Close and re-open the MSYS shell, then install required packages:
   ```bash
   pacman -S --needed --noconfirm \
     make findutils procps-ng cmake gcc python python-pip \
     python-setuptools python-yaml python-packaging \
     libxml2 libxml2-devel libxslt libxslt-devel git
   ```
4. **SSL issues workaround** (if needed):
   ```bash
   sed -i 's/#SigLevel = Required DatabaseOptional/SigLevel = Never/' /etc/pacman.conf
   export CURL_CA_BUNDLE="" SSL_VERIFY=0
   ```

---

### 4. Bootstrap Script (`px4_set_env.sh`)

Save the following as `scripts/set_env.sh` in your workspace and run:

```bash
#!/usr/bin/env bash

# Paths
echo "[+] Bootstrapping MSYS2 PX4 environment..."
export MSYS2_BIN="/usr/bin"
export ARM_GCC_PATH="/c/UserSoftware/arm-toolchain/arm-gnu-toolchain-13.2.Rel1/bin"

# Update pacman for SSL issues
sed -i 's/#SigLevel = Required DatabaseOptional/SigLevel = Never/' /etc/pacman.conf 2>/dev/null || true
export CURL_CA_BUNDLE="" SSL_VERIFY=0

# Install core tools
pacman -Sy --noconfirm
pacman -S --needed --noconfirm make findutils procps-ng cmake gcc python python-pip \
  python-setuptools python-yaml python-packaging libxml2 libxml2-devel \
  libxslt libxslt-devel git

# PATH setup
export PATH="$MSYS2_BIN:$ARM_GCC_PATH:\$PATH"

# Clean Python environment
unset PYTHONHOME PYTHONPATH GNUMAKE GCC cmake

# Verify tools
for tool in make find ps cmake gcc python3.12; do
  echo "\$tool: \$(which \$tool) -> \$($tool --version | head -1)"
done

# Create Python symlinks
ln -sf /usr/bin/python3.12.exe /usr/bin/python
ln -sf /usr/bin/python3.12.exe /usr/bin/python3

# Install Python packages
python3.12 -m pip install --break-system-packages \
  empy==3.3.4 argcomplete cerberus kconfiglib==14.1.0 pyros-genmsg \
  jsonschema==4.17.3 toml==0.10.2 pyserial jinja2 pyyaml lxml

# Verify Python packages
python3.12 -c "import em, jinja2, yaml, kconfiglib; print('✓ Python libs OK')"

# Toolchain vars
export CROSSDEV=arm-none-eabi-
export CC="\$CROSSDEV""gcc"
export CXX="\$CROSSDEV""g++"
export ARCH=arm
export CMAKE_C_COMPILER="$ARM_GCC_PATH/arm-none-eabi-gcc"
export CMAKE_CXX_COMPILER="$ARM_GCC_PATH/arm-none-eabi-g++"
export CMAKE_ASM_COMPILER="$ARM_GCC_PATH/arm-none-eabi-gcc"

echo "[+] Environment bootstrap complete."
```

Run:

```bash
bash scripts/set_env.sh
```

---

### 5. VS Code Configuration

Add to your workspace `.vscode/settings.json`:

```jsonc
{
  "files.eol": "\n",
  "terminal.integrated.profiles.windows": {
    "MSYS2": {
      "path": "C:/msys64/usr/bin/bash.exe",
      "args": ["--login", "-i"],
      "env": {
        "MSYS": "winsymlinks:nativestrict",
        "PATH": "${env:PATH};C:/UserSoftware/arm-toolchain/arm-gnu-toolchain-13.2.Rel1/bin"
      },
      "icon": "terminal-bash"
    }
  },
  "terminal.integrated.defaultProfile.windows": "MSYS2",
  "C_Cpp.default.cStandard": "c11",
  "C_Cpp.default.cppStandard": "c++17",
  "C_Cpp.default.intelliSenseMode": "gcc-arm",
  "files.associations": {
    "*.h": "c",
    "*.c": "c",
    "Makefile": "makefile"
  }
}
```

---

### 6. Clone and Build PX4

```bash
# Clone PX4
git clone https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
# Fetch tags & submodules
git fetch --all --tags
git submodule update --init --recursive

**Switch to a stable release tag:**

```bash
# Example: v1.16.0-rc3
git checkout v1.16.0-rc3
git submodule update --init --recursive
```

# List targets
make list_config_targets | head -20

# Build your target (e.g., px4_fmu-v5_default)
make px4_fmu-v5_default
```


---

### 7. Troubleshooting

- ``

  `` when creating symlinks: ensure Developer Mode or Admin
- **SSL errors**: verify `/etc/pacman.conf` SigLevel or use `SSL_VERIFY=0`
- **Missing headers**: use the MSYS2 POSIX environment (`MSYS2_MSYS`), not MINGW64

For further help, visit the PX4 discussion forum: [https://discuss.px4.io](https://discuss.px4.io)
