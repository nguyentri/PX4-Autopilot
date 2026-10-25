"""Target and configuration discovery routines for PX4 and NuttX."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .contracts import PROFILES_DIR, REPO_ROOT


def discover_px4_targets() -> List[Dict[str, Any]]:
    """Scan boards/renesas/ for authoritative PX4 board targets."""
    boards_root = REPO_ROOT / "boards" / "renesas"
    targets: List[Dict[str, Any]] = []
    if not boards_root.is_dir():
        return targets

    for bdir in sorted(boards_root.iterdir()):
        if not bdir.is_dir():
            continue
        board_name = bdir.name
        core = "cr8_0"
        if board_name.endswith("-io-cr8_1"):
            board_id = "rdk-rzv2h"
            core = "cr8_1"
        elif board_name.endswith("-io-cm33"):
            board_id = "rdk-rzv2h" if "rzv" in board_name else "evk-ra8p1"
            core = "cm33"
        elif board_name.startswith("evk-ra8p1"):
            board_id = "evk-ra8p1"
            core = "cm85"
        elif board_name.startswith("fpb-ra8e1"):
            board_id = "fpb-ra8e1"
            core = "cm85"
        else:
            board_id = "rdk-rzv2h"
            core = "cr8_0"

        for p in sorted(bdir.glob("*.px4board")):
            if p.stem.endswith(("_bk", "_backup", "~")):
                continue
            target_name = f"renesas_{board_name}_{p.stem}"
            targets.append({
                "target": target_name,
                "board": board_id,
                "core": core,
                "family": "px4",
                "file": str(p.relative_to(REPO_ROOT)),
            })
    return targets


def discover_nuttx_configs(board: str) -> List[Dict[str, Any]]:
    """Scan NuttX boards directory for standalone configurations."""
    if board == "rdk-rzv2h":
        cfg_root = REPO_ROOT / "platforms" / "nuttx" / "NuttX" / "nuttx" / "boards" / "arm" / "rzv" / "rdk-rzv2h" / "configs"
    elif board == "evk-ra8p1":
        cfg_root = REPO_ROOT / "platforms" / "nuttx" / "NuttX" / "nuttx" / "boards" / "arm" / "ra8" / "evk-ra8p1" / "configs"
    else:
        return []

    configs: List[Dict[str, Any]] = []
    if not cfg_root.is_dir():
        return configs

    for p in sorted(cfg_root.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        core = "cr8_0"
        if board == "rdk-rzv2h":
            if "cr8_1" in name or name.endswith("-io"):
                core = "cr8_1"
            elif "cm33" in name:
                core = "cm33"
            else:
                core = "cr8_0"
        elif board == "evk-ra8p1":
            if "cm33" in name:
                core = "cm33"
            else:
                core = "cm85"

        configs.append({
            "config": name,
            "board": board,
            "core": core,
            "family": "nuttx",
            "directory": str(p.relative_to(REPO_ROOT)),
        })
    return configs


def load_devices() -> Dict[str, Any]:
    """Load devices profile."""
    path = PROFILES_DIR / "devices.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_groups() -> Dict[str, Any]:
    """Load groups profile."""
    path = PROFILES_DIR / "groups.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
