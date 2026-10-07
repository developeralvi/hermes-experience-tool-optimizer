"""Event schema for EBTTO.

Every trajectory event carries correlation fields so that a single tool call,
its turn, and its task can be joined without ambiguity:

* schema_version — EBTTO schema version for this event type
* event_id — unique event id (UUID4)
* task_id — task fingerprint (stable identifier)
* session_id — Hermes session id
* turn_id — turn identifier
* tool_call_id — Hermes tool call id
* timestamp — UTC ISO-8601, UTC epoch seconds, and local milliseconds
* sequence_number — 1-based position in the event stream for this task

Everything stored is OBSERVABLE EXECUTION DECISION + OUTCOME. Chain-of-thought,
private model reasoning, and any other hidden trace are never stored.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

EVENT_SCHEMA_VERSION = 1
TASK_SCHEMA_VERSION = 1
STRATEGY_SCHEMA_VERSION = 1
METRIC_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utcnow_epoch_ms() -> int:
    return int(time.monotonic() * 1000)


def _utcnow_epoch_s() -> float:
    return time.time()


def new_id() -> str:
    """UUID4 string (stable, unique, no randomness into text)."""
    import uuid

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Core event types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """A logical task the agent attempted to accomplish.

    Attributes not provided on construction are filled by the recorder.
    ``fingerprint`` is the semantic task family key used for retrieval.
    """

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str = field(default_factory=new_id, init=False, repr=False)
    task_fingerprint: str
    task_family: str
    sanitized_intent: Optional[str] = None
    workspace_identifier: Optional[str] = None
    profile: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso, init=False, repr=False)
    created_at_epoch_ms: int = field(default_factory=_utcnow_epoch_ms, init=False, repr=False)
    tags: tuple = field(default_factory=tuple, init=False, repr=False)


@dataclass(frozen=True)
class Turn:
    """One agent turn (one user message + model response loop)."""

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str
    session_id: str
    turn_id: str = ""
    start_timestamp: str = field(default_factory=_utcnow_iso, init=False, repr=False)
    start_epoch_ms: int = field(default_factory=_utcnow_epoch_ms, init=False, repr=False)
    end_timestamp: Optional[str] = None
    end_epoch_ms: Optional[int] = None
    tool_count: int = 0
    total_duration_ms: int = 0
    # Outcome is set by the outcome recorder after the turn settles.
    outcome: Optional[str] = None


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation.

    ``raw_args`` is the sanitized copy actually sent; ``original_args`` preserves
    the raw (potentially secret-bearing) input for audit, never stored to DB.
    """

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    order_number: int = 1
    attempt_number: int = 1
    raw_args: Dict[str, Any] = field(default_factory=dict)
    sanitized_args: Dict[str, Any] = field(default_factory=dict)
    result_status: str = "FAILURE"
    duration_ms: int = 0
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    classified: bool = False
    classified_class: Optional[str] = None
    classifier_version: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=_utcnow_iso, init=False, repr=False)
    created_at_epoch_ms: int = field(default_factory=_utcnow_epoch_ms, init=False, repr=False)


@dataclass(frozen=True)
class Outcome:
    """Outcome of a turn, recorded by the success detector.

    Supports ``SUCCESS | FAILURE | PARTIAL | UNCERTAIN`` plus evidence.
    """

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    outcome_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str
    turn_id: str
    result: str  # SUCCESS / FAILURE / PARTIAL / UNCERTAIN
    confidence: float  # 0..1
    evidence: Dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=_utcnow_iso, init=False, repr=False)
    recorded_at_epoch_ms: int = field(default_factory=_utcnow_epoch_ms, init=False, repr=False)


@dataclass(frozen=True)
class Error:
    """A classified tool-call failure."""

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    error_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    error_class: str  # wrong_tool, wrong_arguments, ...
    confidence: float
    error_message: Optional[str]
    evidence: Dict[str, Any]
    created_at: str = field(default_factory=_utcnow_iso, init=False, repr=False)


@dataclass(frozen=True)
class Trajectory:
    """A full, sanitized, normalized task trajectory for a task family."""

    schema_version: int = field(default=TASK_SCHEMA_VERSION, init=False, repr=False)
    event_id: str = field(default_factory=new_id, init=False, repr=False)
    task_id: str
    task_fingerprint: str
    task_family: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    outcome: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: int = 0
    created_at: str = field(default_factory=_utcnow_iso, init=False, repr=False)
    updated_at: Optional[str] = None

    def add_call(self, call: ToolCall) -> None:
        self.tool_calls.append(call)
        if call.result_status == "SUCCESS":
            self.success_count += 1
        else:
            self.failure_count += 1
        self.total_duration_ms += call.duration_ms
        self.updated_at = _utcnow_iso()


# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------

def normalize_path(value: Any) -> str:
    """Deterministic, secret-safe path normalization.

    Normalizes separators, strips drive-letter case, collapses ``..`` and
    ``.`` segments, and lowercases. Does NOT store the original.
    """
    if value is None:
        return ""
    s = str(value).strip()
    # Percent-decode nothing: anything that looks like a credential stays
    # opaque. Only path structural normalization.
    import re

    s = re.sub(r"\\\\+", "/", s)
    s = re.sub(r"/+", "/", s)
    if len(s) >= 2 and s[1] == ":":
        s = s[0].lower() + s[2:]
    parts: List[str] = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def fingerprint_tool(tool_name: str, sanitized_args: Dict[str, Any]) -> str:
    """Semantic tool fingerprint: name + normalized, de-duped arg keys."""
    args = {str(k): str(v) for k, v in sorted(sanitized_args.items())}
    return f"{tool_name}|{'|'.join(f'{k}:{args[k]}' for k in sorted(args))}"


def fingerprint_task(  # noqa: PLR0913
    task_fingerprint: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    workspace_identifier: Optional[str] = None,
    profile: Optional[str] = None,
) -> str:
    """Stable task fingerprint combining task family + context."""
    ctx = "+".join(
        str(v)
        for v in (model, provider, workspace_identifier, profile)
        if v
    )
    return f"{task_fingerprint}|{ctx}" if ctx else task_fingerprint


def fingerprint_strategy(sequence: List[str]) -> str:
    """Stable fingerprint of a normalized tool sequence."""
    return "|".join(sequence)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_task(*, task_fingerprint: str, task_family: str, **overrides) -> Task:
    task = Task(task_fingerprint=task_fingerprint, task_family=task_family)
    for k, v in overrides.items():
        if hasattr(task, k):
            setattr(task, k, v)
    return task


def build_tool_call(
    *,
    task_id: str,
    turn_id: str,
    tool_call_id: str,
    tool_name: str,
    args: Dict[str, Any],
    order_number: int = 1,
    attempt_number: int = 1,
    result_status: str = "FAILURE",
    duration_ms: int = 0,
    error_class: Optional[str] = None,
    error_message: Optional[str] = None,
) -> ToolCall:
    return ToolCall(
        task_id=task_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        order_number=order_number,
        attempt_number=attempt_number,
        raw_args=dict(args),
        sanitized_args=dict(args),  # sanitized before storing
        result_status=result_status,
        duration_ms=duration_ms,
        error_class=error_class,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def event_to_dict(obj: Any) -> Dict[str, Any]:
    """Serialize a dataclass to a plain dict for DB insertion / JSON export."""
    return asdict(obj)


def dict_to_event(schema_version: int, data: Dict[str, Any]) -> Any:
    """Rebuild a dataclass from a dict (round-trips through asdict).

    Computed fields (event_id, created_at, etc.) are NOT init-able on the
    dataclasses, so we drop them before constructing.
    """
    data = dict(data)
    data.pop("schema_version", None)
    data.pop("event_id", None)
    data.pop("task_id", None)
    data.pop("created_at", None)
    data.pop("created_at_epoch_ms", None)
    data.pop("tags", None)
    data.pop("outcome_id", None)
    data.pop("recorded_at", None)
    data.pop("recorded_at_epoch_ms", None)

    # Determine type by primary key field
    if "task_fingerprint" in data:
        return Task(**data)
    elif "tool_call_id" in data:
        return ToolCall(**data)
    elif "outcome_id" in data:
        return Outcome(**data)
    elif "error_id" in data:
        return Error(**data)
    raise ValueError(f"unknown event type: {data.get('task_fingerprint', data.get('tool_call_id'))}")
