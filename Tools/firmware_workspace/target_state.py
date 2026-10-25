"""Durable per-probe/core mutation state and explicit recovery admission."""
from __future__ import annotations

import json
import os
import tempfile
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
            if not isinstance(self.value.get("cores"), dict):
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

    def record(self, cores, state, receipt_id):
        self.value["pending"] = state == "started"
        for core in cores:
            self.value["cores"][core] = {"state": state, "receiptId": receipt_id}
        atomic_json(self.path, self.value)
