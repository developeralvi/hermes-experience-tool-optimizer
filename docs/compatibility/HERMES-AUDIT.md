# EBTTO — Hermes Core Audit

**Date:** 2026-10-08
**Auditor:** EBTTO build
**Verdict:** EBTTO adapts to the installed API; Hermes is never modified.

---

## 1. Installed Hermes

| Item | Value |
|---|---|
| Hermes version | 0.21.5 (`hermes-agent` package metadata) |
| Git HEAD | `2943ee6f19` ("fix(ts): npm run fix") |
| Python | 3.14.7 (Hermes-managed venv) |
| Hermes home | `$HERMES_HOME` / `~/.hermes` |
| Plugin root | `$HERMES_HOME/plugins/` (or bundled `plugins/`) |
| Plugin manifest schema | `plugin.yaml` v2 (`plugins_manifest.PluginManifest`, `SUPPORTED_MANIFEST_VERSION = 2`) |
| CLI extension | `register_cli_command` via `PluginContext` |

## 2. Verified hook contract (the source of truth)

All lifecycle hooks fire via `hermes_cli.lifecycle.invoke_hook(hook_name, **kwargs)`:

- built-in first-party observers (`hermes_cli.observability.observe_lifecycle`), then
- registered plugin callbacks via `PluginManager._hooks[hook_name]`.

**Plugin-registered hooks** (`ctx.register_hook("<name>", callback)`), verified in this install:

- `pre_tool_call` — payload: `tool_name, args, task_id, session_id, tool_call_id, turn_id, api_request_id, middleware_trace`. Returns `{"action": "block", "message"}`, `{"action": "modify", "args": {...}}`, or `{"action": "approve", ...}`; or any non-None result is appended to results. Never raises into the loop (isolated per callback). Bounded by `hook_callback_timeout` (30s); `pre_tool_call` is a fail-closed policy hook.
- `post_tool_call` — payload: `tool_name, args, result, duration_ms, ...`. Observer; returns ignored / non-None results appended.
- `transform_tool_result` — payload: `tool_name, args, result, duration_ms, ...`. May return a replacement result string.
- `pre_llm_call` — payload: injected via `_collect_pre_llm_call_context`; may return `{"context": "..."}` or a str to inject into the user message.
- `post_llm_call` — fired once per turn in `turn_finalizer`.
- `on_session_start` — payload: `session_id, model, platform, ...`.
- `on_session_end` — payload: `session_id, completed, interrupted, ...`.
- `on_session_finalize` — session finalization; `hermes_cli.lifecycle.finalize_session`.
- `pre_verify` — payload: `session_id, platform, model, coding, attempt, final_response, changed_paths`. Returns `{"action": "continue", "message"}` or `{"decision": "block", "reason"}` to keep the turn going; anything else finishes the turn.

`transform_api_error_classification` is **Python-plugin-only**: shell hooks have no channel for it (`SHELL_UNSUPPORTED_HOOKS`) and are refused loudly. EBTTO uses this for error classification.

### What is NOT in this install

- `pre_api_request` / `post_api_request` / `api_request_error` exist as VALID_HOOKS but their fire sites were not found in the core agent loop in this install (they are auxiliary-provider hooks). EBTTO records its own execution counts instead of relying on them.

## 3. Python plugin lifecycle

- `register(ctx)` in `__init__.py`; `ctx.register_hook(name, callback)`, `ctx.register_command(...)`, `ctx.get_config(key, default)`, `ctx.set_config(key, value)`.
- Manifest fields: `name, version, description, author, provides_hooks, kind, api_version, config_schema, ...`.
- Hook callbacks are isolated (errors logged, never raise into the loop); results are run-all-then-pick-first where the contract says so.
- `pre_tool_call` is fail-closed-policy; all other hooks fail open.

## 4. What EBTTO adapts to / does not do

- Does NOT patch `model_tools.py`, core agent loop, provider, tool registry, or built-in tools.
- Does NOT use shell hooks (`hooks:` config) because Python plugin hooks are richer and are the native contract; shell hook integration is documented as a future adapter.
- Uses Python plugin `register(ctx)` only; never core monkey-patching.
- DB: SQLite (WAL, busy_timeout, transactions, FK on).
- Storage path: `$HERMES_HOME/.hermes-ebtto/` (self-contained, no writes outside Hermes home).

## 5. Configuration (adapted)

`ebtto: { enabled: true, mode: shadow, ... }` under the Hermes config domain. All keys verified against `hermes_cli/config_defaults.py` as optional, override-able keys.

## 6. Decision log

| Assumption | Verified |
|---|---|
| Python plugin hooks exist | Yes — `pre_tool_call`, `post_tool_call`, `on_session_start/end`, `pre_verify`, `transform_tool_result`, `pre_llm_call`, `post_llm_call`, `on_session_finalize` |
| Hook payload shapes | Yes — `_get_pre_tool_call_directive_details` / `_collect_pre_llm_call_context` / `on_session_start` call sites |
| `register(ctx)` contract | Yes — `disk-cleanup` plugin is the reference |
| SQLite default | Chosen (no dependency) |
| No code guards (hooks isolated) | Verified — hooks are isolated, fail-open/fail-closed policy |
