"""Deterministic failure classification (Phase 10).

Each classification carries:

* class          - canonical error class
* confidence     - 0..1
* evidence       - machine-readable evidence (source error, tool config, ...
* classifier_version

Classification is DETERMINISTIC and rule-based from observable evidence — never
an LLM guess. We do NOT blame the LLM when the tool/service/environment failed.

Result categories (minimum):

wrong_tool
wrong_arguments
invalid_argument_schema
wrong_order
missing_prerequisite
stale_state
wrong_assumption
repeated_call
unnecessary_retry
poor_recovery
tool_failure
network_failure
timeout
permission_failure
external_service_failure
environment_failure
user_input_failure
unknown
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Certify: classifier output is deterministic; no confidence below 0.0.
CONFIDENCE_MIN = 0.0


# ---------------------------------------------------------------------------
# Canonical classes
# ---------------------------------------------------------------------------

ERROR_CLASSES = [
    "wrong_tool",
    "wrong_arguments",
    "invalid_argument_schema",
    "wrong_order",
    "missing_prerequisite",
    "stale_state",
    "wrong_assumption",
    "repeated_call",
    "unnecessary_retry",
    "poor_recovery",
    "tool_failure",
    "network_failure",
    "timeout",
    "permission_failure",
    "external_service_failure",
    "environment_failure",
    "user_input_failure",
    "unknown",
]


@dataclass(frozen=True)
class Classification:
    """A single deterministic classification of a tool-call failure."""

    schema_version: int = field(default=1, init=False, repr=False)
    class_: str = field(repr=False)
    confidence: float
    evidence: Dict[str, Any]
    message: Optional[str] = None
    classifier_version: str = field(default="1.0.0", init=False, repr=False)

    @property
    def class_name(self) -> str:
        return self.class_

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be 0..1")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def classify_error(
    *,
    tool_name: str,
    result_message: Optional[str],
    error_type: Optional[str],
    error_code: Optional[str],
    status_code: Optional[int],
    error_class: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    model_output: Optional[str] = None,
) -> Classification:
    """Return a deterministic Classification from observable evidence.

    ``model_output`` is checked LAST -- only if no rule matched.
    """
    evidence = dict(evidence or {})
    evidence["tool_name"] = tool_name
    evidence["error_type"] = error_type
    evidence["error_code"] = error_code
    evidence["status_code"] = status_code

    # 1. Explicit error class given by the tool/error system.
    if error_class:
        canonical = _canonicalize(error_class)
        if canonical:
            return Classification(
                class_=canonical,
                confidence=0.95,
                evidence=evidence,
                message=f"Classified as {canonical}",
            )

    # 2. Status-code based.
    if status_code is not None:
        return _classify_by_status(status_code, evidence)

    # 3. Message-based heuristics (deterministic keyword rules).
    msg = (result_message or "").lower()
    if not msg:
        msg = (error_type or "").lower()
    if not msg:
        msg = (error_code or "").lower()

    if _match(msg, ["timeout", "timed out", "deadline exceeded", "gateway timeout"]):
        return Classification(class_="timeout", confidence=0.85, evidence=evidence)
    if _match(msg, ["network", "connection refused", "dns", "resolved", "errno", "socket"]):
        return Classification(class_="network_failure", confidence=0.80, evidence=evidence)
    if _match(msg, ["permission", "denied", "forbidden", "unauthorized", "ephemeral"]):
        return Classification(class_="permission_failure", confidence=0.80, evidence=evidence)
    if _match(msg, ["tool error", "tool failed", "executable not found", "command failed", "exit code"]):
        return Classification(class_="tool_failure", confidence=0.75, evidence=evidence)
    if _match(msg, ["stale", "not found", "expired", "used", "already"]):
        return Classification(class_="stale_state", confidence=0.70, evidence=evidence)
    if _match(msg, ["schema", "invalid", "missing", "unexpected", "type"]):
        return Classification(class_="invalid_argument_schema", confidence=0.80, evidence=evidence)
    if _match(msg, ["wrong", "incorrect", "invalid tool", "unknown tool", "no such tool"]):
        return Classification(class_="wrong_tool", confidence=0.85, evidence=evidence)
    if _match(msg, ["retry", "repeated", "duplicate"]):
        return Classification(class_="repeated_call", confidence=0.60, evidence=evidence)
    if _match(msg, ["prerequisite", "missing", "required", "cannot proceed", "must be"]):
        return Classification(class_="missing_prerequisite", confidence=0.85, evidence=evidence)

    # 4. Model-output guess (last resort). Deterministic, not learned.
    if model_output:
        mo = model_output.lower()
        if _match(mo, ["wrong tool", "wrong arguments", "bad arguments", "tool error"]):
            return Classification(class_="wrong_arguments", confidence=0.65, evidence=evidence)
        if _match(mo, ["repeat", "retry", "same call", "previous"]):
            return Classification(class_="repeated_call", confidence=0.60, evidence=evidence)

    # 5. Fallback.
    return Classification(class_="unknown", confidence=0.20, evidence=evidence)


def _canonicalize(value: str) -> Optional[str]:
    """Map free-form error class to a canonical ERROR_CLASSES member."""
    v = value.lower().strip()
    for canonical in ERROR_CLASSES:
        if canonical in v or v in canonical:
            return canonical
    return None


def _classify_by_status(status_code: int, evidence: Dict[str, Any]) -> Classification:
    if 500 <= status_code < 600:
        return Classification(
            class_="external_service_failure", confidence=0.80, evidence=evidence
        )
    if status_code == 429:
        return Classification(class_="network_failure", confidence=0.75, evidence=evidence)
    if status_code == 401:
        return Classification(class_="permission_failure", confidence=0.80, evidence=evidence)
    if status_code == 403:
        return Classification(class_="permission_failure", confidence=0.80, evidence=evidence)
    if status_code == 404:
        return Classification(class_="stale_state", confidence=0.65, evidence=evidence)
    if status_code >= 400:
        return Classification(class_="wrong_arguments", confidence=0.70, evidence=evidence)
    return Classification(class_="unknown", confidence=0.20, evidence=evidence)


def _match(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


# ---------------------------------------------------------------------------
# Result-status inference from evidence (Phase 11)
# ---------------------------------------------------------------------------


def infer_result_status(
    *,
    result_message: Optional[str],
    error_type: Optional[str],
    error_code: Optional[str],
    status_code: Optional[int],
    observed_expected: bool = False,
    health_check: bool = False,
) -> str:
    """Infer result status: SUCCESS / FAILURE / PARTIAL / UNCERTAIN.

    A result is SUCCESS when it "behaved as expected": exit 0, expected file
    present, health endpoint responded, explicit verifier confirms, etc.
    """
    if observed_expected:
        return "SUCCESS"
    if health_check:
        return "SUCCESS"
    if status_code is not None and status_code >= 200 and status_code < 300:
        return "SUCCESS"
    if error_type:
        if error_type.lower() in ("success", "ok", "no error"):
            return "SUCCESS"
    if result_message:
        msg = (result_message or "").lower()
        # Observable success signals in output text
        if any(
            kw in msg
            for kw in ("succeeded", "success", "exit 0", "exit_code=0",
                       "output present", "all tests passed", "ok")
        ):
            return "SUCCESS"
    return "FAILURE"
    if _match(msg, ["error", "failed", "failed with", "denied", "refused", "timed out"]):
        return "FAILURE"
    if _match(msg, ["partial", "completed with error", "success but"]):
        return "PARTIAL"
    if _match(msg, ["unclear", "unknown", "ambiguous", "not confirmed"]):
        return "UNCERTAIN"
    return "SUCCESS" if observed_expected else "FAILURE"
