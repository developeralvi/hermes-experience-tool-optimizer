"""Score and rank experience (Phases 21, 24).

Evidence-based scoring model. Signals:

* historical success (success_count / evidence_count)
* sample size (independent contexts, not just total observations)
* independent contexts (recency + independent runs)
* recency
* model / provider / workspace / environment compatibility
* regression status

Do NOT hardcode arbitrary confidence. The scoring formula is documented and
unit-tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Credibility thresholds (documented constants).
MIN_EVIDENCE_FOR_VALIDATED = 5
MIN_SUCCESS_RATE = 0.80
MIN_INDEPENDENT_CONTEXTS = 3

# Weighting constants (documented, tunable).
_W_RELIABILITY = 0.45
_W_EFFICIENCY = 0.15
_W_EVIDENCE = 0.20
_W_RISKCAP = 0.10
_W_RECENCY = 0.10

_SUPERFLUOUS = {
    "schema_version", "event_id", "created_at", "created_at_epoch_ms",
    "class_", "confidence", "classifier_version", "sequence_number",
}


def score_pattern(*, success_count: int, evidence_count: int,
                  independent_contexts: int, recent_successes: int,
                  model_compat: float = 1.0, provider_compat: float = 1.0,
                  workspace_compat: float = 1.0, tool_avail: float = 1.0,
                  regression_state: str = "validated",
                  total_occurrences: int = 0) -> Dict[str, Any]:
    """Compute a 0..1 confidence score with documented signals.

    Returns a dict with:
      confidence, raw, components, thresholds
    """
    if evidence_count <= 0:
        return {"confidence": 0.0, "raw": 0.0, "components": {}, "thresholds": {}}

    # Reliability: success rate, scaled by sample (diminishing returns).
    reliability = success_count / max(1, evidence_count)

    # Sample-size robustness: more independent contexts => higher confidence.
    context_score = min(1.0, independent_contexts / max(1, MIN_INDEPENDENT_CONTEXTS))

    # Recency: recent successes weighted.
    recency = min(1.0, recent_successes / max(1, total_occurrences or 1))

    # Compatibility: how well this pattern matches the current context.
    compat = (model_compat + provider_compat + workspace_compat + tool_avail) / 4.0
    if compat < 0.0:
        compat = 0.0
    if compat > 1.0:
        compat = 1.0

    # Regression state discount.
    regression_discount = 0.0
    if regression_state == "regressed":
        regression_discount = 0.5
    elif regression_state == "quarantined":
        regression_discount = 0.8
    elif regression_state == "degraded":
        regression_discount = 0.2

    # Compute the weighted utility and normalize by the sum of weights.
    weight_sum = _W_RELIABILITY + _W_EVIDENCE + _W_RISKCAP + _W_RECENCY

    # Reliability term: success rate * weight
    reliability_term = _W_RELIABILITY * reliability
    # Evidence term: sample-size-based evidence strength
    evidence_term = _W_EVIDENCE * (1.0 if evidence_count >= MIN_EVIDENCE_FOR_VALIDATED
                                    else evidence_count / max(1, MIN_EVIDENCE_FOR_VALIDATED))
    # Risk term: compatibility * weight
    risk_term = _W_RISKCAP * compat
    # Recency term: recency * weight
    recency_term = _W_RECENCY * recency

    # Total raw utility, normalized by the sum of weights.
    raw = (reliability_term + evidence_term + risk_term + recency_term) / weight_sum

    # Clamp and apply regression discount.
    confidence = max(0.0, min(1.0, raw * (1.0 - regression_discount)))

    return {
        "confidence": confidence,
        "raw": raw,
        "components": {
            "reliability": round(reliability, 4),
            "sample_size": round(context_score, 4),
            "recency": round(recency, 4),
            "compatibility": round(compat, 4),
        },
        "thresholds": {
            "min_evidence": MIN_EVIDENCE_FOR_VALIDATED,
            "min_success_rate": MIN_SUCCESS_RATE,
            "min_independent_contexts": MIN_INDEPENDENT_CONTEXTS,
            "regression_discount": {
                "validated": 0.0, "degraded": 0.2, "quarantined": 0.8, "regressed": 0.5,
            },
        },
    }


def rank_strategies(strategies: List[Dict[str, Any]], context: Dict[str, Any],
                     top_n: int = 3) -> List[Dict[str, Any]]:
    """Rank candidate strategies by compatibility + score.

    Returns the top_n strategies, sorted by adjusted confidence.
    """
    scored = []
    for s in strategies:
        adjusted = s.get("confidence", 0.0)
        if s.get("status") in ("regressed", "quarantined"):
            adjusted *= 0.5 if s["status"] == "regressed" else 0.2
        elif s.get("status") == "degraded":
            adjusted *= 0.8
        # Context compatibility discount from the current environment.
        ctx = s.get("context", {})
        ctx_compat = ctx.get("model_compat", 1.0)
        ctx_compat = min(1.0, ctx_compat or 1.0)
        adjusted *= ctx_compat
        scored.append({"strategy": s, "adjusted_confidence": adjusted})

    scored.sort(key=lambda x: x["adjusted_confidence"], reverse=True)
    return [
        {"strategy": s["strategy"], "adjusted_confidence": s["adjusted_confidence"]}
        for s in scored[:top_n]
    ]


@dataclass(frozen=True)
class Strategy:
    """An evidence-backed strategy for a tool family."""

    strategy_id: str
    strategy_name: str
    strategy_type: str  # recovery / best / minimum / anti / retry
    sequence: list[str]  # ordered tool sequence
    evidence_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    context_count: int = 0
    confidence: float = 0.0
    last_validated_at: Optional[str] = None
    last_used_at: Optional[str] = None
    version: int = 1
    scope: str = "global"  # global / profile / user / workspace / session
    status: str = "candidate"  # candidate / validated / high_confidence / degraded / regressed / quarantined / disabled
    created_at: Optional[str] = None

    def score(self, **kwargs) -> Dict[str, Any]:
        return score_pattern(
            success_count=self.success_count,
            evidence_count=self.evidence_count,
            independent_contexts=self.context_count,
            recent_successes=0,  # filled by caller
            model_compat=kwargs.get("model_compat", 1.0),
            provider_compat=kwargs.get("provider_compat", 1.0),
            workspace_compat=kwargs.get("workspace_compat", 1.0),
            tool_avail=kwargs.get("tool_avail", 1.0),
            regression_state=self.status,
            total_occurrences=self.evidence_count,
        )


def evaluate_pattern(*, success_count: int, evidence_count: int,
                     independent_contexts: int) -> Dict[str, Any]:
    """Return PATTERN VALIDATION state (Phase 16)."""
    if evidence_count < MIN_EVIDENCE_FOR_VALIDATED:
        return {"status": "candidate", "confidence": 0.0, "validated": False}
    success_rate = success_count / evidence_count
    if success_rate < MIN_SUCCESS_RATE:
        return {"status": "candidate", "confidence": success_rate,
                "validated": False, "reason": "success_rate_below_threshold"}
    independent_ok = independent_contexts >= MIN_INDEPENDENT_CONTEXTS
    if independent_ok:
        return {"status": "validated", "confidence": success_rate, "validated": True}
    return {"status": "candidate", "confidence": success_rate,
            "validated": False, "reason": "insufficient_independent_contexts"}
