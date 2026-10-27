"""Read-only prerequisite checking and probe discovery for firmware workspace."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .contracts import (
    EXIT_BLOCKED_RECOVERY,
    EXIT_OK,
    REPO_ROOT,
    make_diagnostic,
    make_result,
)

HOSTILE_VARS = [
    "CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER", "CMAKE_ASM_COMPILER",
    "CC", "CXX", "LD", "AR", "AS", "NM", "OBJCOPY", "OBJDUMP", "STRIP", "RANLIB",
    "CFLAGS", "CXXFLAGS", "LDFLAGS", "ASFLAGS", "CPPFLAGS"
]

USB_BUS_DEVICES = Path("/sys/bus/usb/devices")


def check_tool(name: str) -> Optional[str]:
    """Find absolute path of executable, checking common paths if not in PATH."""
    p = shutil.which(name)
    if p:
        return p
    common = [
        Path("/opt/SEGGER/JLink") / name,
        Path("/opt/arm-gnu-toolchain-13.2.Rel1/bin") / name,
    ]
    for c in common:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def get_arm_gcc_version() -> Tuple[bool, str]:
    """Check arm-none-eabi-gcc presence and version >= 9."""
    path = check_tool("arm-none-eabi-gcc")
    if not path:
        return False, "arm-none-eabi-gcc not found in PATH"
    try:
        out = subprocess.check_output([path, "-dumpversion"], text=True).strip()
        major = int(out.split(".")[0])
        if major < 9:
            return False, f"arm-none-eabi-gcc version {out} is too old (need >= 9)"
        return True, f"arm-none-eabi-gcc {out} ({path})"
    except Exception as e:
        return False, f"Failed checking arm-none-eabi-gcc: {e}"


def get_cmake_version() -> Tuple[bool, str]:
    """Check cmake presence and version >= 3.20."""
    path = check_tool("cmake")
    if not path:
        return False, "cmake not found in PATH"
    try:
        out = subprocess.check_output([path, "--version"], text=True).splitlines()[0]
        v_str = out.split()[2]
        parts = [int(p) for p in v_str.split("-")[0].split(".")[:2]]
        if parts[0] < 3 or (parts[0] == 3 and parts[1] < 20):
            return False, f"cmake {v_str} is too old (need >= 3.20)"
        return True, f"cmake {v_str} ({path})"
    except Exception as e:
        return False, f"Failed checking cmake: {e}"


def get_python_requirements() -> Tuple[bool, str]:
    """Check Python >= 3.9 and required modules."""
    if sys.version_info < (3, 9):
        return False, f"Python {sys.version.split()[0]} is too old (need >= 3.9)"
    missing = []
    try:
        import menuconfig  # noqa: F401
    except ImportError:
        missing.append("kconfiglib (menuconfig)")
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        missing.append("jsonschema")
    if missing:
        return False, f"Missing Python packages: {', '.join(missing)}"
    return True, f"Python {sys.version.split()[0]} with kconfiglib & jsonschema"


def enumerate_jlink_probes() -> List[Dict[str, str]]:
    """Enumerate USB connected SEGGER J-Link probes via sysfs."""
    probes = []
    if not USB_BUS_DEVICES.is_dir():
        return probes
    try:
        for dev in USB_BUS_DEVICES.iterdir():
            id_vendor = dev / "idVendor"
            if id_vendor.is_file() and id_vendor.read_text().strip() == "1366":
                serial_f = dev / "serial"
                product_f = dev / "product"
                serial = serial_f.read_text().strip() if serial_f.is_file() else "unknown"
                prod = product_f.read_text().strip() if product_f.is_file() else "J-Link"
                probes.append({
                    "usbDevice": dev.name,
                    "product": prod,
                    "serial": serial
                })
    except Exception:
        pass
    return probes


def run_doctor() -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Execute all read-only doctor checks."""
    data: Dict[str, Any] = {"tools": {}, "probes": [], "environment": {}}
    diags: List[Dict[str, str]] = []

    # 1. Compiler
    gcc_ok, gcc_msg = get_arm_gcc_version()
    data["tools"]["arm-none-eabi-gcc"] = {"ok": gcc_ok, "info": gcc_msg}
    if not gcc_ok:
        diags.append(make_diagnostic("error", "MISSING_ARM_GCC", gcc_msg))

    # 2. CMake
    cmake_ok, cmake_msg = get_cmake_version()
    data["tools"]["cmake"] = {"ok": cmake_ok, "info": cmake_msg}
    if not cmake_ok:
        diags.append(make_diagnostic("error", "MISSING_CMAKE", cmake_msg))

    # 3. Python
    py_ok, py_msg = get_python_requirements()
    data["tools"]["python"] = {"ok": py_ok, "info": py_msg}
    if not py_ok:
        diags.append(make_diagnostic("error", "PYTHON_DEPENDENCY_ERROR", py_msg))

    # 4. Ninja
    ninja = check_tool("ninja") or check_tool("ninja-build")
    data["tools"]["ninja"] = {"ok": bool(ninja), "path": ninja}
    if not ninja:
        diags.append(make_diagnostic("error", "MISSING_NINJA", "ninja or ninja-build is required"))

    # 5. GDB & JLink
    gdb = check_tool("gdb-multiarch") or check_tool("arm-none-eabi-gdb")
    data["tools"]["gdb"] = {"ok": bool(gdb), "path": gdb}
    jlink = check_tool("JLinkExe")
    data["tools"]["jlink"] = {"ok": bool(jlink), "path": jlink}
    server = check_tool("JLinkGDBServerCLExe") or check_tool("JLinkGDBServer")
    data["tools"]["jlink-gdb-server"] = {"ok": bool(server), "path": server}
    make = check_tool("make")
    data["tools"]["make"] = {"ok": bool(make), "path": make}
    if not make:
        diags.append(make_diagnostic("error", "MISSING_MAKE", "make is required for NuttX builds"))

    # 6. Leaked hostile vars in environment
    leaked = [v for v in HOSTILE_VARS if v in os.environ]
    data["environment"]["leakedToolchainVars"] = leaked
    if leaked:
        diags.append(make_diagnostic("warning", "HOSTILE_ENV_VARS", f"Environment contains overriding toolchain variables: {', '.join(leaked)}"))

    # 7. Submodules
    nuttx_dir = REPO_ROOT / "platforms" / "nuttx" / "NuttX" / "nuttx"
    submodule_ok = nuttx_dir.is_dir() and (nuttx_dir / "Makefile").is_file()
    data["submodules"] = {"nuttxInitialized": submodule_ok}
    if not submodule_ok:
        diags.append(make_diagnostic("error", "UNINITIALIZED_SUBMODULE", "NuttX submodule is not initialized"))

    # 8. J-Link probes
    probes = enumerate_jlink_probes()
    data["probes"] = probes
    if not probes:
        is_wsl = "microsoft" in os.uname().release.lower()
        msg = (
            "No J-Link probe detected on USB. On WSL attach from Windows: "
            "usbipd attach --wsl --hardware-id 1366:1020 --auto-attach"
            if is_wsl
            else "No J-Link probe detected on USB."
        )
        diags.append(make_diagnostic("info", "NO_PROBE_DETECTED", msg))

    data["readiness"] = {
        "build": all((gcc_ok, cmake_ok, py_ok, bool(ninja), bool(make), submodule_ok)),
        "load": bool(jlink and probes),
        "debug": bool(server and gdb and probes),
        "console": bool(jlink and probes),
    }
    for name, info in data["tools"].items():
        if not info["ok"]:
            info["remediation"] = {
                "gdb": "Install gdb-multiarch or set px4Nuttx.gdbPath on this workspace host.",
                "jlink": "Install the SEGGER J-Link tools on the extension host and add them to PATH.",
                "jlink-gdb-server": "Install SEGGER J-Link GDB Server on the extension host and add it to PATH.",
                "python": "Run the documented build_setup.sh setup with this Python interpreter.",
            }.get(name, "Run source ./build_setup.sh on this workspace host; check the reported executable path/version.")

    return data, diags


def cmd_doctor(args: Any) -> int:
    """CLI handler for doctor command."""
    data, diags = run_doctor()
    from .contracts import HAS_JSONSCHEMA
    readelf = check_tool("arm-none-eabi-readelf")
    data["importPrerequisites"] = {"ready": bool(HAS_JSONSCHEMA and readelf),
        "jsonschema": HAS_JSONSCHEMA, "readelf": readelf,
        "remediation": "Install Python jsonschema and arm-none-eabi-readelf on the workspace host."}
    if getattr(args, "serial", None):
        from .probe import probe_history_path
        from .target_state import TargetState
        from .verification import OperationError
        try:
            data["targetHistory"] = TargetState(probe_history_path(args.serial)).history()
        except OperationError as error:
            data["targetHistory"] = {"state": "unreadable", "recoveryRequired": True, "verifiedPair": None}
            diags.append(make_diagnostic("error", error.code, str(error)))
    has_error = any(d["level"] == "error" for d in diags)
    status = "failed" if has_error else "ok"
    res = make_result("doctor", status, data=data, diagnostics=diags)

    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print("== Prerequisites Check (Doctor)")
        for name, info in data["tools"].items():
            status_str = "OK" if info.get("ok") else "FAIL"
            print(f"  [{status_str}] {name:20} {info.get('info') or info.get('path') or ''}")
        print(f"  Submodules initialized: {data['submodules']['nuttxInitialized']}")
        print(f"  Probes detected:        {len(data['probes'])}")
        for d in diags:
            print(f"  [{d['level'].upper()}] {d['code']}: {d['message']}")
    return EXIT_BLOCKED_RECOVERY if has_error else EXIT_OK
