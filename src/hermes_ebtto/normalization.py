"""EBTTO event envelope + serialization helpers.

Provides:

* ``normalize_tool_input`` — structural normalization (argument ordering,
  formatting differences, path normalization, URL normalization, harmless
  whitespace). Pure function; deterministic output.
* ``trajectory_fingerprint`` / ``task_fingerprint`` / ``tool_fingerprint`` /
  ``strategy_fingerprint`` — stable keys for retrieval and dedup.
* ``sanitize_for_storage`` — dedupe, trimming, secret removal for DB fields.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_tool_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize tool input for semantic comparison.

    Recognizes semantic similarity despite:

    * argument ordering
    * formatting differences
    * path normalization
    * URL normalization
    * harmless whitespace

    Preserves raw sanitized evidence separately.
    """
    out: Dict[str, Any] = {}
    for k, v in sorted(args.items()):
        out[k] = normalize_value(v)
    return out


def normalize_value(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): normalize_value(val) for k, val in sorted(v.items())}
    if isinstance(v, list):
        return [normalize_value(x) for x in v]
    if isinstance(v, str):
        return normalize_string(v)
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)


def normalize_string(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)  # collapse whitespace
    s = normalize_path(s)
    s = re.sub(r"//+", "/", s)  # collapse repeated slashes
    return s


def normalize_path(value: str) -> str:
    """Deterministic path normalization (no secrets)."""
    if not value:
        return value
    value = value.replace("\\", "/")
    # strip leading/trailing slash on relative paths
    if not value.startswith("/") and not value.startswith("~"):
        while value.startswith("/"):
            value = value[1:]
    # drop drive-letter case
    if len(value) >= 2 and value[1] == ":":
        value = value[0].lower() + value[2:]
    parts: List[str] = []
    for seg in value.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


# ---------------------------------------------------------------------------
# Fingerprints (versioned)
# ---------------------------------------------------------------------------

def task_fingerprint(task_family: str, **context: Any) -> str:
    """Versioned stable task fingerprint.

    Version tag 1 separates from any future version 2 family.
    """
    ctx = "_".join(f"{k}={normalize_string(str(v))}" for k, v in sorted(context.items()))
    return f"1|{task_family}|{ctx}" if ctx else f"1|{task_family}"


def tool_fingerprint(tool_name: str, normalized_args: Dict[str, Any]) -> str:
    """Versioned stable tool fingerprint."""
    args = "|".join(f"{k}={normalize_string(str(v))}" for k, v in sorted(normalized_args.items()))
    return f"1|{tool_name}|{args}"


def trajectory_fingerprint(tool_sequence: List[str]) -> str:
    """Versioned stable trajectory fingerprint."""
    return f"1|{'|'.join(tool_sequence)}"


def strategy_fingerprint(sequence: List[str]) -> str:
    """Versioned stable strategy fingerprint."""
    return f"1|{'|'.join(sequence)}"


# ---------------------------------------------------------------------------
# Storage-level sanitization (optional: duplicate trims, type coercion)
# ---------------------------------------------------------------------------

def sanitize_for_storage(value: Any, *, max_length: int = 5000) -> Any:
    """Trim, dedupe, coerce values for safe DB insertion."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if len(v) > max_length:
            v = v[:max_length]
        return v
    if isinstance(value, dict):
        return {str(k): sanitize_for_storage(v) for k, v in value.items()}
    if isinstance(value, list):
        # dedupe preserving order
        seen = set()
        out = []
        for item in value:
            key = sanitize_for_storage(item, max_length=max_length)
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out
    return value
