"""Shared utilities: JSON round-trip, secret redaction helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def json_dumps(obj: Any, **kwargs) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, **kwargs)


def json_loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def is_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except (json.JSONDecodeError, TypeError):
        return False
