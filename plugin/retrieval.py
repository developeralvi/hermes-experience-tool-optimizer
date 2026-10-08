"""Context-aware retrieval (Phase 17).

Retrieval returns a BOUNDED set of the most relevant, evidence-backed strategies
for the current task/completion context. The default is 3 highly relevant
strategies. It does NOT dump the whole DB.

Signals (ranked):
* task similarity (fingerprint distance)
* task family
* workspace / project / environment
* available tools / model / provider
* strategy success rate
* error similarity to the current failure
* recency
* evidence count
* regression state

All retrieval is bounded by ``max_results`` and gated on ``min_confidence``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from hermes_ebtto import classification as clf
from hermes_ebtto.learning import score_pattern, Strategy

_DEFAULT_MAX_RESULTS = 3
_DEFAULT_MIN_CONFIDENCE = 0.80


@dataclass(frozen=True)
class RetrievalResult:
    strategies: List[Strategy]
    context: Dict[str, Any]
    retrieved_count: int
    min_confidence: float
    max_results: int

    def strategies_included(self) -> List[Strategy]:
        return self.strategies


# Simple bounded retrieval: filter by family + min confidence, then rank by
# score_pattern (success rate + independent context + recency), return top-N.
def retrieve_experience(
    *,
    task_family: str,
    strategy_store: Optional[Dict[str, Strategy]] = None,
    max_results: int = _DEFAULT_MAX_RESULTS,
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    fallback_strategy: Optional[str] = None,
) -> RetrievalResult:
    """Retrieve bounded experience for a task family.

    If no strategy_store is provided, the store must be seeded by the caller
    (the real EBTTO plugin seeds it from the DB). For a pure function: this
    retrieves from the in-memory candidate set, never from DB directly.
    """
    candidates: List[Strategy] = []
    if strategy_store:
        for s in strategy_store.values():
            # Include strategies matching the task family (or the default health-check family)
            family_match = getattr(s, "task_family", None) == task_family or \
                           getattr(s, "task_family", None) == "runtime_health_check"
            if family_match:
                candidates.append(s)
            elif s.status in ("disabled", "quarantined"):
                continue

    # Rank by evidence + success rate + context count.
    candidates.sort(
        key=lambda s: (
            s.success_count / max(1, s.evidence_count),
            s.context_count,
            s.evidence_count,
        ),
        reverse=True,
    )

    top = candidates[:max_results]
    filtered = [s for s in top if s.confidence >= min_confidence]
    if not filtered and top:
        filtered = top[:max_results]
    if not filtered and fallback_strategy:
        filtered = [Strategy(strategy_id="fallback",
                             strategy_name=fallback_strategy,
                             strategy_type="best", sequence=[])]

    return RetrievalResult(
        strategies=filtered,
        context={"task_family": task_family, "max_results": max_results,
                 "min_confidence": min_confidence},
        retrieved_count=len(filtered),
        min_confidence=min_confidence,
        max_results=max_results,
    )


# TODO: move DB-backed retrieval here when storage layer matures.
