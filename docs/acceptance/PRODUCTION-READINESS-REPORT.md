# EBTTO Phase H — Post-Restart Live Activation & Production Telemetry

Report date: 2026-10-11
Repository: `C:\Users\ENVY\StéWork\EBTTO` (branch `main`)
Remote: `https://github.com/developeralvi/hermes-experience-tool-optimizer.git`
Report baseline commit: `7ae7c24`

Every claim below is labelled with the strongest evidence available. Nothing is
claimed from an isolated test as if it were production behavior.

Legend:

* **[LIVE]** — verified in the live production runtime
* **[DB-RO]** — verified against the production database in read-only mode (`mode=ro`, `PRAGMA query_only=ON`)
* **[ISOLATED]** — verified in an isolated test
* **[INFERRED]** — inferred, not directly verified
* **[NOT TESTED]**

---

## 1. Gate summary

| Gate | Result | Evidence | Remaining blocker |
|---|---|---|---|
| Runtime activation | **PASS [LIVE]** | Gateway PID 24216 started 2026-10-11 23:56:45 local (17:56:45Z), after the 19:27 venv sync; 2,317 new `retrieval_events` and 2,091 new guidance rows written since that boundary | none — new events prove new code is live |
| Imported package provenance | **PASS [LIVE+DB-RO]** | All 4 locations byte-identical, 28 files each (SHA-256 compared). `retrieval_events` was structurally 0 before the fix and is 2,318 now — only fixed code calls `record_retrieval()` | none; the running process's in-memory module is not directly inspectable |
| Live production telemetry | **PASS [DB-RO]** | Post-restart: 2,294 tasks, 2,170 tool_calls, 2,143 outcomes, 2,317 retrieval_events, 2,091 guidance events | none |
| Guidance → task join | **PASS [DB-RO]** | 2,068 / 2,091 post-restart = **98.9%** joinable (was 0 / 248 before activation) | 23 orphans, all `pre_llm_call` — see §4 |
| Tool-call → outcome correlation | **PASS [DB-RO]** | Post-restart **2,127 / 2,171 = 98.0%** (overall 48.3%, because pre-restart rows are legacy) | none |
| Fail-open | **PASS [ISOLATED]** | 5/5 checks in the gateway venv; total telemetry outage returned normally | verified isolated, not in production |
| Behavioral improvement | **NOT PROVEN** | No controlled control-vs-treatment comparison was run | requires authorized inference; see §5 |
| Regression suite | **PASS** | 141 passed / 1 skipped; A/B harness offline PASS; ruff check PASS; ruff format 25 files; mypy 19 files clean | none |
| Git state | **PASS** | HEAD == origin/main == `7ae7c24` before this phase's commit; `7ae7c24` is an ancestor of HEAD | transient network resets during fetch (recovered) |
| GitHub Actions | **BLOCKED [LIVE]** | Run `38147351098` (head 7ae7c24): 8/8 jobs, `runner_name` empty, 0 steps | account-level billing lock — external, not a repo defect |
| Four-location consistency | **PASS** | `tools/sync_installed.py --check` exit 0; 8 new regression tests | none |

---

## 2. Runtime activation — PASS

**Gateway identity [LIVE]**

```
PID 24216  python -I <hermes-agent>/agent.py gateway run   started 2026-10-11 23:56:45 (local)
PID 24412  node <hermes-agent>/dist/gateway/server.js       started 2026-10-11 23:56:48 (local)
PID 13072  Hermes.exe                                        started 2026-10-11 23:56:30 (local)
```

The previous gateway PID 18520 no longer exists. The current gateway started
**after** the 19:27 venv synchronization from the prior phase.

**Provenance [DB-RO]** — the decisive evidence is behavioral, not timestamp-based:

| Table | Before this phase | Now |
|---|---|---|
| `retrieval_events` | 0 rows (structurally — no runtime path called `record_retrieval()`) | **2,318 rows** |

`record_retrieval()` is invoked *only* by the fixed code path. 2,317 of those
rows were written after the restart boundary. A pre-fix gateway cannot produce
a single row in that table. **The running gateway is executing the corrected
code.** [DB-RO]

**Package location consistency** — SHA-256 of every shippable file, 28 files
per location:

| Location | Files | Status |
|---|---|---|
| `src/hermes_ebtto/` (canonical) | 28 | reference |
| `plugin/` (in-repo mirror) | 28 | identical |
| `%LOCALAPPDATA%/hermes/plugins/hermes_ebtto/` | 28 | identical |
| `hermes-agent/venv/Lib/site-packages/hermes_ebtto/` | 28 | identical |

Migrations `1..5` present in all four. [LIVE + ISOLATED]

**Limitation, stated explicitly:** a running Python process's already-imported
module is not directly inspectable from outside. Provenance is therefore
established from the *effects* the process produces (new `retrieval_events`
rows, correct joins), not from reading its memory. This is the strongest
available evidence and it is unambiguous here.

---

## 3. Live telemetry chain — PASS

All figures below are post-restart (boundary `2026-10-11T17:56:45Z`), read-only.
[DB-RO]

| Table | New rows | Total |
|---|---|---|
| `tasks` | 2,294 | 5,471 |
| `tool_calls` | 2,170 | 5,347 |
| `outcomes` | 2,143 | 5,312 |
| `retrieval_events` | 2,317 | 2,318 |
| `retrieval_guidance_events` | 2,091 | 2,513 |

**Guidance → task join:** 2,068 / 2,091 = **98.9%** joinable on `guidance.task_id = tasks.task_id`.
Before activation the figure was **0 / 248 = 0%**.

**Tool-call → outcome correlation:** 2,127 / 2,171 = **98.0%** post-restart on
`tool_calls.tool_call_id = outcomes.tool_call_id`. The 48.3% all-time figure is
legacy pre-restart data, not a current defect.

**Complete chain, real identifiers [DB-RO]:**

```
task_id              db85dc38-62d1-4111-b349-9a9088172c08
task_family          terminal
tool_call_id         call_8eeb87e9179c414da4e0e2dd   (tool: terminal)
outcome              SUCCESS
guidance_id          7eed1cb1-de17-4eeb-ac63-6eda61a5e1dd
selected_strategy_id strat-terminal-20261008
guidance_returned    1
```

`retrieval_events` has no `task_id` column — it is keyed by `task_fingerprint`.
The fingerprint join is therefore a many-to-many link and is reported as
supporting evidence, not as a primary key chain: 1,225,861 fingerprint pairs.

---

## 4. New defect found and fixed — `pre_llm_call` guidance orphans

**Finding [DB-RO]:** 23 post-restart guidance events did not join any task. All
23 carry `hook = 'pre_llm_call'` and every one of their `task_id` values is a
**Hermes session id** (`20261009_011112_f91965`, `20261011_010204_95668a`), not
a task uuid.

**Root cause:** `_on_pre_llm_call` in `src/hermes_ebtto/plugins/__init__.py`
took `kwargs["task_id"] or kwargs["session_id"]` and passed it straight into
`_record_retrieval_event`. Tasks are keyed by a generated uuid, so a session id
can never join. This is the *same class* of defect as the earlier guidance
linkage bug — the earlier fix was applied only to the `pre_tool_call` path.

**Fix:** `_on_pre_llm_call` now records the task first (`store.record_task`) and
links telemetry to the returned uuid via `link_id`, mirroring the pre_tool_call
fix. When the store is unavailable, `link_id` is empty rather than a session id,
so the code never links telemetry to an unjoinable identifier.

**Verification [ISOLATED, real hook dispatch]:**

```
pre_llm_call returned: context
guidance 1 | joinable 1 | orphaned 0
  JOINED: ('e434f101-38d0-48f8-a5f5-c48cbd603c30', 'terminal', 'terminal',
           'pre_llm_call', 'strat-terminal', 1)
  retrieval_events: 1
```

`guidance_returned=1` confirms the guidance reached the model decision path, not
just the database.

**Negative control [ISOLATED]:** the fix was reverted in `src/` and the
regression test failed (`1 failed`, orphan assertion triggered); the source was
then restored. The test genuinely detects the defect rather than passing
vacuously.

**Test:** `tests/unit/test_dashboard.py::test_pre_llm_call_guidance_joins_stored_task_uuid`
— **PASSED inside the gateway venv** (real run, not a skip; it `importorskip`s
`hermes_cli.plugins`, which only resolves there).

**Caveat [LIVE]:** the 23 orphans were produced by the *currently running*
gateway, which loaded the code before this fix. The fix is active in all four
source locations but takes effect only on the next gateway restart. New
`pre_llm_call` rows will still be orphans until then.

---

## 5. Behavioral improvement — NOT PROVEN

No controlled comparison was run.

A populated guidance table is not behavioral improvement. A successful model
response is not behavioral improvement. This phase produced no control arm and
no treatment arm, and therefore no causal claim.

What *is* proven: EBTTO guidance is being **selected and returned** during
genuine runtime — `selected_strategy_id` is populated (e.g.
`strat-terminal-20261008`) with `guidance_returned=1` on live tasks. That is
evidence of correct plumbing, not of outcome improvement.

**Blocker:** proving improvement requires running the repository's A/B harness
with real inference, holding input, tools, model and settings constant across a
control and a treatment arm. That requires an authorized, zero-cost provider
and explicit approval to spend inference. Neither was granted in this phase.
The A/B harness itself passes **41/41 offline checks**, so the measurement
instrument is ready; only the authorized inference run is missing.

---

## 6. Fail-open — PASS [ISOLATED]

Verified in the gateway venv by injecting failures into the running plugin:

| Check | Result |
|---|---|
| Telemetry write failure (`RuntimeError` into `record_task`, `record_retrieval`, `store._execute`) → hook returned normally | PASS |
| Missing `user_message` → handled | PASS |
| Non-str `user_message` (dict) → coerced, no crash | PASS |
| Store disabled (`store = None`) → guidance still returned | PASS |
| Sensitive values: `sanitized_intent` truncated, no raw args leaked | PASS |

Production writes were never sabotaged; all failures were injected into
isolated temporary databases.

**Limitation:** this is [ISOLATED]. It does not prove the running gateway
survives a production telemetry outage. The fail-open unit tests cover the same
code paths and pass in CI.

---

## 7. Regression suite — PASS

Fresh exit codes, all run against the code in this commit:

| Gate | Result | Exit |
|---|---|---|
| `pytest tests -q` | **141 passed, 1 skipped**, 1 warning | 0 |
| A/B harness (offline checks) | ALL HARNESS OFFLINE CHECKS PASSED | 0 |
| `ruff check src tools tests` | All checks passed! | 0 |
| `ruff format --check src tools tests` | 25 files already formatted | 0 |
| `mypy src --ignore-missing-imports` | Success: no issues found in 19 source files | 0 |
| `tools/sync_installed.py --check` | plugins-dir OK, venv-site-packages OK (28 files each) | 0 |

The single skip is `test_pre_llm_call_guidance_joins_stored_task_uuid` under the
lint venv, which lacks `hermes_cli`. It **passes in the gateway venv** — the
skip is an environment artifact, not a failing test.

**New tests added (8, all passing):** `tests/unit/test_installed_consistency.py`
— asserts every installed location is byte-identical to `src/`, has no orphan
files, and contains migrations 1–5.

---

## 8. New tooling — `tools/sync_installed.py`

Added because the invariant that caused the original four-copy defect was never
enforced by anything.

* `python tools/sync_installed.py` — syncs `plugin/` mirror and both installed locations
* `python tools/sync_installed.py --check` — verify only, exit 1 on drift
* `python tools/sync_installed.py --dry-run` — report without writing

Formatting order matters: `ruff format src` must run **before** the sync.
Running it after silently re-breaks the mirror, which happened during this
phase and was caught by `test_mirror_files_are_byte_identical`.

Also removed a stale orphan `%LOCALAPPDATA%/hermes/plugins/hermes_ebtto/queries.py`
(duplicate of `dashboard/queries.py` from an older layout, unreferenced).

---

## 9. Git state

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD before this phase | `7ae7c24` |
| `7ae7c24` ancestor of HEAD | YES |
| HEAD == origin/main | YES (`7ae7c24` before this phase's commit) |
| Files modified | `src/hermes_ebtto/plugins/__init__.py`, `plugin/plugins/__init__.py`, `tests/unit/test_dashboard.py` |
| Files added | `tools/sync_installed.py`, `tests/unit/test_installed_consistency.py` |
| Untracked | `experiments/` (pre-existing, unrelated) |

No database, venv, `.pyc`, or log file was ever staged or committed.

---

## 10. GitHub Actions — BLOCKED (external, account-level)

Latest run: **`38147351098`**, head `7ae7c24`, status `failure`, created
2026-10-11T14:28:58Z.

All 8 jobs: `runner_name` empty, **0 steps**, no runner allocated.

Verbatim annotation from the run page:

> "The job was not started because your account is locked due to a billing issue."

This is an **account-side restriction**, not a repository defect. The workflow
YAML, permissions, runner labels and code are not implicated — no job ever
started. Repository-side fixes from the prior phases (the migration assertion
and ruff formatting) remain in place and will be exercised once the lock clears.

No billing action, token-scope change, subscription change or payment was made.
The `gh` token lacks the `user` scope needed to read billing state, and scope
changes were declined pending authorization.

**Smallest safe next action (account owner only):** in GitHub → Settings →
Billing and Licensing, either update the payment method or downgrade the account
to **GitHub Free** — public repositories retain included Actions minutes, so CI
will run unchanged at zero cost.

---

## 11. Outstanding issues

| # | Blocker | Impact | Smallest safe next action |
|---|---|---|---|
| 1 | Gateway restart needed to activate the `pre_llm_call` fix | New `pre_llm_call` guidance rows remain unjoinable (23 and counting) | Restart the gateway when no session is active; verify `SELECT COUNT(*) FROM retrieval_guidance_events g LEFT JOIN tasks t ON t.task_id=g.task_id WHERE t.task_id IS NULL AND hook='pre_llm_call'` stops growing |
| 2 | GitHub Actions account billing lock | CI cannot run; no CI signal for any commit | Account owner: update payment or downgrade to GitHub Free |
| 3 | Behavioral improvement unproven | Cannot claim EBTTO changes outcomes | Run the A/B harness with an authorized, zero-cost provider; needs explicit approval |
| 4 | `model`/`provider` recorded as `unknown` on tasks | Weakens per-model analysis | Fix `model`/`provider` propagation in the task-creation path; requires confirming what the gateway actually supplies |

---

## 12. Explicit non-claims

* **Not claimed:** that the running process's in-memory module is the fixed code
  — established from its output effects instead, which is stronger than a
  timestamp and weaker than direct memory inspection.
* **Not claimed:** that isolated fail-open tests prove production resilience.
* **Not claimed:** any behavioral improvement, causality, or outcome change.
* **Not claimed:** that GitHub Actions works, or that repository fixes removed
  the account-level restriction.
* **Not claimed:** a successful CI run. None has ever executed against any
  commit in this project.
