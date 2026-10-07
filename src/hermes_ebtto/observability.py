"""EBTTO observability hooks.

Publishes machine-readable events for the dashboard/CLI record:

* ``trajectory_started``
* ``tool_call_started``
* ``tool_call_completed``
* ``turn_completed``
* ``session_started``
* ``session_ended``
* ``experience_retrieved``
* ``learning_event``
* ``evaluation_recorded``
* ``regression_detected``

Implementation is a thin publisher; a JSONL sink is included for CLI use.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class Publisher:
    """Emits events to subscribed sinks. Thread-safe."""

    def __init__(self, name: str = "ebtto"):
        self.name = name
        self._sinks: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.RLock()

    def subscribe(self, sink: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._sinks.append(sink)

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {
            "event_id": _new_id(),
            "schema_version": 1,
            "event_type": event_type,
            "timestamp": _utcnow_iso(),
            "publisher": self.name,
            **payload,
        }
        with self._lock:
            for sink in self._sinks:
                try:
                    sink(event)
                except Exception:
                    pass  # fail open; observability must never crash EBTTO

    def jsonl(self, path: str) -> Callable[[Dict[str, Any]], None]:
        """Return a sink that appends JSONL to *path* (best-effort)."""
        import os

        def sink(event: Dict[str, Any]) -> None:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
            except Exception:
                pass

        return sink


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def events_collection() -> List[Dict[str, Any]]:
    """Return the in-memory event pool (for CLI dump)."""
    return []


# Built-in JSONL sink (future: pluggable adapter).
def start_jsonl_sink(path: str) -> None:
    """Start a JSONL sink for internal events."""
    pass
