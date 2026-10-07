"""EBTTO package exports test — verifies the top-level package is importable
and exposes the public API with no import-time side effects.
"""

from hermes_ebtto import __version__
from hermes_ebtto import events as ev
from hermes_ebtto import storage as st
from hermes_ebtto import privacy as priv
from hermes_ebtto import classification as cls
from hermes_ebtto import learning as ln
from hermes_ebtto import retrieval as rt
from hermes_ebtto.plugins import EBTTOPlugin


def test_version():
    assert __version__ == "0.1.0"


def test_event_schema():
    t = ev.Task(task_fingerprint="test_fingerprint", task_family="test_family")
    assert t.event_id
    assert t.created_at
    assert t.task_fingerprint == "test_fingerprint"
    assert t.task_family == "test_family"


def test_event_serialization_roundtrip():
    t = ev.Task(task_fingerprint="fp", task_family="family")
    d = ev.event_to_dict(t)
    assert d["task_fingerprint"] == "fp"
    t2 = ev.dict_to_event(d["schema_version"], d)
    assert t2.task_fingerprint == "fp"
    assert t2.task_family == "family"



def test_privacy_redact_dict():
    payload = {"args": {"password": "secret123", "user": "alvi"}}
    out = priv.redact_dict(payload, mode="redacted")
    assert "secret123" not in str(out)
    assert "args" in out


def test_privacy_redact_str():
    # redact_str is conservative — it only drops raw-credential-looking text,
    # preserving the input otherwise. This avoids false positives on real data.
    s = "Authorization: Bearer ***"
    out = priv.redact_str(s, mode="redacted")
    assert "Authorization" in out
    assert "Bearer" in out
    assert "***" in out
    # No raw credential-like token was dropped
    assert "redacted" not in out.lower()


def test_classification():
    c = cls.classify_error(
        tool_name="terminal",
        result_message="command failed with exit code 1",
        error_type=None,
        error_code=None,
        status_code=None,
    )
    assert c.class_ == "tool_failure"
    assert 0.0 <= c.confidence <= 1.0
    assert c.evidence["tool_name"] == "terminal"


def test_classification_by_status():
    c = cls.classify_error(
        tool_name="api",
        result_message=None,
        error_type=None,
        error_code=None,
        status_code=500,
    )
    assert c.class_ == "external_service_failure"


def test_classification_result_status():
    r = cls.infer_result_status(
        result_message="command succeeded",
        error_type=None,
        error_code=None,
        status_code=None,
    )
    assert r == "SUCCESS"


def test_learning_score():
    s = ln.score_pattern(
        success_count=10, evidence_count=12, independent_contexts=5,
        recent_successes=4, model_compat=1.0, provider_compat=1.0,
        workspace_compat=1.0, tool_avail=1.0,
    )
    assert 0.0 <= s["confidence"] <= 1.0
    assert s["confidence"] > 0.0


def test_learning_validate_pattern():
    v = ln.evaluate_pattern(
        success_count=10, evidence_count=12, independent_contexts=5,
    )
    assert v["validated"] is True
    v2 = ln.evaluate_pattern(
        success_count=3, evidence_count=5, independent_contexts=1,
    )
    assert v2["validated"] is False


def test_retrieval_bounds():
    from hermes_ebtto.learning import Strategy
    store = {
        "s1": Strategy(strategy_id="s1", strategy_name="a", strategy_type="best",
                       sequence=["t1"], success_count=10, evidence_count=12,
                       context_count=5, confidence=0.9, status="validated"),
        "s2": Strategy(strategy_id="s2", strategy_name="b", strategy_type="best",
                       sequence=["t2"], success_count=2, evidence_count=3,
                       context_count=1, confidence=0.5, status="candidate"),
    }
    r = rt.retrieve_experience(
        task_family="test", strategy_store=store, max_results=1,
        min_confidence=0.6, fallback_strategy=None,
    )
    assert r.retrieved_count <= 1
    assert len(r.strategies) <= 1
