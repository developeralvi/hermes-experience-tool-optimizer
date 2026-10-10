# EBTTO Modes — Verified Runtime Contract

This document is the authoritative reference for EBTTO's mode semantics. It is
written from the implementation in
`src/hermes_ebtto/plugins/__init__.py` and is intended to let a developer
understand behaviour **without reading the code**. Where the implementation and
any other document disagree, **this document and the source are authoritative**.

Verified against commit `f3ec110`.

Mode names are defined in **three places, which disagree on the default**. This
is a real inconsistency, documented here rather than silently resolved:

| Location | Role | Default it declares |
|---|---|---|
| `plugins/__init__.py` — `EBTTOPlugin.__init__` (`config.get("mode", MODE_RECORD_ONLY)`) | Instance default when constructed directly | `record_only` |
| `plugins/__init__.py` — `register(ctx)` (`ctx.get_config("mode", "record_only")`, overridable by `EBTTO_MODE`) | **The path Hermes actually uses.** | `record_only` |
| `config.py` — `DEFAULTS["mode"]` | Standalone-config defaults dict | `shadow` |

**The effective runtime default is `record_only`**, because `register(ctx)` — the
only path the running Hermes process invokes — never reads `config.py`'s
`DEFAULTS`. `config.py`'s `shadow` value is therefore a latent inconsistency: it
is dead for the plugin path, but would surprise anyone importing the config
module directly.

**Mode resolution order** (first hit wins):

1. `EBTTO_MODE` environment variable — profile-independent escape hatch.
2. `ctx.get_config("mode")` — i.e. `plugins.entries.<id>.settings.mode`.
3. `"record_only"`.

Valid mode names (`config.py::VALID_MODES`):
`off`, `record_only`, `shadow`, `advisory`, `guarded`, `controlled_auto`.


---

## 1. Two hook stages — the distinction that explains `shadow`

EBTTO registers several Hermes hooks. Two of them are mode-sensitive, and they
operate at fundamentally different points in a turn. Conflating them is the
single most common source of confusion about `shadow` mode.

### Pre-selection guidance — `pre_llm_call`

Fires **once per turn, before the provider/tool-calling loop is built**. Hermes
dispatches it through `agent/turn_context.py::_collect_pre_llm_call_context`,
which collects a `{"context": "..."}` result from each plugin and appends it to
the **user message** — never the system prompt.

Consequence: anything returned here is visible to the model **when it decides
which tool to call**. This is the only hook in EBTTO that can influence tool
*selection*.

### Post-selection observation — `pre_tool_call`

Fires **immediately before an individual tool executes**, after the model has
already chosen that tool and its arguments. Returning `None` means "continue
normally". Returning a directive dict lets the plugin modify, gate, or rewrite
the call.

Consequence: by the time this hook runs, the selection decision is already made.
It is **too late to influence which tool was chosen** — it can only affect what
happens *to that chosen call*.

> This is why `shadow` can legitimately be "passive" and still deliver guidance:
> the guidance was already in the prompt at selection time.

---

## 2. Mode contract table

Every cell below is read directly from the implementation. "No guidance" means
`_retrieve_guidance_for_task()` is never called for that mode/stage.

| Mode | `pre_llm_call` (pre-selection) | `pre_tool_call` (post-selection) | Net effect |
|------|-------------------------------|----------------------------------|------------|
| `off` | Returns `None` on the first guard. No retrieval. | Returns `None` on the first guard, **before recording the tool call**. | Plugin fully inert; no data collected. |
| `record_only` *(default)* | Returns `None` immediately. No retrieval, no injection. | Records the task + tool call (`result_status="PENDING"`), then returns `None`. No guidance retrieved, nothing logged. | Observe and record only. **Cannot influence tool selection.** |
| `shadow` | Retrieves guidance and **returns `{"context": "<text>"}`**, which Hermes appends to the user message. | Records the call, retrieves guidance, and **logs** `[EBTTO SHADOW] Guidance: <strategy_name>`. **Returns `None`** — never modifies or blocks. | **Mixed by design.** May influence tool *selection* via the prompt; never changes or blocks the tool *call*. |
| `advisory` | Identical retrieval and injection to `shadow`. | Returns `guidance["directive"]` (defaults to `{"action": "continue", "guidance": ...}`). | May influence selection and surfaces a directive to the runtime. Does not modify or block. |
| `guarded` | Identical retrieval and injection to `shadow`. | Logs `[EBTTO GUARDED] Requires user approval before executing: ...` and returns `{"action": "continue", "requires_approval": True, "guidance": ...}`. | Can require approval before a tool executes. |
| `controlled_auto` | Identical retrieval and injection to `shadow`. | Calls `_apply_strategy_to_args(tool_name, args, guidance)` and returns its result. | Can **rewrite the tool call's arguments**. Disabled by default; must be enabled explicitly. |

### Shared behaviour (all modes)

- **All hooks fail open.** Every hook body is wrapped in `try/except`; any
  storage or EBTTO error is logged and the hook returns `None`. EBTTO can never
  break the ordinary Hermes tool loop.
- **`post_tool_call` is not mode-gated.** Outcomes, failures, and pattern
  learning are recorded in every mode except `off`, because recording is what
  makes guidance possible later.
- **`guidance_injected` is a delivery counter, not an effect counter.** It
  increments whenever guidance is produced for a hook. It does **not** measure
  whether the model changed its behaviour.

---

## 3. `shadow` mode in detail

`shadow` is deliberately **asymmetric** between the two hook stages:

- At `pre_llm_call` it injects learned experience into the model's prompt.
- At `pre_tool_call` it only logs.

This is intentional, not an inconsistency. The design treats *changing what the
model is shown* as observation, and *altering or blocking an actual tool
execution* as intervention. A "shadow" run is therefore one where execution is
untouched, but the model is allowed to see prior experience and decide for
itself.

### Open design question (not a defect)

Whether guidance injection belongs in a mode named `shadow` is a legitimate
product-design question. A reader could reasonably expect `shadow` to mean
"log only, never touch the model's input". The implementation does not do that.

This document records the actual behaviour and flags the question. It does
**not** silently redefine `shadow` to be log-only, rename the configuration
value, or migrate existing user settings. Changing the semantics is a product
decision that should be made explicitly, with a migration path for anyone whose
config currently reads `mode: shadow`.

### What shadow mode guarantees

- The tool call is never modified, blocked, or gated.
- No stored strategy is executed as code.
- The system prompt is never modified.
- Guidance is labelled advisory and the model is told to ignore it if it does
  not fit.

### What shadow mode does *not* guarantee

- That the model will act on the guidance.
- That guidance is present at all (see §4).

---

## 4. When guidance is absent

Guidance is **not** injected on every turn. `_retrieve_guidance_for_task()`
returns `None`, and the turn proceeds exactly as it would without EBTTO, when:

1. `self.store is None` or the plugin is disabled.
2. No strategy passes the qualification thresholds for the resolved task family.
3. `get_patterns_by_tool(family)` returns no rows — most commonly because the
   task family resolved to `general`, which has no learned experience.
4. Any exception occurs inside retrieval (logged, then fail open).

Qualification thresholds are enforced in `src/hermes_ebtto/learning.py`:

- `MIN_EVIDENCE_FOR_VALIDATED` = 5 — at least 5 independent outcomes.
- `MIN_SUCCESS_RATE` = 0.8 — at least 80% of outcomes must succeed.
- `MIN_INDEPENDENT_CONTEXTS` = 3 — at least 3 distinct contexts.

A `patterns` or `strategies` row is created **only** when a tool's accumulated
evidence clears all three.

---

## 5. Task-family resolution

The task family is the retrieval key, and it must use the same vocabulary that
learning stores (`task_family = <tool_name>`).

`_derive_task_family(user_message)` resolves in two tiers:

1. **Explicit tool mention wins.** If the message names a tool
   (`terminal`, `execute_code`, `read_file`, `patch`, `write_file`,
   `search_files`, `browser_exec`, or a `"<x> tool"` phrase), that name is the
   family. This tier exists because "Use the terminal tool to run `python -c
   ...`" names `terminal` but incidentally contains `python`, which would
   otherwise capture it into the `execute_code` bucket and retrieve the wrong
   tool's evidence.
2. **Keyword matching** only when no tool is named.

Unrecognised messages resolve to `general`, which has no learned experience and
therefore produces no guidance.

---

## 6. Evidence limits — what has actually been verified

Separate the evidence tiers; they are not interchangeable.

- **Source-verified (this document):** every mode/hook behaviour in §2 is read
  directly from the implementation at commit `f3ec110`.
- **Unit-test verified:** `test_gap1.py` (29/29) and `test_gap2.py` (13/13)
  cover failure persistence, pattern qualification thresholds, retrieval, and
  task-family mapping.
- **Live-runtime verified (historical):** a live one-shot turn at
  2026-10-10 12:47 UTC produced a redacted `HERMES_DUMP_REQUESTS` preflight dump
  showing genuine EBTTO guidance (`EBTTO prior experience ... Previous similar
  calls to terminal succeeded with 'terminal best practice' (success rate 89%
  over 299 examples)`) present in the **tool-selection request** — the request
  containing only `system` and `user` messages, with no tool result yet. That
  dump is historical evidence from a previous certification phase; it is not
  re-collected here.
- **NOT verified:** that guidance changed any model decision. Presence in a
  request proves delivery before selection, nothing more. Establishing a
  behavioural effect requires a controlled baseline-vs-EBTTO comparison, which
  has not been completed.

---

## 7. Historical note

Earlier README wording listed only `record_only`, `advisory`, and `auto`. The
implementation additionally defines `shadow`, `guarded`, `controlled_auto`, and
`off`. The README's `auto` corresponds to the `controlled_auto` constant.
Historical acceptance reports in `docs/acceptance/` are preserved unchanged and
reflect the state of the repository at the time they were written.
