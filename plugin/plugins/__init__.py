
"""EBTTO — Experience-Based Tool Trajectory Optimizer for Hermes.

Adapts to the installed Hermes 0.21.5 hook contract.
Uses ONLY public plugin APIs:
  ctx.register_hook() — the supported hook registration path.
  hermes_ebtto.plugins.invoke_hook() — module-level hook invocation helper.
Does NOT modify Hermes core.
"""
from __future__ import annotations

import json
import logging
import re
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# hermes_ebtto config import (relative — works whether the package is
# installed as ``hermes_ebtto`` or loaded standalone by the Hermes
# capability probe, which names the module ``hermes_validate_probe_plugin``).
from .. import config as ebtto_config

# ``hermes_ebtto`` may not be an importable top-level package when Hermes loads
# this directory plugin as ``hermes_plugins.<slug>`` (the loader imports
# ``__init__.py`` by path). Alias the loaded package under its canonical name so
# the ``from hermes_ebtto... import`` statements below resolve to the same files
# instead of hitting an unrelated (or absent) installation.
def _alias_canonical_package() -> None:
    import sys as _sys
    if "hermes_ebtto" in _sys.modules:
        return
    pkg = __name__.rpartition(".")[0]
    if not pkg:
        return
    parent = _sys.modules.get(pkg)
    if parent is not None and getattr(parent, "__file__", None):
        _sys.modules["hermes_ebtto"] = parent


def _payload_reports_error(result: Any) -> bool:
    """True when a tool RESULT payload itself reports a failure.

    Hermes tool results are JSON strings of the shape
    ``{"error": "..."}`` / ``{"status": "error"}`` / ``{"error": {...}}``.
    This mirrors the same observable-derivation Hermes' own
    ``_tool_result_observer_fields`` performs, so a status-less delivery
    cannot be mistaken for success. Parsing never raises: an unparseable or
    empty payload is treated as "no reported error" and the decision falls
    back to the status field alone.
    """
    if isinstance(result, dict):
        payload = result
    elif isinstance(result, (bytes, bytearray)):
        try:
            payload = json.loads(result.decode("utf-8", "replace"))
        except Exception:
            return False
    elif isinstance(result, str):
        text = result.strip()
        if not text.startswith("{"):
            return False
        try:
            payload = json.loads(text)
        except Exception:
            return False
    else:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("error"):
        return True
    return str(payload.get("status") or "").lower() in ("error", "failed", "failure", "cancelled")


_alias_canonical_package()


# Provider credential prefixes that ``privacy.redact(mode="masked")`` does not
# cover. Tool error text routinely embeds them inside prose ("auth failed for
# token sk-live-..."), where a whole-string check cannot see them.
EMBEDDED_KEY_PREFIX_RE = re.compile(
    r"\b(?:sk|pk|rk)[-\w]{16,}\b|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}\b|\bAKIA[0-9A-Z]{16}\b|\bAI[A-Za-z0-9]{30,}\b|\blin_api_[A-Za-z0-9]{20,}\b",
    re.I,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

# Default EBTTO storage path for the plugin
DEFAULT_STORAGE_PATH = Path(
    os.environ.get("EBTTO_DATA_DIR", str(Path.home() / ".hermes-ebtto"))
)


def _get_hermes_types():
    """Lazy import of Hermes plugin types — hermes_cli.plugins may not be installed."""
    from hermes_cli.plugins import PluginContext, PluginManifest, PluginRegistration
    return PluginContext, PluginManifest, PluginRegistration


class EBTTOStore:
    """Thin wrapper around hermes_ebtto.storage.Store for the EBTTO plugin."""

    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path is None:
            storage_path = Path(DEFAULT_STORAGE_PATH)
        from hermes_ebtto.storage import Store
        self.store = Store(storage_path)
        self.db_path = storage_path / "ebtto.db"

    def record_task(self, task):
        return self.store.record_task(task)

    def record_tool_call(self, tool_call):
        return self.store.record_tool_call(tool_call)

    def record_outcome(self, outcome):
        return self.store.record_outcome(outcome)

    def record_error(self, error):
        return self.store.record_error(error)

    def record_pattern(self, pattern):
        return self.store.record_pattern(pattern)

    def record_strategy(self, strategy):
        return self.store.record_strategy(strategy)

    def get_patterns_by_tool(self, tool_name, limit=3):
        return self.store.get_patterns_by_tool(tool_name, limit=limit)

    def get_trajectories(self, **filters):
        return self.store.get_trajectories(**filters)

    def get_task(self, task_id):
        return self.store.get_task(task_id)

    def release(self):
        self.store.close()

def register(ctx):
    """Module-level register(ctx) - the Hermes plugin entry point.
    
    Creates the EBTTOPlugin and registers all hooks via the public
    ctx.register_hook() API. This satisfies the Hermes plugin manifest
    contract: modules with main: hermes_ebtto.plugins MUST provide
    a register(ctx) function.

    ``mode`` is read from the plugin's own settings
    (``plugins.entries.<id>.settings.mode`` via ``ctx.get_config``) so an
    operator can move the plugin out of RECORD_ONLY without a code change;
    it stays RECORD_ONLY when unset, so a fresh install never injects
    guidance. ``ctx.get_config`` is fail-safe: an older/absent ctx yields
    the default rather than an exception.
    """
    # ``mode`` resolution order (first hit wins):
    #   1. EBTTO_MODE env var — profile-independent escape hatch, so an
    #      operator can force a mode without editing a profile-scoped config
    #      that the routed profile may not inherit.
    #   2. ctx.get_config("mode") — plugins.entries.<id>.settings.mode.
    #   3. config.DEFAULT_MODE — safe default: a fresh install never injects.
    #      Resolved from the canonical constant so the declared default and the
    #      effective fallback cannot drift apart.
    import os as _os
    _default_mode = getattr(ebtto_config, "DEFAULT_MODE", "record_only")
    mode = _os.environ.get("EBTTO_MODE", "").strip()
    if not mode:
        try:
            mode = ctx.get_config("mode", _default_mode)
        except Exception:
            mode = _default_mode
    plugin = EBTTOPlugin(manifest=None, ctx=ctx, config={
        "mode": mode,
        "enabled": True,
    })
    plugin.register()
    return plugin


class EBTTOPlugin:
    """Hermes plugin that records tool trajectories and injects guidance.

    Modes:
      OFF       - No recording/guidance
      RECORD_ONLY - Record only, no injection
      SHADOW    - Record + show guidance in logs (no action)
      ADVISORY  - Record + inject guidance as suggestions
      GUARDED   - Record + guided calls that must be accepted
      CONTROLLED_AUTO - Automatic execution of learned strategies

    All modes use ctx.register_hook() — the public, supported API.
    """

    MODE_OFF = "off"
    MODE_RECORD_ONLY = "record_only"
    MODE_SHADOW = "shadow"
    MODE_ADVISORY = "advisory"
    MODE_GUARDED = "guarded"
    MODE_CONTROLLED_AUTO = "controlled_auto"

    def __init__(self, manifest: Any, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self.manifest = manifest
        self.ctx = ctx
        self.mode = self.MODE_RECORD_ONLY
        self.store = None
        self._hook_handles = []
        self._started = False

        if config is None:
            config = {}
        self.mode = config.get("mode", self.MODE_RECORD_ONLY)
        self.enabled = config.get("enabled", True)

        # Metrics
        self.metrics = {
            "tool_calls": 0,
            "successes": 0,
            "failures": 0,
            "first_tool_successes": 0,
            "retries": 0,
            "regressions": 0,
            "guidance_injected": 0,
            "guidance_accepted": 0,
            "guidance_blocked": 0,
        }

    # -- Lifecycle ----------------------------------------------------------

    def register(self):
        """Register all hooks and CLI commands. Public API only."""
        if self._started:
            return

        # Import Hermes types lazily
        PluginContext, PluginManifest, PluginRegistration = _get_hermes_types()

        log.info(
            "EBTTO plugin registering for mode=%s (enabled=%s)",
            self.mode, self.enabled,
        )

        # Register the lifecycle hooks via the public ctx.register_hook() API
        if self.enabled:
            self.prepare_storage()
            self._register_hooks()
            self.record_metrics()
            self._start_recording()

        # Register CLI commands
        self._register_cli_commands()

        # Register retrieval admin
        self._register_admin_commands()

        self._started = True
        log.info("EBTTO plugin registered (mode=%s, hooks=%d)",
                 self.mode, len(self._hook_handles))

    # -- Hook registration -------------------------------------------------

    def _register_hooks(self):
        """Register hook callbacks via the public ctx.register_hook() API."""
        # Register pre_llm_call: inject retrieved experience into the user message
        # BEFORE the provider/tool-calling loop is built, so the model's next
        # tool-selection decision can actually see prior experience. This is the
        # hook that carries the Run-1 -> Run-2 behavioral loop; pre_tool_call
        # fires only AFTER the model has already chosen the tool and is therefore
        # too late to influence that choice.
        if self.mode != self.MODE_OFF:
            self._hook_handles.append(self.ctx.register_hook("pre_llm_call", self._hook_pre_llm_call))

        # Register pre_tool_call: intercept before the tool executes
        if self.mode != self.MODE_OFF:
            self._hook_handles.append(self.ctx.register_hook("pre_tool_call", self._hook_pre_tool_call))

        # Register post_tool_call: record actual result
        self._hook_handles.append(self.ctx.register_hook("post_tool_call", self._hook_post_tool_call))

        # Register on_session_end: flush per-task state
        self._hook_handles.append(self.ctx.register_hook("on_session_end", self._hook_on_session_end))

    def _hook_pre_llm_call(self, **kwargs):
        """Wrapper for the pre_llm_call hook."""
        return self._on_pre_llm_call(kwargs)

    def _on_pre_llm_call(self, kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Called once per turn BEFORE the provider/tool-calling loop is built.

        Returns ``{"context": "<text>"}`` — the contract Hermes's
        ``agent/turn_context.py::_collect_pre_llm_call_context`` accepts. The text is
        appended to the user message (never the system prompt), so the model's next
        tool-selection decision can see prior experience. This is what makes the
        Run-1 -> Run-2 behavioral loop possible; returning nothing here means EBTTO
        can never influence tool choice.

        Fails open: any error returns None so Hermes continues normally.
        """
        if not self.enabled or self.mode == self.MODE_OFF:
            return None
        if self.mode == self.MODE_RECORD_ONLY:
            # record_only is the safe default: observe without influencing.
            return None

        try:
            task_id = kwargs.get("task_id") or kwargs.get("session_id") or ""
            # Hermes passes the user's message; derive the task family from it so
            # guidance is scoped to the current task rather than replayed blindly.
            user_message = kwargs.get("user_message") or ""
            if not isinstance(user_message, str):
                user_message = str(user_message)
            task_family = self._derive_task_family(user_message)

            guidance = self._retrieve_guidance_for_task(task_family, {"user_message": user_message}, task_id)
            if not guidance:
                return None

            hint = (guidance.get("directive") or {}).get("hint")
            if not hint:
                return None

            self.metrics["guidance_injected"] += 1
            log.info("[EBTTO pre_llm_call] injecting guidance for task=%s: %s",
                     task_id, guidance.get("strategy_name", "unknown"))

            # Bounded, evidence-backed, task-scoped text. Treated as DATA by the
            # model, never as an instruction to re-run a historical trajectory.
            context = (
                "EBTTO prior experience (advisory, do not assume it still applies): "
                f"{hint} "
                "Use it only if it is consistent with the current request and the "
                "current environment; ignore it if it does not fit."
            )
            return {"context": context}

        except Exception as e:
            log.warning("EBTTO pre_llm_call error: %s", e)
            return None

    def _hook_pre_tool_call(self, **kwargs):
        """Wrapper for the pre_tool_call hook."""
        return self._on_pre_tool_call(kwargs)

    def _hook_post_tool_call(self, **kwargs):
        """Wrapper for the post_tool_call hook."""
        return self._on_post_tool_call(kwargs)

    def _hook_on_session_end(self, **kwargs):
        """Wrapper for the on_session_end hook."""
        return self._on_session_end(kwargs)

    def _on_pre_tool_call(self, kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Called before a tool executes. Returns None (continue) or a directive dict."""
        if not self.enabled or self.mode == self.MODE_OFF:
            return None

        try:
            from hermes_ebtto import events as ev
            from hermes_ebtto import classification as cl

            task_id = kwargs.get("task_id") or kwargs.get("session_id") or f"turn-{int(time.time() * 1000)}"
            tool_name = kwargs.get("tool_name") or kwargs.get("tool_input", {}).get("name", "unknown")
            args = kwargs.get("args") or kwargs.get("tool_input", {})

            # Track metrics
            self.metrics["tool_calls"] += 1

            if self.store is not None:
                # Record the tool call
                t = ev.Task(
                    task_fingerprint=f"{tool_name}_pre_{kwargs.get('attempt', 1)}",
                    task_family=tool_name,
                    workspace_identifier=kwargs.get("session_id", "unknown"),
                    model=kwargs.get("model", "unknown"),
                    provider=kwargs.get("provider", "unknown"),
                    sanitized_intent=str(args),
                )
                task_id_db = self.store.record_task(t)

                tool_call = ev.ToolCall(
                    task_id=task_id_db,
                    turn_id=kwargs.get("turn_id", "turn-1"),
                    tool_call_id=kwargs.get("tool_call_id", "call-pre"),
                    tool_name=tool_name,
                    order_number=kwargs.get("order_number", 1),
                    attempt_number=kwargs.get("attempt", 1),
                    raw_args=args,
                    sanitized_args=args,
                    result_status="PENDING",
                    duration_ms=0,
                )
                self.store.record_tool_call(tool_call)

            # In shadow/advisory/guarded modes, we may inject guidance
            if self.mode in (self.MODE_SHADOW, self.MODE_ADVISORY, self.MODE_GUARDED, self.MODE_CONTROLLED_AUTO):
                guidance = self._retrieve_guidance_for_task(
                    kwargs.get("tool_name"),
                    kwargs.get("args", {}),
                    kwargs.get("task_id", ""),
                )
                if guidance:
                    self.metrics["guidance_injected"] += 1
                    if self.mode == self.MODE_SHADOW:
                        log.info("[EBTTO SHADOW] Guidance: %s", guidance.get("strategy_name", "unknown"))
                    elif self.mode == self.MODE_ADVISORY:
                        return guidance.get("directive", {"action": "continue", "guidance": guidance})
                    elif self.mode == self.MODE_GUARDED:
                        log.warning("[EBTTO GUARDED] Requires user approval before executing: %s",
                                    guidance.get("strategy_name", "unknown"))
                        return {"action": "continue", "requires_approval": True,
                                "guidance": guidance}
                    elif self.mode == self.MODE_CONTROLLED_AUTO:
                        return self._apply_strategy_to_args(tool_name, kwargs.get("args", {}), guidance)

            return None

        except Exception as e:
            log.warning("EBTTO pre_tool_call error: %s", e)
            return None

    def _on_post_tool_call(self, kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Called after a tool executes. Records outcome, and on failure a
        classified error row through the canonical ``Store.record_error`` path.

        Hermes' post_tool_call contract is authoritative here: ``status`` is
        ``ok`` / ``error`` / ``blocked`` / ``cancelled`` (derived by
        ``model_tools._tool_result_observer_fields``), with ``error_type`` and
        ``error_message`` carried alongside the raw ``result``. We treat
        anything other than ``ok`` as a failure so a non-empty result cannot be
        mistaken for success, and never depend on string-sniffing the result.

        Fail-open by design: every persistence step is individually guarded, so
        a DB/EBTTO fault is logged and the ordinary Hermes tool loop continues.
        """
        try:
            from hermes_ebtto import events as ev

            result = kwargs.get("result", "")
            result_str = str(result)
            tool_name = kwargs.get("tool_name") or "unknown"
            status = str(kwargs.get("status") or "ok").strip()
            error_type = kwargs.get("error_type")
            error_message = kwargs.get("error_message")
            task_id = kwargs.get("task_id") or kwargs.get("session_id") or ""
            tool_call_id = kwargs.get("tool_call_id") or ""
            turn_id = kwargs.get("turn_id") or "turn-1"

            # The wire contract marks success explicitly as "ok"; every other
            # status (error/blocked/cancelled) is a failure. Hermes also reports
            # structured errors inside a JSON result, so a status-less delivery
            # still gets checked via the payload before being called success.
            success = self._is_success(status=status, result=result, tool_name=tool_name)

            if self.store is not None and self._started and task_id and tool_call_id:
                outcome = ev.Outcome(
                    task_id=task_id,
                    turn_id=turn_id,
                    result="SUCCESS" if success else "FAILURE",
                    confidence=0.90,
                    evidence={"tool": tool_name, "status": status,
                              "result": self._safe_text(result_str)[:500]},
                )
                self.store.record_outcome(outcome)

                if not success:
                    self._record_failure(
                        task_id=task_id, turn_id=turn_id,
                        tool_call_id=tool_call_id, tool_name=tool_name,
                        status=status, error_type=error_type,
                        error_message=error_message, result=result,
                    )

            self.metrics["tool_calls"] += 1
            if success:
                self.metrics["successes"] += 1
            else:
                self.metrics["failures"] += 1

            # GAP-2: after persisting the outcome, evaluate whether the
            # accumulated evidence for this tool qualifies as a pattern.
            if self.store is not None and self._started and task_id and tool_call_id:
                try:
                    self._learn_pattern(task_id=task_id, tool_name=tool_name,
                                        success=success)
                except Exception as exc:
                    log.warning("EBTTO pattern learning failed for %s: %s",
                                tool_name, exc)

            return None

        except Exception as e:
            log.warning("EBTTO post_tool_call error: %s", e)
            return None

    # -- failure classification + persistence (GAP 1) ----------------------

    @staticmethod
    def _is_success(*, status: str, result: Any, tool_name: str) -> bool:
        """Decide success from Hermes' documented hook contract.

        Order matters: an explicit ``ok`` wins; a structured ``{"error": ...}``
        payload fails even when the status field was omitted; otherwise the
        status string is matched against the known failure vocabulary.
        """
        if status:
            if status == "ok":
                return not _payload_reports_error(result)
            if status in ("error", "blocked", "cancelled", "failed", "failure"):
                return False
        return not _payload_reports_error(result)

    @staticmethod
    def _safe_text(text: Any, limit: int = 4000) -> str:
        """Privacy-sanitize any text before it reaches storage or a log line.

        Three layers, all fail-open:
          1. ``redact_str`` — whole-string credential case.
          2. ``redact(mode="masked")`` — known embedded fragments
             (bearer, JWT, AWS keys, connection strings).
          3. ``EMBEDDED_KEY_PREFIX_RE`` — provider key prefixes embedded in
             prose, e.g. ``"auth failed for token sk-live-..."``. Neither layer
             1 nor 2 catches these: ``redact_str`` only judges the ENTIRE
             string, and the masked regex set has no ``sk-``/``gh-`` entry.
             Tool error messages are exactly this case.
        """
        raw = str(text)[:limit]
        try:
            from hermes_ebtto import privacy as pr
            out = pr.redact_str(raw)
            if out == raw:
                out = pr.redact(raw, mode="masked")
            if out == raw:
                out = EMBEDDED_KEY_PREFIX_RE.sub("[REDACTED]", out)
            return out
        except Exception:
            # Redaction must never be the reason a failure is lost.
            return raw

    @staticmethod
    def _safe_evidence(obj: Any) -> Any:
        """Recursively redact a structured payload for storage."""
        try:
            from hermes_ebtto import privacy as pr
            return pr.sanitize_payload(obj)
        except Exception:
            return {"note": "payload dropped: sanitization unavailable"}

    def _record_failure(self, *, task_id: str, turn_id: str, tool_call_id: str,
                        tool_name: str, status: str, error_type: Optional[str],
                        error_message: Optional[str], result: Any) -> None:
        """Classify a genuine failure and persist it as a canonical Error event.

        The classifier receives only observable hook fields — never guessed
        values. Correlation uses the SAME ``task_id``/``tool_call_id`` that the
        outcome record was written with, so the three rows join exactly. One
        delivery yields at most one error row: a repeated delivery of the same
        tool_call_id is ignored via the UNIQUE constraint on ``error_id`` plus
        the caller's single-fire contract.
        """
        safe_message = self._safe_text(error_message if error_message else str(result))
        safe_result = self._safe_text(str(result))
        evidence = {
            "tool": tool_name,
            "status": status,
            "hook_error_type": error_type,
            "result_preview": safe_result[:500],
        }

        try:
            from hermes_ebtto.classification import classify_error

            classification = classify_error(
                tool_name=tool_name,
                result_message=safe_result,
                error_type=error_type,
                error_code=None,
                status_code=None,
                evidence=self._safe_evidence(evidence),
            )
            error_class = classification.class_
            confidence = classification.confidence
        except Exception as exc:
            # Classification is diagnostic; never lose the failure itself.
            log.warning("EBTTO classify_error failed for %s: %s", tool_name, exc)
            error_class = "unknown"
            confidence = 0.0

        log.info("[EBTTO] Failure on %s classified as %s (confidence=%.2f)",
                 tool_name, error_class, confidence)

        try:
            from hermes_ebtto import events as ev

            error = ev.Error(
                task_id=task_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                error_class=error_class,
                confidence=confidence,
                error_message=safe_message,
                evidence=self._safe_evidence({**evidence, "error_class": error_class}),
            )
            self.store.record_error(error)
        except Exception as exc:
            log.warning("EBTTO record_error failed (fail-open) for %s: %s", tool_name, exc)

    def _on_session_end(self, kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if self.store is not None and self._started:
                log.info("[EBTTO] Session metrics: %s", self.metrics)
                self.metrics = {
                    "tool_calls": 0, "successes": 0, "failures": 0,
                    "first_tool_successes": 0, "retries": 0,
                    "regressions": 0, "guidance_injected": 0,
                    "guidance_accepted": 0, "guidance_blocked": 0,
                }
            return None
        except Exception as e:
            log.warning("EBTTO session_end error: %s", e)
            return None

    # -- GAP-2: pattern learning (Phase 22) ---------------------------------

    def _learn_pattern(self, *, task_id: str, tool_name: str, success: bool) -> None:
        """Aggregate evidence for ``tool_name`` and persist a qualified pattern.

        The chain is: persisted outcome → evidence aggregation →
        ``evaluate_pattern()`` qualification → ``record_pattern()``.

        Qualification thresholds (from ``learning.py``):

        * ``MIN_EVIDENCE_FOR_VALIDATED`` = 5 — at least 5 independent outcomes
        * ``MIN_SUCCESS_RATE`` = 0.8 — at least 80% of outcomes must succeed
        * ``MIN_INDEPENDENT_CONTEXTS`` = 3 — at least 3 distinct contexts

        A pattern is NOT created on every call. It is only persisted when the
        accumulated evidence for this tool clears all three thresholds. The
        ``patterns`` table is the read path for ``get_patterns_by_tool()``.
        """
        try:
            from hermes_ebtto import learning as L

            # Resolve the inner Store (EBTTOStore wraps Store).
            inner = getattr(self.store, "store", self.store)

            # Aggregate evidence from the outcomes table for this tool.
            # NOTE: ``outcomes`` stores ``tool_name`` inside the ``evidence``
            # JSON blob (key ``tool``), not as a column. Use ``json_extract``
            # to filter by it.
            rows = inner._execute(
                """SELECT result, COUNT(*) AS n
                   FROM outcomes
                  WHERE json_extract(evidence, '$.tool') = :tool_name
                  GROUP BY result""",
                {"tool_name": tool_name},
                commit=False,
            ).fetchall()

            success_count = 0
            failure_count = 0
            for result, count in rows:
                if result == "SUCCESS":
                    success_count = count
                elif result == "FAILURE":
                    failure_count = count

            evidence_count = success_count + failure_count
            if evidence_count == 0:
                return

            # Count distinct task_ids as independent contexts.
            ctx_count = inner._execute(
                """SELECT COUNT(DISTINCT task_id) FROM outcomes
                  WHERE json_extract(evidence, '$.tool') = :tool_name""",
                {"tool_name": tool_name},
                commit=False,
            ).fetchone()[0]

            # Qualify via the existing learning module.
            verdict = L.evaluate_pattern(
                success_count=success_count,
                evidence_count=evidence_count,
                independent_contexts=ctx_count,
            )

            if not verdict.get("validated"):
                return  # not enough evidence — no pattern row

            # Logical key = the tool alone: evidence is aggregated per tool, so
            # the SAME (tool) must always map to the SAME pattern/strategy id.
            # Deriving the id from task_id (as an earlier revision did) produced
            # a fresh row per task and defeated the INSERT OR IGNORE dedup —
            # one tool could accumulate many duplicate "patterns".
            pattern_id = f"pat-{tool_name}"
            pattern = {
                "pattern_id": pattern_id,
                "pattern_name": f"{tool_name} best practice",
                "pattern_type": "tool_best_practice",
                "evidence_count": evidence_count,
                "success_count": success_count,
                "failure_count": failure_count,
                "confidence": verdict.get("confidence", 0.0),
                "status": "validated",
            }
            self.store.record_pattern(pattern)

            # Also persist a strategy row so get_patterns_by_tool() can retrieve it.
            strategy_id = f"strat-{tool_name}"
            strategy = {
                "strategy_id": strategy_id,
                "strategy_name": f"{tool_name} best practice",
                "strategy_type": "tool_best_practice",
                "sequence": [{"tool": tool_name, "order": 1}],
                "evidence_count": evidence_count,
                "success_count": success_count,
                "failure_count": failure_count,
                "context_count": ctx_count,
                "confidence": verdict.get("confidence", 0.0),
                "scope": "tool",
                "status": "validated",
                "task_family": tool_name,
            }
            self.store.record_strategy(strategy)

            log.info(
                "[EBTTO] Pattern persisted for %s: %s (evidence=%d, success_rate=%.2f)",
                tool_name, pattern_id, evidence_count,
                success_count / evidence_count,
            )
        except Exception as exc:
            log.warning("EBTTO pattern learning failed for %s: %s", tool_name, exc)

    def _retrieve_guidance_for_task(self, tool_name: str, args: Dict[str, Any],
                                    task_id: str) -> Optional[Dict[str, Any]]:
        if self.store is None or not self.enabled:
            return None

        try:
            from hermes_ebtto import retrieval as rt
            from hermes_ebtto import scoring as sc

            from hermes_ebtto.normalization import task_fingerprint

            # task_family is the retrieval key: at the pre-LLM hook it is derived from
            # the user's message; at the pre-tool hook it is the tool name.
            family = tool_name or "general"
            task_fingerprint(family, args=args, session_id=task_id)

            patterns = self.store.get_patterns_by_tool(family, limit=3)
            if not patterns:
                return None

            best = patterns[0]
            return {
                "strategy_id": best.get("strategy_id", "unknown"),
                "strategy_name": best.get("strategy_name", "unknown"),
                "success_rate": best.get("success_rate", best.get("confidence", 0.0)),
                "evidence_count": best.get("evidence_count", 0),
                "confidence": best.get("confidence", 0.0),
                "status": best.get("status", "unknown"),
                "directive": {
                    "action": "continue",
                    "hint": f"Previous similar calls to {family} succeeded with "
                            f"'{best.get('strategy_name', 'the first strategy')}' "
                            f"(success rate {best.get('success_rate', 0.0):.0%} over "
                            f"{best.get('evidence_count', 0)} examples). "
                            f"Review evidence: {best.get('evidence_count', 0)} examples.",
                },
            }

        except Exception as e:
            log.warning("EBTTO retrieval error: %s", e)
            return None

    def _derive_task_family(self, user_message: str) -> str:
        """Derive the retrieval key from the user's message.

        The returned value MUST be a ``task_family`` that learning actually
        stores. ``_learn_pattern`` persists strategies with
        ``task_family = <tool_name>``, so the vocabulary here is tool names
        (``terminal``, ``execute_code``, ``read_file``, ``patch``, ...). A
        message-level label like "shell" or "file_read" never matches a stored
        row and silently starves retrieval — the exact bug that kept the
        Run-1 -> Run-2 guidance loop dead. Falls back to ``general`` so an
        unrecognised request never retrieves unrelated experience.
        """
        text = (user_message or "").lower()
        if not text.strip():
            return "general"

        # An explicit tool mention is the strongest possible signal and must win
        # over generic keyword matches. "Use the terminal tool to run python -c ..."
        # names `terminal` and only incidentally mentions `python`; without this
        # tier the `execute_code` keyword list (which contains "python") captures it
        # and retrieval pulls experience for the wrong tool entirely.
        tool_names = ("browser_exec", "execute_code", "write_file", "read_file",
                      "search_files", "terminal", "patch")
        for name in tool_names:
            if name in text:
                return name
        for name, phrases in (("terminal", ("terminal tool",)),
                              ("patch", ("patch tool",)),
                              ("read_file", ("read file tool",))):
            if any(p in text for p in phrases):
                return name

        # No explicit tool name: fall back to keyword matching. Longer/more
        # distinctive families are tested first so "write file" lands on
        # write_file rather than the broader patch bucket.
        keywords = {
            "terminal": ("run", "execute", "command", "terminal", "shell", "install",
                         "npm", "pip", "git ", "bash", "cmd"),
            "execute_code": ("python", "script", "code", "execute_code", "snippet"),
            "read_file": ("read", "open", "show me", "inspect", "cat ", "view",
                          "look at"),
            "patch": ("patch", "edit", "overwrite", "write file", "update file",
                      "modify", "create file", "save", "fix"),
            "write_file": ("write file", "create file", "new file", "save to"),
            "search_files": ("search", "find", "grep", "look for", "locate"),
            "browser_exec": ("browse", "website", "web page", "browser", "open url"),
        }
        for family in sorted(keywords, key=len, reverse=True):
            if any(w in text for w in keywords[family]):
                return family
        return "general"

    def _apply_strategy_to_args(self, tool_name: str, args: Dict[str, Any],
                                guidance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        log.info("[EBTTO CONTROLLED_AUTO] Proposed strategy for %s: %s",
                 tool_name, guidance.get("strategy_name"))
        return {"EBTTO_GUIDED": True, **args}

    def _register_cli_commands(self):
        try:
            import hermes_ebtto.cli as ebtto_cli

            register_ebtto_commands = getattr(ebtto_cli, "register_ebtto_commands", None)
            if register_ebtto_commands is None:
                log.debug("EBTTO CLI commands: no register_ebtto_commands in ebtto.cli; skipping")
                return
            register_ebtto_commands(self.ctx)
            log.info("EBTTO CLI commands registered")
        except Exception as e:
            log.warning("EBTTO CLI registration failed: %s", e)

    def _register_admin_commands(self):
        pass

    def prepare_storage(self, storage_path: Optional[Path] = None):
        if self.store is None:
            self.store = EBTTOStore(storage_path)
            log.info("EBTTO store initialized at %s", self.store.db_path)

    def close(self):
        if self.store is not None:
            self.store.release()
            self.store = None

    def record_metrics(self):
        """Persist the current in-memory metric counters (best effort)."""
        if self.store is None:
            return
        try:
            if hasattr(self.store, "record_metrics"):
                self.store.record_metrics(dict(self.metrics))
        except Exception as e:
            log.warning("EBTTO metrics recording error: %s", e)

    def _start_recording(self):
        """Announce that recording is live (observability only, best effort)."""
        try:
            from hermes_ebtto.observability import Publisher

            pub = Publisher()
            pub.publish("session_started", {"mode": self.mode, "enabled": self.enabled})
        except Exception as e:
            log.warning("EBTTO recording start error: %s", e)
