"""Firmware build coordinator with shared locking and artifact staging."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .artifacts import create_receipt, stage_artifact
from .catalog import group_fingerprint, load_groups, resolve_selection
from .contracts import (
    EXIT_BLOCKED_RECOVERY,
    EXIT_FAILED,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    EXIT_CANCELLED,
    REPO_ROOT,
    make_diagnostic,
    make_result,
)
from .locks import BuildLock, BuildLockContentionError
from .process import ManagedProcess


# Written by build.sh / build_ra8p1.sh after configure as "<board>:<config>".
NUTTX_CONFIG_STAMP = ".config-build-sh"


def nuttx_tree_configured_for(board: str, config: str, tree: Path) -> bool:
    """True when the shared NuttX tree was last configured for board:config."""
    try:
        stamp = (tree / NUTTX_CONFIG_STAMP).read_text(encoding="utf-8").strip()
        if not (tree / ".config").is_file() or stamp != f"{board}:{config}":
            return False

        # PX4/CMake can replace the shared configuration without removing the
        # standalone stamp. Match the files installed by tools/configure.sh
        # before allowing --no-clean; .config itself may include menuconfig edits.
        config_dir = next(tree.glob(f"boards/*/*/{board}/configs/{config}"), None)
        if config_dir is None:
            return False
        make_defs = config_dir / "Make.defs"
        if not make_defs.is_file():
            make_defs = config_dir.parent.parent / "scripts" / "Make.defs"
        return (
            (tree / "defconfig").read_bytes() == (config_dir / "defconfig").read_bytes()
            and (tree / "Make.defs").read_bytes() == make_defs.read_bytes()
        )
    except OSError:
        return False


def nuttx_build_command(board: str, config: str, mode: str, tree: Path) -> List[str]:
    """Build-script command for a NuttX config.

    All NuttX configs share one tree, so the build script refuses --no-clean
    when the tree is configured for another config. Incremental mode therefore
    only passes --no-clean when the tree already matches; otherwise the script
    reconfigures, which is what switching configs requires anyway.
    """
    helper = "build.sh" if board == "rdk-rzv2h" else "build_ra8p1.sh"
    cmd = [str(tree.parent / helper)]
    if mode == "incremental" and nuttx_tree_configured_for(board, config, tree):
        cmd.append("--no-clean")
    cmd.append(config)
    return cmd


def build_single_target(
    family: str,
    board: str,
    core: str,
    target_or_config: str,
    mode: str,
    run_id: str,
    dest_prefix: str = "firmware",
) -> Tuple[int, List[Dict[str, Any]], str]:
    """Execute single build adapter, stage artifacts, and return (returncode, artifacts, error_msg)."""
    if family == "px4":
        cmd = [str(REPO_ROOT / "build.sh")]
        if mode == "incremental":
            cmd.append("--no-clean")
        cmd.append(target_or_config)
        expected_elf = REPO_ROOT / "build" / target_or_config / f"{target_or_config}.elf"
    else:
        tree = REPO_ROOT / "platforms" / "nuttx" / "NuttX" / "nuttx"
        cmd = nuttx_build_command(board, target_or_config, mode, tree)
        expected_elf = tree / "nuttx"

    proc = ManagedProcess(cmd, cwd=str(REPO_ROOT))
    rc, _, err = proc.run(stream_stderr=True)
    if rc != 0:
        return rc, [], err or f"Build process failed with code {rc}"

    if not expected_elf.is_file():
        return 1, [], f"Expected output ELF not found at {expected_elf}"

    # Stage artifact
    staged = stage_artifact(
        expected_elf,
        run_id,
        f"{dest_prefix}.elf",
        core=core
    )
    return 0, [staged], ""


def cmd_build(args: Any) -> int:
    """CLI handler for build command."""
    sel_path = Path(args.selection)
    if not sel_path.is_file():
        err = make_diagnostic("error", "FILE_NOT_FOUND", f"Selection file not found: {sel_path}")
        print(json.dumps(make_result("build", "failed", diagnostics=[err]), indent=2))
        return EXIT_INVALID_INPUT

    try:
        raw_sel = json.loads(sel_path.read_text(encoding="utf-8"))
    except Exception as e:
        err = make_diagnostic("error", "INVALID_JSON", f"Failed to parse selection: {e}")
        print(json.dumps(make_result("build", "failed", diagnostics=[err]), indent=2))
        return EXIT_INVALID_INPUT

    resolved, diags = resolve_selection(raw_sel)
    if not resolved:
        print(json.dumps(make_result("build", "failed", diagnostics=diags), indent=2))
        return EXIT_INVALID_INPUT

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    is_group = "group" in raw_sel
    board_id = raw_sel["board"]
    core_id = raw_sel["core"]
    build_info = raw_sel["build"]
    mode = "clean" if getattr(args, "clean", False) else build_info["mode"]

    try:
        with BuildLock(timeout=10.0):
            all_staged: List[Dict[str, Any]] = []
            if not is_group:
                # Single target build
                name = build_info.get("target") or build_info.get("config")
                rc, artifacts, err_msg = build_single_target(
                    build_info["family"], board_id, core_id, name, mode, run_id
                )
                if rc != 0:
                    d = make_diagnostic("error", "BUILD_FAILED", err_msg)
                    print(json.dumps(make_result("build", "cancelled" if rc == EXIT_CANCELLED else "failed", diagnostics=[d], child_exit_code=rc), indent=2))
                    return EXIT_CANCELLED if rc == EXIT_CANCELLED else EXIT_FAILED

                receipt_file = create_receipt(
                    run_id, build_info["family"], board_id, core_id, raw_sel["id"],
                    artifacts, status="committed",
                    target=build_info.get("target"), config=build_info.get("config")
                )
                all_staged.extend(artifacts)
            else:
                # Group build
                group_id = raw_sel["group"]
                groups = load_groups().get("groups", {})
                group_meta = groups.get(group_id, {})
                members = group_meta.get("members", [])
                for idx, m in enumerate(members):
                    m_core = m["core"]
                    m_cfg = m.get("target") or m.get("config")
                    m_fam = m["family"]
                    rc, artifacts, err_msg = build_single_target(
                        m_fam, board_id, m_core, m_cfg, mode, run_id,
                        dest_prefix=f"{group_id}-{m_core}"
                    )
                    if rc != 0:
                        # Member failed: cannot publish group success
                        d = make_diagnostic("error", "MEMBER_BUILD_FAILED", f"Member {m_core} ({m_cfg}) failed: {err_msg}")
                        print(json.dumps(make_result("build", "cancelled" if rc == EXIT_CANCELLED else "failed", diagnostics=[d], child_exit_code=rc), indent=2))
                        return EXIT_CANCELLED if rc == EXIT_CANCELLED else EXIT_FAILED
                    all_staged.extend(artifacts)

                # Commit group receipt atomically after all members pass
                group_family = group_meta.get("family") or build_info.get("family") or "multicore"
                receipt_file = create_receipt(
                    run_id, group_family, board_id, "multicore", raw_sel["id"],
                    all_staged, status="committed", group=group_id,
                    group_definition_sha256=group_fingerprint(group_meta)
                )

    except BuildLockContentionError as e:
        d = make_diagnostic("error", "LOCK_CONTENTION", str(e))
        print(json.dumps(make_result("build", "blocked", diagnostics=[d]), indent=2))
        return EXIT_BLOCKED_RECOVERY
    except (OSError, ValueError) as error:
        d = make_diagnostic("error", "BUILD_FAILED", str(error))
        print(json.dumps(make_result("build", "failed", diagnostics=[d])))
        return EXIT_FAILED

    res = make_result(
        "build", "ok",
        data={"receiptId": run_id, "artifacts": all_staged},
        receipt_path=str(receipt_file.relative_to(REPO_ROOT))
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print(f"Build completed successfully. Receipt: {res['receiptPath']}")
    return EXIT_OK
