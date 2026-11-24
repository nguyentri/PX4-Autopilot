"""Schema validation and result contracts for the firmware workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import jsonschema
    from jsonschema import Draft7Validator
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    Draft7Validator = None

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID_INPUT = 2
EXIT_BLOCKED_RECOVERY = 3
EXIT_CANCELLED = 130

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "Tools" / "vscode_extension" / "px4-db" / "schemas"
PROFILES_DIR = REPO_ROOT / "Tools" / "vscode_extension" / "px4-db" / "profiles"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def get_schema_path(schema_name: str) -> Path:
    """Resolve full path to a named schema file."""
    if not schema_name.endswith(".schema.json"):
        schema_name = f"{schema_name}.schema.json"
    return SCHEMAS_DIR / schema_name


def load_schema(schema_name: str) -> Dict[str, Any]:
    """Load JSON schema by name with caching."""
    if schema_name not in _SCHEMA_CACHE:
        path = get_schema_path(schema_name)
        if not path.is_file():
            raise FileNotFoundError(f"Schema not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            _SCHEMA_CACHE[schema_name] = json.load(f)
    return _SCHEMA_CACHE[schema_name]


def validate_schema(instance: Any, schema_name: str) -> List[Dict[str, str]]:
    """Validate data instance against a named schema.

    Returns a list of diagnostic error dicts; empty list if valid.
    """
    if not HAS_JSONSCHEMA:
        return [{
            "level": "error",
            "code": "MISSING_JSONSCHEMA_MODULE",
            "message": "Python jsonschema package is required for schema validation",
            "path": ""
        }]

    schema = load_schema(schema_name)
    validator = Draft7Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: e.path):
        loc = "/".join(str(p) for p in err.path)
        errors.append({
            "level": "error",
            "code": "SCHEMA_VALIDATION_ERROR",
            "message": err.message,
            "path": f"/{loc}" if loc else "/"
        })
    return errors


def make_diagnostic(level: str, code: str, message: str, path: str = "") -> Dict[str, str]:
    """Create a standardized diagnostic dictionary."""
    return {
        "level": level,
        "code": code,
        "message": message,
        "path": path
    }


def make_result(
    operation_id: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[List[Dict[str, str]]] = None,
    child_exit_code: Optional[int] = None,
    receipt_path: Optional[str] = None
) -> Dict[str, Any]:
    """Create a standardized OperationResult dictionary."""
    return {
        "protocolVersion": 1,
        "operationId": operation_id,
        "status": status,
        "data": data or {},
        "diagnostics": diagnostics or [],
        "childExitCode": child_exit_code,
        "receiptPath": receipt_path
    }
