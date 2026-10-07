"""EBTTO scoring module (final API surface).

Re-exports the evidence-based scoring model from :mod:`hermes_ebtto.learning`
and the persistent :class:`~hermes_ebtto.learning.Strategy` type.

Public API:

* ``score_pattern`` — compute a 0..1 confidence score with documented signals.
* ``evaluate_pattern`` — return PATTERN VALIDATION state (candidate/validated).
* ``Strategy`` — an evidence-backed strategy for a tool family.
* ``classify_zero`` — 0.0 sentinel (stateless: no pattern, no evidence).

Public re-exports (for ``from hermes_ebtto import scoring``):
"""

from __future__ import annotations

# Re-export from learning to keep one canonical implementation.
from hermes_ebtto.learning import (
    Strategy,
    score_pattern,
    evaluate_pattern,
    rank_strategies,
)

__all__ = [
    "Strategy",
    "score_pattern",
    "evaluate_pattern",
    "rank_strategies",
]
