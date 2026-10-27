"""Durable per-probe/core mutation state and explicit recovery admission."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .verification import OperationError


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class TargetState:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.value = json.loads(self.path.read_text()) if self.path.exists() else {"cores": {}}
            if (not isinstance(self.value, dict) or not isinstance(self.value.get("cores"), dict) or
                    any(not isinstance(item, dict) or not isinstance(item.get("state"), str)
                        for item in self.value["cores"].values()) or
                    (self.value.get("verifiedPair") is not None and not isinstance(self.value["verifiedPair"], dict))):
                raise ValueError("invalid core journal")
        except (OSError, ValueError, TypeError) as error:
            raise OperationError("Target journal is unreadable; inspect it before recovery", "RECOVERY_REQUIRED", True) from error

    def require_ready(self, cores, recover=False):
        affected = [core for core in cores if self.value["cores"].get(core, {}).get("state") in
                    ("started", "indeterminate/recovery-required")]
        if self.value.get("pending") and not recover:
            raise OperationError("A target operation was interrupted; explicitly select recovery reload", "RECOVERY_REQUIRED", True)
        if affected and not recover:
            raise OperationError("Target state is indeterminate for " + ", ".join(affected) +
                                 "; explicitly select recovery reload", "RECOVERY_REQUIRED", True)

    def require_loaded(self, identity):
        self.require_ready(["cr8_0", "cr8_1"])
        pair = self.value.get("verifiedPair", {})
        if (not pair or pair.get("pairSha256") != identity.get("pairSha256") or
                pair.get("groupDefinitionSha256") != identity.get("groupDefinitionSha256") or
                pair.get("artifactDigests") != identity.get("artifactDigests") or
                any(self.value["cores"].get(core, {}).get("state") != "verified" or
                    self.value["cores"][core].get("operationInstanceId") != pair.get("operationInstanceId") or
                    self.value["cores"][core].get("sha256") != digest
                    for core, digest in identity["artifactDigests"].items())):
            raise OperationError("Loaded image history differs from this pair; select Load Both first", "LOADED_IMAGE_MISMATCH", True)

    def history(self):
        pair = self.value.get("verifiedPair")
        if pair:
            try:
                if not isinstance(pair.get("artifactDigests"), dict) or set(pair["artifactDigests"]) != {"cr8_0", "cr8_1"}:
                    raise OperationError("Incomplete pair history", "LOADED_IMAGE_MISMATCH")
                self.require_loaded(pair)
            except OperationError:
                pair = None
        return {"state": "recorded" if self.path.exists() else "none", "cores": self.value["cores"],
                "verifiedPair": pair,
                "recoveryRequired": bool(self.value.get("pending") or any(
                    self.value["cores"].get(core, {}).get("state") in ("started", "indeterminate/recovery-required")
                    for core in ("cr8_0", "cr8_1"))),
                "lastOperation": self.value.get("lastOperation")}

    def record(self, cores, state, receipt_id, *, digests=None, group=None, pair_id=None,
               operation_id=None, timestamp=None, steps=None, log_path=None):
        cores = list(cores)
        self.value["pending"] = state == "started"
        self.value.pop("verifiedPair", None)
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        for core in cores:
            self.value["cores"][core] = {"state": state, "receiptId": receipt_id}
            if digests and core in digests and group and pair_id and operation_id:
                self.value["cores"][core].update(sha256=digests[core], groupDefinitionSha256=group,
                    pairSha256=pair_id, operationInstanceId=operation_id, timestamp=timestamp)
        operation = {"state": state, "receiptId": receipt_id, "operationInstanceId": operation_id,
                     "timestamp": timestamp, "steps": steps or [], "logPath": log_path}
        self.value["lastOperation"] = operation
        if (state == "verified" and set(cores) == {"cr8_0", "cr8_1"} and digests and
                set(digests) == set(cores) and group and pair_id and operation_id):
            self.value["verifiedPair"] = dict(operation, artifactDigests=digests,
                groupDefinitionSha256=group, pairSha256=pair_id)
        atomic_json(self.path, self.value)
