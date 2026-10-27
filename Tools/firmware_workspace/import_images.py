"""Host-only, resumable capture of explicitly assigned CR8 image bytes."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path

from .artifacts import (ARTIFACTS_ROOT, atomic_json, compute_sha256, create_import_receipt,
                        read_elf_metadata)
from .catalog import group_fingerprint, resolve_selection
from .contracts import REPO_ROOT, EXIT_OK, validate_schema, make_result
from .doctor import check_tool
from .load import check_rz_allowlist, operation_failure
from .locks import BuildLock
from .verification import OperationError, read_json

CORES = ("cr8_0", "cr8_1")


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def local_path(value):
    if not value or "\x00" in value or "://" in value or re.match(r"^[A-Za-z]:", value):
        raise OperationError("Select an accessible workspace-host filesystem path", "INVALID_SOURCE_PATH")
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def observed(path, descriptor=None):
    info = os.fstat(descriptor) if descriptor is not None else path.stat()
    return {"path": str(path), "size": info.st_size, "mtimeNs": str(info.st_mtime_ns)}


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def open_source(source):
    """Folder traversal is relative to pinned directory FDs; no symlinks are followed."""
    descriptors = []
    try:
        if source["kind"] == "folder":
            root = local_path(source["path"]).resolve(strict=True)
            relative = Path(source["relativePath"])
            if relative.is_absolute() or not relative.parts or any(p in ("..", ".") for p in relative.parts):
                raise OperationError("Selected folder file must stay inside the folder", "INVALID_SOURCE_PATH")
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            for component in relative.parts[:-1]:
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                descriptors.append(descriptor)
            descriptor = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            path = root / relative
        else:
            path = local_path(source["path"]).resolve(strict=True)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OperationError("Image source must be a regular file", "INVALID_SOURCE_PATH")
        yield path, descriptor
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture(source, destination):
    """Detect in-place writes and inode replacement, including equal-size rewrites."""
    destination = Path(destination)
    partial = destination.with_suffix(".partial")
    completed = destination.with_suffix(".capture.json")
    if completed.exists():
        observation = read_json(completed)
        captured = destination if destination.exists() else partial
        if (captured.stat().st_size != observation["size"] or
                compute_sha256(captured) != observation["sha256"]):
            raise OperationError("Completed capture changed; start a new preparation", "ARTIFACT_HASH_MISMATCH")
        if captured == partial:
            os.replace(partial, destination)
        return observation
    partial.unlink(missing_ok=True)
    with open_source(source) as (path, descriptor):
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        with open(partial, "wb") as output:
            while chunk := os.read(descriptor, 1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.lseek(descriptor, 0, os.SEEK_SET)
        again = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            again.update(chunk)
        if (identity(before) != identity(os.fstat(descriptor)) or
                identity(before) != identity(path.stat()) or digest.digest() != again.digest()):
            partial.unlink(missing_ok=True)
            raise OperationError("Source changed during capture; choose it again", "SOURCE_CHANGED_DURING_COPY")
        if source["kind"] == "folder":
            with open_source(source) as (_, checked):
                if identity(before) != identity(os.fstat(checked)):
                    raise OperationError("Folder source changed during capture", "SOURCE_CHANGED_DURING_COPY")
        observation = dict(observed(path, descriptor), sha256=digest.hexdigest())
    partial.chmod(0o400)
    atomic_json(completed, observation)
    os.replace(partial, destination)
    # The following durable manifest publication also flushes this directory.
    return observation


def validate_startup(path):
    """Check the ARM-state __start convention used by the retained RAM loader."""
    readelf = check_tool("arm-none-eabi-readelf")
    if not readelf:
        raise OperationError("Install arm-none-eabi-readelf on the workspace host to validate existing images",
                             "IMPORT_PREREQUISITE_MISSING", True)
    result = subprocess.run([readelf, "-W", "-h", "-l", "-s", "-A", str(path)],
                            capture_output=True, text=True, check=False)
    text = result.stdout
    valid_header = all(re.search(pattern, text) for pattern in (
        r"Class:\s+ELF32\b", r"Data:\s+2's complement, little endian", r"Type:\s+EXEC\b",
        r"Machine:\s+ARM\b", r"Flags:.*Version5 EABI"))
    starts = re.findall(r"^\s*\d+:\s+([0-9a-fA-F]+)\s+\d+\s+(?:FUNC|NOTYPE)\s+\S+\s+\S+\s+(\d+)\s+__start\s*$", text, re.M)
    start = int(starts[0][0], 16) if len(starts) == 1 else None
    segments = re.findall(r"^\s*LOAD\s+0x[0-9a-fA-F]+\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+0x[0-9a-fA-F]+\s+([^\n]+)$", text, re.M)
    executable = start is not None and any(
        "E" in flags and int(vaddr, 16) == int(paddr, 16) and
        int(vaddr, 16) <= start < int(vaddr, 16) + int(filesz, 16)
        for vaddr, paddr, filesz, flags in segments)
    mappings = [(int(value, 16), mode) for value, mode in re.findall(
        r"^\s*\d+:\s+([0-9a-fA-F]+)\s+\d+\s+NOTYPE\s+\S+\s+\S+\s+\d+\s+\$([atd])(?:\.[^\s]+)?\s*$", text, re.M)]
    preceding = sorted((value, mode) for value, mode in mappings if start is not None and value <= start)
    # Mapping symbols can be stripped without removing the architecture attributes.
    # M-profile code cannot enter the ARM state forced by the retained CR8 loader.
    architectures = re.findall(r"Tag_CPU_arch:\s*([^\n]+)", text)
    incompatible_isa = (any("-M" in arch.upper() for arch in architectures) or
                        re.search(r"Tag_CPU_arch_profile:\s*Microcontroller\b", text) or
                        re.search(r"Tag_ARM_ISA_use:\s*(?:No|Not permitted|0)\b", text))
    if (result.returncode or not valid_header or start is None or start % 4 or not executable or
            incompatible_isa or (preceding and preceding[-1][1] != "a")):
        raise OperationError("Image requires a different startup contract: expected ELF32 little-endian ARM EABI5 EXEC with executable ARM-state __start",
                             "UNSUPPORTED_STARTUP_CONTRACT")


def source_artifact(source, member, selection, fingerprint):
    """Resolve a member from a receipt without treating its assertions as attestation."""
    if source["artifactCore"] != member["core"]:
        raise OperationError("Receipt source core differs from this row", "RECEIPT_CORE_MISMATCH")
    receipt_path = local_path(source["receiptPath"]).resolve(strict=True)
    receipt = read_json(receipt_path)
    if validate_schema(receipt, "artifact-receipt"):
        raise OperationError("Source receipt is not schema-valid", "INVALID_RECEIPT")
    prepared = source["kind"] == "prepared-receipt"
    if prepared:
        expected = ARTIFACTS_ROOT / ("import-" + receipt.get("requestId", ""))
        if (receipt.get("schemaVersion") != 2 or receipt.get("operation") != "import-images" or
                receipt_path != (expected / "receipt.json").resolve() or
                receipt.get("receiptId") != expected.name or receipt["status"] not in ("provisional", "committed")):
            raise OperationError("Prepared source must be an importer-owned provisional or committed receipt", "INVALID_PREPARED_SOURCE")
    elif receipt["status"] != "committed":
        raise OperationError("Build receipt must be committed", "RECEIPT_NOT_COMMITTED")
    if receipt["board"] != selection["board"]:
        raise OperationError("Source receipt belongs to another board", "RECEIPT_MISMATCH")
    if receipt.get("group"):
        if (receipt["group"] != selection["group"] or receipt.get("groupDefinitionSha256") != fingerprint or
                receipt["core"] != "multicore" or receipt["family"] != selection["build"]["family"]):
            raise OperationError("Source receipt group definition differs", "RECEIPT_MISMATCH")
    elif any(receipt.get(k) != member.get(k) for k in ("core", "family", "target", "config")):
        raise OperationError("Source receipt does not match this member target/config/core", "RECEIPT_MISMATCH")
    by_core = {}
    for item in receipt["artifacts"]:
        core = item.get("core", receipt["core"])
        if core in by_core:
            raise OperationError("Source receipt has duplicated cores", "RECEIPT_CORE_MISMATCH")
        path = local_path(item["path"]).resolve(strict=True)
        if prepared and not path.is_relative_to(receipt_path.parent):
            raise OperationError("Prepared artifact escapes its run directory", "INVALID_PREPARED_SOURCE")
        if path.stat().st_size != item["size"] or compute_sha256(path) != item["sha256"].lower():
            raise OperationError("Source receipt bytes changed", "ARTIFACT_HASH_MISMATCH")
        if receipt["schemaVersion"] == 2 and item.get("member") != member and core == member["core"]:
            raise OperationError("Prepared member declaration differs", "RECEIPT_MISMATCH")
        by_core[core] = dict(item, path=str(path))
    if prepared and receipt["status"] == "provisional" and (len(by_core) != 1 or set(by_core) - set(CORES)):
        raise OperationError("Provisional source must contain exactly one CR8 member", "INVALID_PREPARED_SOURCE")
    if member["core"] not in by_core:
        raise OperationError("Source receipt lacks this member", "MISSING_PAIR_MEMBERS")
    if receipt.get("group") and receipt["status"] == "committed" and set(by_core) != set(CORES):
        raise OperationError("Source group receipt is incomplete", "MISSING_PAIR_MEMBERS")
    item = by_core[member["core"]]
    provenance = item.get("provenance") if receipt["schemaVersion"] == 2 else {
        "evidence": "receipt-reported", "sourceReceiptId": receipt["receiptId"],
        "reportedGitRevision": receipt["gitRevision"], "reportedGitDirty": receipt["gitDirty"],
        "reportedCompiler": receipt["compiler"]}
    return {"kind": "file", "path": item["path"]}, provenance, item


def prepare_images(request):
    errors = validate_schema(request, "firmware-import")
    if errors:
        raise OperationError(errors[0]["message"], "INVALID_IMPORT")
    selection = request["selection"]
    resolved, diagnostics = resolve_selection(selection, "load")
    if not resolved:
        raise OperationError(diagnostics[0]["message"], diagnostics[0]["code"])
    group = resolved.get("groupMeta", {})
    if (selection["board"] != "rdk-rzv2h" or group.get("loadRecipe") != "rzv-dual-cr8-ram" or
            {m["core"] for m in group.get("members", [])} != set(CORES)):
        raise OperationError("Image preparation requires a catalogued RDK-RZ/V2H CR8 pair", "IMPORT_UNAVAILABLE", True)
    fingerprint = group_fingerprint(group)
    run_dir = ARTIFACTS_ROOT / ("import-" + request["requestId"])
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(run_dir / ".prepare.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest_path = run_dir / "preparation.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {
            "requestSha256": digest_json(request), "groupDefinitionSha256": fingerprint,
            "state": "capturing", "artifacts": {}}
        if manifest["requestSha256"] != digest_json(request) or manifest["groupDefinitionSha256"] != fingerprint:
            raise OperationError("Request ID already belongs to different inputs/group", "IMPORT_REQUEST_MISMATCH")
        atomic_json(manifest_path, manifest)
        for member in group["members"]:
            core = member["core"]
            if core not in request["sources"]:
                continue
            if core not in manifest["artifacts"]:
                cached = manifest.get("sourceContracts", {}).get(core)
                if cached:
                    source, provenance, reported = cached["source"], cached["provenance"], cached["reported"]
                else:
                    source = request["sources"][core]
                    reported = None
                    if source["kind"] in ("build-receipt", "prepared-receipt"):
                        source, provenance, reported = source_artifact(source, member, selection, fingerprint)
                    else:
                        if source["declaration"] != member:
                            raise OperationError("Declare the exact selected core and target/config for loose images", "DECLARATION_MISMATCH")
                        provenance = {"evidence": "developer-declared", "sourceReceiptId": None,
                                      "reportedGitRevision": None, "reportedGitDirty": None, "reportedCompiler": None}
                    manifest.setdefault("sourceContracts", {})[core] = {
                        "source": source, "provenance": provenance, "reported": reported}
                    atomic_json(manifest_path, manifest)
                source_path = local_path(source["path"]).resolve()
                known = source_path.is_relative_to(REPO_ROOT / "build") or source_path.is_relative_to(REPO_ROOT / "platforms/nuttx/NuttX/nuttx")
                with BuildLock() if known else nullcontext():
                    observation = capture(source, run_dir / (core + ".elf"))
                manifest.setdefault("capturePaths", {})[core] = observation["path"]
                if reported and observation["sha256"] != reported["sha256"].lower():
                    raise OperationError("Receipt source changed during capture", "ARTIFACT_HASH_MISMATCH")
                artifact = {"path": str(run_dir / (core + ".elf")), "core": core,
                            "size": observation["size"], "sha256": observation["sha256"],
                            "sourceObservation": reported.get("sourceObservation", observation) if reported else observation,
                            "provenance": provenance, "member": member}
                manifest["artifacts"][core] = artifact
                manifest["state"] = "captured"
                atomic_json(manifest_path, manifest)
            artifact = manifest["artifacts"][core]
            path = Path(artifact["path"])
            if (path.resolve() != (run_dir / (core + ".elf")).resolve() or artifact.get("member") != member or
                    artifact.get("core") != core or path.stat().st_size != artifact["size"] or
                    compute_sha256(path) != artifact["sha256"]):
                raise OperationError("Captured bytes changed or disappeared; select a new request", "ARTIFACT_HASH_MISMATCH")
            validate_startup(path)
            check_rz_allowlist(path, resolved["board"]["cores"][core]["jlinkDevice"], artifact["sha256"])
            # Optional tool discovery must not change a previously published receipt.
            if not {"entryPoint", "rttAddress"}.issubset(artifact):
                artifact.update(read_elf_metadata(path))
            artifact["checks"] = {"bytes": "sha256-verified", "address": "address-compatible", "startup": "supported",
                                  "identity": artifact["provenance"]["evidence"], "hardwareQualified": False}
            manifest["state"] = "validated"
            atomic_json(manifest_path, manifest)
        artifacts = list(manifest["artifacts"].values())
        if len(artifacts) == 2:
            actual_sources = list(manifest.get("capturePaths", {}).values())
            if len(set(a["sha256"] for a in artifacts)) != 2 or (len(actual_sources) == 2 and actual_sources[0] == actual_sources[1]):
                raise OperationError("Assign distinct image bytes to the two core roles", "DUPLICATE_CORE_IMAGE")
        receipt_path = run_dir / "receipt.json"
        if not receipt_path.exists():
            create_import_receipt(run_dir, request, artifacts, fingerprint)
        else:
            published = read_json(receipt_path)
            if (validate_schema(published, "artifact-receipt") or published["artifacts"] != artifacts or
                    published.get("requestId") != request["requestId"] or
                    published.get("receiptId") != run_dir.name or published.get("selectionId") != selection["id"] or
                    published.get("groupDefinitionSha256") != fingerprint or
                    published.get("group") != selection["group"] or
                    published.get("status") != ("committed" if len(artifacts) == 2 else "provisional") or
                    (manifest.get("receiptSha256") and compute_sha256(receipt_path) != manifest["receiptSha256"])):
                raise OperationError("Published receipt changed", "INVALID_RECEIPT")
        manifest["state"] = "published"
        manifest["receiptSha256"] = compute_sha256(receipt_path)
        atomic_json(manifest_path, manifest)
        return receipt_path, {"preparationState": "ready" if len(artifacts) == 2 else "partial",
                              "requestId": request["requestId"], "receiptId": "import-" + request["requestId"],
                              "groupDefinitionSha256": fingerprint, "artifacts": artifacts}


def cmd_import_images(args):
    try:
        receipt_path, data = prepare_images(read_json(args.input))
        print(json.dumps(make_result("import-images", "ok", data=data, receipt_path=str(receipt_path))))
        return EXIT_OK
    except (OperationError, OSError, ValueError, KeyError, RuntimeError) as error:
        return operation_failure("import-images", error)
