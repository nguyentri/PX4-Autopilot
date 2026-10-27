"""Shared operation admission and exact receipt/artifact identity checks."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .artifacts import ARTIFACTS_ROOT, compute_sha256
from .catalog import group_fingerprint, resolve_selection
from .contracts import REPO_ROOT, validate_schema


class OperationError(ValueError):
    def __init__(self, message, code="INVALID_OPERATION", blocked=False):
        super().__init__(message)
        self.code = code
        self.blocked = blocked


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (OSError, ValueError, TypeError) as error:
        raise OperationError(f"Cannot read input: {error}", "INVALID_INPUT") from error
    if not isinstance(value, dict):
        raise OperationError("Input must be a JSON object", "INVALID_INPUT")
    return value


def admitted_inputs(args, operation):
    selection = read_json(args.selection)
    resolved, diagnostics = resolve_selection(selection, operation=operation)
    if not resolved:
        diagnostic = diagnostics[0]
        raise OperationError(diagnostic["message"], diagnostic["code"],
                             diagnostic["code"].endswith("_UNAVAILABLE"))
    receipt = read_json(args.receipt)
    errors = validate_schema(receipt, "artifact-receipt")
    if errors:
        raise OperationError(errors[0]["message"], "INVALID_RECEIPT")
    if receipt["status"] != "committed":
        raise OperationError("Only committed artifact receipts may be used", "RECEIPT_NOT_COMMITTED")
    expected = {"board": selection["board"], "core": selection["core"],
                "selectionId": selection["id"], "family": selection["build"]["family"],
                "target": selection["build"].get("target"),
                "config": selection["build"].get("config"), "group": selection.get("group")}
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise OperationError(f"Receipt {field} does not match the selected profile", "RECEIPT_MISMATCH")
    members = resolved.get("groupMeta", {}).get("members", [])
    if members and receipt.get("groupDefinitionSha256") != group_fingerprint(resolved["groupMeta"]):
        raise OperationError("Group definition changed or is absent from this receipt; rebuild the selected group", "RECEIPT_MISMATCH")
    expected_cores = [member["core"] for member in members] if members else [selection["core"]]
    artifacts = receipt["artifacts"]
    if len(artifacts) != len(expected_cores):
        raise OperationError("Receipt does not contain the complete image set", "MISSING_PAIR_MEMBERS")
    by_core = {}
    for artifact in artifacts:
        core = artifact.get("core")
        if core is None and len(expected_cores) == 1:
            core = receipt["core"]  # Legacy single-image receipt has an unambiguous core.
        if core not in expected_cores or core in by_core:
            raise OperationError("Receipt core membership is invalid or duplicated", "RECEIPT_CORE_MISMATCH")
        if receipt["schemaVersion"] == 2 and artifact.get("member") != next((m for m in members if m["core"] == core), None):
            raise OperationError("Imported member declaration differs from the selected group", "RECEIPT_MISMATCH")
        source = Path(artifact["path"])
        source = source if source.is_absolute() else REPO_ROOT / source
        try:
            if source.stat().st_size != artifact["size"] or compute_sha256(source) != artifact["sha256"].lower():
                raise OperationError("Artifact changed after receipt publication", "ARTIFACT_HASH_MISMATCH")
        except OSError as error:
            raise OperationError(f"Artifact is unavailable: {source.name}", "ARTIFACT_NOT_FOUND") from error
        by_core[core] = dict(artifact, path=str(source.resolve()), core=core)
    requested_core = getattr(args, "core", None)
    if requested_core and requested_core not in by_core:
        raise OperationError("Requested core is absent from this receipt", "RECEIPT_CORE_MISMATCH")
    actual = prepared_identity(selection, resolved, receipt, by_core)
    if ((getattr(args, "expect_receipt_id", None) and args.expect_receipt_id != receipt["receiptId"]) or
            (getattr(args, "expect_pair_sha256", None) and args.expect_pair_sha256 != actual.get("pairSha256"))):
        raise OperationError("Prepared receipt or pair bytes differ from the frozen request", "PREPARED_IDENTITY_MISMATCH")
    return selection, resolved, receipt, by_core


def prepared_identity(selection, resolved, receipt, artifacts):
    digests = {core: item["sha256"].lower() for core, item in artifacts.items()}
    definition = group_fingerprint(resolved["groupMeta"]) if resolved.get("groupMeta") else None
    pair = None
    if definition and set(digests) == {"cr8_0", "cr8_1"}:
        payload = [selection["board"], selection["group"], definition,
                   [[core, digests[core]] for core in ("cr8_0", "cr8_1")]]
        pair = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return {"receiptId": receipt["receiptId"], "artifactDigests": digests,
            "groupDefinitionSha256": definition, "pairSha256": pair}


def copy_verified(artifact, directory):
    """Copy first, then verify the exact private bytes consumed by another tool."""
    target = directory / (artifact["sha256"] + "-" + artifact["core"] + ".elf")
    with open(artifact["path"], "rb") as source, open(target, "xb") as output:
        shutil.copyfileobj(source, output)
        output.flush()
        os.fsync(output.fileno())
    if target.stat().st_size != artifact["size"] or compute_sha256(target) != artifact["sha256"].lower():
        target.unlink()
        raise OperationError("Artifact changed while taking a snapshot", "ARTIFACT_HASH_MISMATCH")
    target.chmod(0o400)
    return target


@contextmanager
def artifact_snapshots(artifacts):
    with tempfile.TemporaryDirectory(prefix="firmware-load-") as directory:
        root = Path(directory)
        yield {core: copy_verified(artifact, root) for core, artifact in artifacts.items()}


def debug_snapshot(artifact):
    root = ARTIFACTS_ROOT / ".debug"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix="session-", dir=root))
    return copy_verified(artifact, directory)
