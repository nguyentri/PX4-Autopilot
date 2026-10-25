"""Target catalog and profile resolver for PX4 and NuttX on Renesas hardware."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .contracts import make_diagnostic, validate_schema
from .discovery import (
    discover_nuttx_configs,
    discover_px4_targets,
    load_devices,
    load_groups,
)

__all__ = [
    "discover_px4_targets",
    "discover_nuttx_configs",
    "load_devices",
    "load_groups",
    "resolve_selection",
]


def group_fingerprint(group):
    """Bind the image set to its authoritative member/operation definition."""
    contract = {key: group.get(key) for key in ("id", "board", "members", "loadRecipe", "console")}
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_selection(selection: Dict[str, Any], operation: str = "build") -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """Validate and resolve a selection dictionary.

    Returns (resolved_data, diagnostics).
    """
    diags = validate_schema(selection, "firmware-selection")
    if diags:
        return None, diags

    devices = load_devices().get("boards", {})
    board_id = selection["board"]
    core_id = selection["core"]

    if board_id not in devices:
        diags.append(make_diagnostic("error", "UNKNOWN_BOARD", f"Unknown board: {board_id}", "/board"))
        return None, diags

    board_meta = devices[board_id]
    cores = board_meta.get("cores", {})
    if core_id not in cores:
        diags.append(make_diagnostic("error", "UNKNOWN_CORE", f"Unknown core '{core_id}' for board {board_id}", "/core"))
        return None, diags

    core_cap = cores[core_id]
    build_info = selection["build"]
    family = build_info["family"]

    if family not in core_cap.get("supportedFamilies", []):
        diags.append(make_diagnostic("error", "UNSUPPORTED_FAMILY", f"Family '{family}' unsupported on {board_id}:{core_id}", "/build/family"))
        return None, diags

    # Multi-core group resolution
    if "group" in selection:
        groups = load_groups().get("groups", {})
        group_id = selection["group"]
        if group_id not in groups:
            diags.append(make_diagnostic("error", "UNKNOWN_GROUP", f"Multicore group '{group_id}' not found", "/group"))
            return None, diags
        group_meta = groups[group_id]
        if core_id != "multicore" or group_meta["board"] != board_id:
            return None, [make_diagnostic("error", "GROUP_MISMATCH", "Group does not belong to the selected board/core", "/group")]
        members = group_meta.get("members", [])
        if not members or len({member["core"] for member in members}) != len(members):
            return None, [make_diagnostic("error", "GROUP_MISMATCH", "Group must contain distinct concrete cores", "/group")]
        families = {member["family"] for member in members}
        expected_family = next(iter(families)) if len(families) == 1 else "multicore"
        if family != expected_family:
            return None, [make_diagnostic("error", "GROUP_MISMATCH", "Build family differs from the group members", "/build/family")]

        # Validate that each member exists in authoritative catalog
        for idx, m in enumerate(group_meta.get("members", [])):
            m_core = m["core"]
            m_fam = m["family"]
            if m_fam == "px4":
                tgt = m.get("target")
                avail = [t for t in discover_px4_targets() if t["target"] == tgt]
                if not avail:
                    diags.append(make_diagnostic("error", "TARGET_NOT_FOUND", f"Member target '{tgt}' not found", f"/group/members/{idx}"))
                    return None, diags
            else:
                cfg = m.get("config")
                avail = [c for c in discover_nuttx_configs(board_id) if c["config"] == cfg]
                if not avail:
                    diags.append(make_diagnostic("error", "CONFIG_NOT_FOUND", f"Member config '{cfg}' not found", f"/group/members/{idx}"))
                    return None, diags
            if avail[0]["core"] != m_core or (m_fam == "px4" and avail[0]["board"] != board_id):
                return None, [make_diagnostic("error", "GROUP_MISMATCH", "Group member target/config belongs to another board/core", f"/group/members/{idx}")]

        # Admission check
        if operation == "load" and not core_cap.get("loadAvailable", False):
            msg = core_cap.get("remediation") or f"Target loading unsupported or gated on {board_id}:{core_id}"
            diags.append(make_diagnostic("error", "LOAD_UNAVAILABLE", msg, "/load"))
            return None, diags

        if operation == "debug" and not core_cap.get("debugAvailable", False):
            msg = core_cap.get("remediation") or f"Debugging unsupported on {board_id}:{core_id}"
            diags.append(make_diagnostic("error", "DEBUG_UNAVAILABLE", msg, "/debug"))
            return None, diags

        resolved = {
            "selection": selection,
            "board": board_meta,
            "coreCapabilities": core_cap,
            "jlinkDevice": core_cap.get("jlinkDevice"),
            "groupMeta": group_meta,
        }
        return resolved, diags

    if core_id == "multicore" or not (build_info.get("target") or build_info.get("config")):
        return None, [make_diagnostic("error", "MISSING_TARGET", "Select a concrete target/config or a multicore group", "/build")]

    # Single-core target / config presence check
    if family == "px4":
        target = build_info["target"]
        avail = [t for t in discover_px4_targets() if t["target"] == target]
        if not avail:
            diags.append(make_diagnostic("error", "TARGET_NOT_FOUND", f"PX4 target '{target}' not found in catalog", "/build/target"))
            return None, diags
        if avail[0]["board"] != board_id or avail[0]["core"] != core_id:
            diags.append(make_diagnostic("error", "CORE_MISMATCH", f"Target '{target}' is for {avail[0]['board']}:{avail[0]['core']}, not {board_id}:{core_id}", "/build/target"))
            return None, diags
    else:
        config = build_info["config"]
        avail = [c for c in discover_nuttx_configs(board_id) if c["config"] == config]
        if not avail:
            diags.append(make_diagnostic("error", "CONFIG_NOT_FOUND", f"NuttX config '{config}' not found for board {board_id}", "/build/config"))
            return None, diags
        if avail[0]["core"] != core_id:
            diags.append(make_diagnostic("error", "CORE_MISMATCH", f"Config '{config}' is for core {avail[0]['core']}, not {core_id}", "/build/config"))
            return None, diags

    # Check load recipe availability
    if operation == "load" and not core_cap.get("loadAvailable", False):
        msg = core_cap.get("remediation") or f"Target loading unsupported or gated on {board_id}:{core_id}"
        diags.append(make_diagnostic("error", "LOAD_UNAVAILABLE", msg, "/load"))
        return None, diags

    # Check debug availability
    if operation == "debug" and not core_cap.get("debugAvailable", False):
        msg = core_cap.get("remediation") or f"Debugging unsupported on {board_id}:{core_id}"
        diags.append(make_diagnostic("error", "DEBUG_UNAVAILABLE", msg, "/debug"))
        return None, diags

    resolved = {
        "selection": selection,
        "board": board_meta,
        "coreCapabilities": core_cap,
        "jlinkDevice": core_cap.get("jlinkDevice"),
    }
    return resolved, diags
