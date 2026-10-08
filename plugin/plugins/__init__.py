
"""EBTTO — Experience-Based Tool Trajectory Optimizer for Hermes.

Adapts to the installed Hermes 0.21.5 hook contract.
Uses ONLY public plugin APIs:
  ctx.register_hook() — the supported hook registration path.
  hermes_ebtto.plugins.invoke_hook() — module-level hook invocation helper.
Does NOT modify Hermes core.
"""
from __future__ import annotations

import logging
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


_alias_canonical_package()

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
    """
    plugin = EBTTOPlugin(manifest=None, ctx=ctx, config={
        "mode": "record_only",
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
        # Register pre_tool_call: intercept before the tool executes
        if self.mode != self.MODE_OFF:
            self._hook_handles.append(self.ctx.register_hook("pre_tool_call", self._hook_pre_tool_call))

        # Register post_tool_call: record actual result
        self._hook_handles.append(self.ctx.register_hook("post_tool_call", self._hook_post_tool_call))

        # Register on_session_end: flush per-task state
        self._hook_handles.append(self.ctx.register_hook("on_session_end", self._hook_on_session_end))

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
        """Called after a tool executes. Records the actual result."""
        try:
            from hermes_ebtto import events as ev

            result = kwargs.get("result", "")
            if isinstance(result, (dict, list)):
                result_str = str(result)
            else:
                result_str = str(result)

            tool_name = kwargs.get("tool_name", "unknown")
            status = kwargs.get("status", "SUCCESS")
            success = status in ("SUCCESS", "success", "0", "exit 0", "OK", "ok")

            if self.store is not None and self._started:
                task_id = kwargs.get("task_id") or kwargs.get("session_id", "")
                tool_call_id = kwargs.get("tool_call_id", "")

                if task_id and tool_call_id:
                    outcome = ev.Outcome(
                        task_id=task_id,
                        turn_id=kwargs.get("turn_id", "turn-1"),
                        result="SUCCESS" if success else "FAILURE",
                        confidence=0.90,
                        evidence={"result": result_str[:500], "tool": tool_name, "status": status},
                        recorded_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self.store.record_outcome(outcome)

                    from hermes_ebtto.classification import classify_error
                    if not success:
                        error_class = classify_error(tool_name=tool_name, result_message=result_str)
                        log.info("[EBTTO] Classified as: %s (confidence=%.2f)",
                                 error_class, 0.70)

            self.metrics["tool_calls"] += 1
            if success:
                self.metrics["successes"] += 1
            else:
                self.metrics["failures"] += 1

            return None

        except Exception as e:
            log.warning("EBTTO post_tool_call error: %s", e)
            return None

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

    def _retrieve_guidance_for_task(self, tool_name: str, args: Dict[str, Any],
                                    task_id: str) -> Optional[Dict[str, Any]]:
        if self.store is None or not self.enabled:
            return None

        try:
            from hermes_ebtto import retrieval as rt
            from hermes_ebtto import scoring as sc

            from hermes_ebtto.normalization import task_fingerprint
            fp = task_fingerprint(tool_name=tool_name, args=args, session_id=task_id)

            patterns = self.store.get_patterns_by_tool(tool_name, limit=3)
            if not patterns:
                return None

            return {
                "strategy_id": patterns[0].get("strategy_id", "unknown"),
                "strategy_name": patterns[0].get("strategy_name", "unknown"),
                "success_rate": patterns[0].get("confidence", 0.0),
                "evidence_count": patterns[0].get("evidence_count", 0),
                "directive": {
                    "action": "continue",
                    "hint": f"Previous similar calls to {tool_name} succeeded with "
                            f"{patterns[0].get('strategy_name', 'the first strategy')}. "
                            f"Review evidence: {patterns[0].get('evidence_count', 0)} examples.",
                },
            }

        except Exception as e:
            log.warning("EBTTO retrieval error: %s", e)
            return None

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
