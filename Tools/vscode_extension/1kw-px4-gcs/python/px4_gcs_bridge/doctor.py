"""Environment report: Python, pymavlink and pyserial versions, missing modules."""
from __future__ import annotations

import importlib
import platform
import sys

from . import BRIDGE_VERSION
from .protocol import PROTOCOL_VERSION


def _version(module_name: str):
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - any import failure means "missing"
        return None
    return str(getattr(module, "__version__", "unknown"))


def report() -> dict:
    pymavlink = None
    if _version("pymavlink") is not None:
        try:
            from importlib.metadata import version
            pymavlink = version("pymavlink")
        except Exception:  # noqa: BLE001
            pymavlink = "unknown"
    serial = _version("serial")
    missing = [name for name, found in (("pymavlink", pymavlink), ("pyserial", serial)) if found is None]
    return {
        "bridgeVersion": BRIDGE_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "python": platform.python_version(),
        "pythonExecutable": sys.executable,
        "platform": sys.platform,
        "pymavlink": pymavlink,
        "pyserial": serial,
        "missing": missing,
        "pythonOk": sys.version_info >= (3, 8),
    }
