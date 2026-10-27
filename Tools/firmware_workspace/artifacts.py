"""Artifact staging, provenance verification, and immutable receipts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import REPO_ROOT, validate_schema
from .doctor import check_tool

ARTIFACTS_ROOT = REPO_ROOT / "build" / "workspace-artifacts"


def atomic_json(path: Path, value: Any) -> None:
    """Publish durable JSON without exposing an incomplete document."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def create_import_receipt(run_dir: Path, request: Dict[str, Any], artifacts: List[Dict[str, Any]],
                          group_digest: str) -> Path:
    """Import metadata describes supplied bytes, never the current checkout's origin."""
    selection = request["selection"]
    provenance = {"evidence": "unknown", "sourceReceiptId": None, "reportedGitRevision": None,
                  "reportedGitDirty": None, "reportedCompiler": None}
    receipt = {
        "schemaVersion": 2, "operation": "import-images", "requestId": request["requestId"],
        "receiptId": "import-" + request["requestId"], "timestamp": datetime.now(timezone.utc).isoformat(),
        "family": selection["build"]["family"], "board": selection["board"], "core": "multicore",
        "selectionId": selection["id"], "target": selection["build"].get("target"),
        "config": selection["build"].get("config"), "group": selection["group"],
        "groupDefinitionSha256": group_digest, "gitRevision": None, "gitDirty": None,
        "compiler": None, "provenance": provenance, "artifacts": artifacts,
        "status": "committed" if len(artifacts) == 2 else "provisional",
    }
    errors = validate_schema(receipt, "artifact-receipt")
    if errors:
        raise ValueError(f"Import receipt validation failed: {errors}")
    destination = run_dir / "receipt.json"
    atomic_json(destination, receipt)
    return destination


def compute_sha256(path: Path) -> str:
    """Calculate SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info() -> Dict[str, Any]:
    """Retrieve git HEAD revision and dirty status."""
    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
        return {"revision": rev, "dirty": bool(status)}
    except Exception:
        return {"revision": "unknown", "dirty": False}


def read_elf_metadata(elf_path: Path) -> Dict[str, Any]:
    """Read entry point and _SEGGER_RTT symbol address from 32-bit ARM ELF."""
    meta: Dict[str, Any] = {"entryPoint": None, "rttAddress": None}
    if not elf_path.is_file():
        return meta

    # Entry point from ELF header
    try:
        with open(elf_path, "rb") as fh:
            hdr = fh.read(0x1C)
            if len(hdr) >= 0x1C and hdr[:4] == b"\x7fELF" and hdr[4] == 1:
                endian = "<I" if hdr[5] == 1 else ">I"
                entry = struct.unpack_from(endian, hdr, 0x18)[0]
                meta["entryPoint"] = f"0x{entry:08x}"
    except Exception:
        pass

    # _SEGGER_RTT symbol via nm
    nm = check_tool("arm-none-eabi-nm")
    if nm:
        try:
            out = subprocess.check_output([nm, str(elf_path)], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if line.endswith(" _SEGGER_RTT"):
                    addr = line.split()[0]
                    meta["rttAddress"] = f"0x{addr}"
                    break
        except Exception:
            pass
    return meta


def stage_artifact(src_path: Path, run_id: str, dest_name: str, core: Optional[str] = None) -> Dict[str, Any]:
    """Copy an artifact into run staging directory and record metadata."""
    run_dir = ARTIFACTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    dest_path = run_dir / dest_name
    shutil.copy2(src_path, dest_path)

    sha = compute_sha256(dest_path)
    size = dest_path.stat().st_size
    info: Dict[str, Any] = {
        "path": str(dest_path.relative_to(REPO_ROOT)),
        "sha256": sha,
        "size": size,
    }
    if core:
        info["core"] = core

    elf_meta = read_elf_metadata(dest_path)
    info["entryPoint"] = elf_meta.get("entryPoint")
    info["rttAddress"] = elf_meta.get("rttAddress")
    return info


def create_receipt(
    run_id: str,
    family: str,
    board: str,
    core: str,
    selection_id: str,
    artifacts: List[Dict[str, Any]],
    status: str = "committed",
    target: Optional[str] = None,
    config: Optional[str] = None,
    group: Optional[str] = None,
    compiler: str = "arm-none-eabi-gcc",
    group_definition_sha256: Optional[str] = None,
) -> Path:
    """Create, validate, and write immutable artifact receipt JSON."""
    git_info = get_git_info()
    receipt_data = {
        "schemaVersion": 1,
        "receiptId": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "family": family,
        "board": board,
        "core": core,
        "selectionId": selection_id,
        "target": target,
        "config": config,
        "gitRevision": git_info["revision"],
        "gitDirty": git_info["dirty"],
        "compiler": compiler,
        "artifacts": artifacts,
        "status": status,
        "group": group,
    }
    if group:
        from .catalog import group_fingerprint, load_groups
        receipt_data["groupDefinitionSha256"] = group_definition_sha256 or group_fingerprint(load_groups()["groups"][group])

    diags = validate_schema(receipt_data, "artifact-receipt")
    if diags:
        raise ValueError(f"Artifact receipt validation error: {diags}")

    run_dir = ARTIFACTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = run_dir / "receipt.json"

    # Atomic write via temp file
    temp_path = run_dir / "receipt.json.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(receipt_data, f, indent=2)
    os.replace(temp_path, receipt_path)
    return receipt_path
