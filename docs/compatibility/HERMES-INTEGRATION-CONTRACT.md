# EBTTO — Hermes Integration Contract

**Audit scope:** Hermes `hermes-agent` 0.21.5 installed at `<hermes_home>/hermes-agent/` (git HEAD `2943ee6f19`).
Audit date: August 2026 (this session). Python 3.14.7 at `<hermes_home>/.hermes/venv/...`.

---

## 1. Hook API Discovery

### Verified actual hook contract

| Spec assumption | Actual API | Verified source |
|---|---|---|
| `pre_llm_call` / `pre_tool_call` as Python hook names | `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, `on_session_start` etc. as **shell hook event names** | `VALID_HOOKS` in `hermes_cli/plugins.py:326` |
| `PluginManager._hooks[hook_name]` for registration | `ctx.register_hook(hook_name, callback)` — **public PluginContext method** | `hermes_cli/plugins.py:PluginContext.register_hook()` |
| `hermes_cli.lifecycle.invoke_hook` | `invoke_hook(hook_name, **kwargs)` — **module-level public function** | `hermes_cli/plugins.py:invoke_hook()` |
| Plugin hooks fire via Python dispatch | Hooks fire through `shell_hooks.run_once(spec, payload)` — **JSON wire protocol** | `agent/shell_hooks.py` |

### Hook event names (VALID_HOOKS)

```
pre_tool_call, post_tool_call, transform_terminal_output, transform_tool_result,
transform_llm_output, pre_llm_call, post_llm_call, on_stream_start, on_stream_delta,
on_stream_end, on_interim_message, pre_verify, pre_api_request, post_api_request,
api_request_error, pre_auxiliary_call, post_auxiliary_call,
transform_api_error_classification, on_session_start, on_session_end,
on_session_finalize, on_session_reset, gateway_platform_event, pre_command
```

`SHELL_UNSUPPORTED_HOOKS = {"transform_api_error_classification"}` — its directive has no channel; refused loudly.

---

## 2. Plugin registration path

**Public API (preferred):**

```python
def register(ctx):
    @ctx.register_hook("pre_tool_call")
    def on_pre_tool_call(**kwargs):
        # kwargs: tool_name, args, session_id, task_id, tool_call_id, ...
        pass
```

- `ctx` is a `PluginContext` instance passed to `register(ctx)`.
- `PluginContext.register_hook(hook_name, callback)` appends to `PluginManager._hooks` and returns a `PluginRegistration` handle.
- **Never access `PluginManager._hooks` directly in EBTTO** — use `ctx.register_hook()` only, except for compatibility adapters.

---

## 3. JSON wire protocol (shell hooks)

**stdin JSON:**

```json
{
  "hook_event_name": "pre_tool_call",
  "tool_name": "terminal",
  "tool_input": {"command": "ls"},
  "session_id": "session-1",
  "cwd": "/path",
  "extra": {}
}
```

**stdout JSON (post_tool_call):**

```json
{"decision": "continue"}                          // or "block"/"modify"
{"action": "block", "reason": "..."}
{"context": "..."}
```

**Exit codes:**
- 0 = continue; 2 = block (pre_tool_call fail-closed); failure = fail-open unless `fail_on_error` set.

---

## 4. CLI behavior (`hermes experience`)

Registered via `ctx.register_cli_command("experience", ...)` + `PluginContext.register_cli_command()`.
Range: `status`, `stats`, `patterns`, `strategies`, `failures`, `regressions`, `trajectory <id>`, `mode`.

---

## 5. Gateway behavior

Hooks are shared across CLI/gateway via `hermes_cli.lifecycle.invoke_hook` → `PluginManager.invoke_hook` → shell hook dispatch.
Gateway platform events fire via `gateway_platform_event` hook.

---

## 6. Compatibility fallback

`PluginManager._hooks` was used in earlier versions; now the public `ctx.register_hook()` is the only supported
registration path. EBTTO isolates any compatibility adapter in `hermes_ebtto/plugins/compat.py`.

---

## 7. Risk factors from private APIs

| Private API | Risk | Mitigation |
|---|---|---|
| `PluginManager._hooks` | Version-sensitive; changed across Hermes releases | Do not use; use `ctx.register_hook()` |
| `shell_hooks.run_once()` | Internal shell hook execution | Not used by EBTTO |
| `hermes_cli.lifecycle` | Internal module | Use `hermes_cli.plugins.invoke_hook()` |

---

## 8. Conclusion

**Verdict: PASS** — EBTTO adapts to the installed API. Hermes is not modified. The public plugin
contract (`ctx.register_hook()`, `invoke_hook()`, `PluginContext`) is used exclusively.
