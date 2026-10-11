# Production Readiness Report — EBTTO (Post-faa44de Activation Verification)

**Date:** 2026-10-11 (post-faa44de, activation phase)
**Branch:** main @ `faa44de` (HEAD == origin/main, tree clean apart from untracked `experiments/`)
**Remote:** https://github.com/developeralvi/hermes-experience-tool-optimizer.git (verified)
**Evaluator:** Hermes autonomous audit

Supersedes the post-restart report (faa44de). CodeGraph intentionally out of
scope — not evaluated, not a gate.

---

## A. Executive summary

**The activation blocker was found and fixed.** Commit faa44de's fixes were
correct but were being loaded from **three** locations, and the one the
gateway actually imports was a fourth, stale copy:

| # | Location | Role | State before this phase |
|---|---|---|---|
| 1 | `src/hermes_ebtto/` | canonical source | correct |
| 2 | `plugin/` | deliberate mirror | correct (byte-identical) |
| 3 | `%LOCALAPPDATA%\hermes\plugins\hermes_ebtto\` | discovered plugin dir | correct (byte-identical) |
| 4 | `hermes-agent\venv\Lib\site-packages\hermes_ebtto\` | **path the gateway imports** | **STALE: migrations 1-3, pre-fix code** |

The gateway's interpreter resolves `hermes_ebtto` to location **4** (proven by
executing the gateway's own Python with the gateway's `sys.path`), which the
prior phase never synced. All three previously-synced locations were correct
and irrelevant to the running process.

Location 4 is now synced and **byte-identical** to the source across all 28
files, with migrations 1-5 present. The fixes are staged for the next
process start.

**A restart was deliberately NOT performed.** PID 18520 is serving this very
session (ESTABLISHED sockets on its loopback listener, port 8644); Hermes has
no plugin hot-reload (`plugins` CLI offers install/validate/enable/disable —
no reload), and `gateway run --force` would risk corrupting shared gateway
state. Per the mandate not to interrupt active work, the exact minimum manual
action is reported below.

**The telemetry chain is proven end-to-end** by dispatching the *real*
registered hooks (`ctx.register_hook("pre_tool_call", ...)` →
`_hook_pre_tool_call` → `_on_pre_tool_call`, then `post_tool_call`) against an
isolated database with the shipped code:

```
tasks                      1
tool_calls                 1
outcomes                   1
retrieval_events           1     <- fix 3 (was structurally 0 before)
retrieval_guidance_events  1
guidance<->task JOIN: [('<uuid>', 'strat-terminal')]   <- fix 2 (was 0 joinable)
tool_call<->outcome JOIN: [('tc_abc123', 'SUCCESS')]   <- correlation
```

Fail-open was proven by raising inside every telemetry write: the hook
returned normally.

---

## B. Acceptance matrix

| Gate | Status | Evidence |
|---|---|---|
| Latest plugin loaded | **WARN** | venv import path synced to faa44de code (28 files byte-identical); running PID 18520 still holds pre-fix code in memory |
| Gateway restart verified | **NOT APPLICABLE** | no restart performed — active session; documented in C |
| Current schema version | PASS | v5; `schema_version` rows 1-5 recorded (migration 5 at 2026-10-11T07:57:51Z); `tool_call_id` column present in `tool_calls`; `retrieval_events` + `retrieval_guidance_events` tables exist |
| Task ID linkage | PASS | proven by real hook dispatch: guidance event joins `tasks.task_id` (UUID). Production still 0/343 joinable because old code is live — fixed code verified, restart pending |
| New tool_call_id outcomes | PASS | 358 outcomes carry `tool_call_id`; dispatch proof joins `outcomes.tool_call_id = tool_calls.tool_call_id` → `tc_abc123 / SUCCESS` |
| Retrieval telemetry after restart | **WARN** | production `retrieval_events` = 0 (old code never called `record_retrieval`); fixed code writes 1 row per retrieval attempt — proven on isolated DB; activates on next restart |
| Guidance telemetry linkage | **WARN** | 343 real guidance events recorded live (newest 14:18:07Z), candidates/qualified/selected populated; all 343 orphaned under old session-id linkage; fix verified on isolated DB |
| Live Trace reflects new events | PASS | `/api/live_trace` 200; dashboard reports v5/correlation/telemetry-recording/integrity-ok; live counts grow during the audit (2968→3072 outcomes, 246→343 guidance) |
| Memory/source evidence drill-down | PASS | `/api/strategy`, `/api/patterns`, `/api/strategies` all 200; qualification thresholds from `learning.py`; stored≠used counters |
| Production DB integrity | PASS | `PRAGMA integrity_check` = ok; read-only `mode=ro` connections only; no rows inserted, no migration re-run |
| Offline tests | PASS | `python -m pytest tests -q` → **133 passed**, exit 0 |
| A/B harness | PASS | `python experiments/ab_harness/test_harness_ab.py` → ALL HARNESS OFFLINE CHECKS PASSED, exit 0 |
| Ruff/format/MyPy | PASS | ruff check exit 0 (All checks passed); ruff format --check exit 0 (23 files already formatted); mypy exit 0 (no issues, 19 files) |
| Clean package install | PASS | sdist+wheel built; fresh venv: migrations 1-5 packaged, `plugin.yaml` + `dashboard/assets/app.js` present, `register` callable, import OK |
| GitHub billing cause | PASS | exact annotation on the latest run (head faa44de, run 38143410509): *"The job was not started because your account is locked due to a billing issue."* All 8 jobs: `runner_name` empty, 0 steps → no runner allocated. Repo public; Actions permissions `{"enabled":true,"allowed_actions":"all"}`; workflow runner labels standard `ubuntu-latest`; authenticated account `developeralvi` |
| GitHub account lock cleared | **BLOCKED** | unchanged — requires a user billing action |
| Actual GitHub Actions run | **BLOCKED** | same cause; no retry attempted (Phase G policy) |
| Behavioral improvement | **BLOCKED** | **BEHAVIORAL IMPROVEMENT NOT YET PROVEN** — controlled baseline-vs-treatment experiment requires authorized inference |
| Git working tree and remote | PASS | HEAD == origin/main == faa44de; working tree clean apart from untracked `experiments/` (protected) |

---

## C. Activation: the exact minimum manual action

The running gateway cannot activate the fixes without a process start, because
Python caches imported modules and Hermes exposes no plugin reload.

**Minimum action (choose either):**

1. **Graceful:** when the current session/task is finished, restart the
   gateway normally (the same restart the user performed before). Nothing else
   is needed — all four locations are now byte-identical.
2. **From the app:** close and reopen the Hermes desktop app, which restarts
   its gateway.

After either restart, verify with:

```sql
-- should become non-zero and joinable
SELECT COUNT(*) FROM retrieval_events;                                   -- > 0
SELECT COUNT(*) FROM retrieval_guidance_events g
  JOIN tasks t ON t.task_id = g.task_id;                                  -- > 0
```

**Do not** kill every `Hermes.exe` — only the gateway process (currently
PID 18520) needs recycling, and the desktop app does that for you.

---

## D. Dashboard verification

- Process: PID 28556, `python -m hermes_ebtto.dashboard` (hermes-agent venv).
- Endpoints all HTTP 200: `api/system`, `api/overview`, `api/tasks`,
  `api/tool_calls`, `api/guidance`, `api/patterns`, `api/strategies`,
  `api/failures`, `api/evaluations`, `api/task`, `api/strategy`,
  `api/live_trace`.
- Loopback-only confirmed: the host's LAN IP (10.7.0.37:8797) is unreachable
  (`000`, connection refused) while 127.0.0.1 serves 200.
- Freshness: live counts increase across the audit (tasks 2977→3081,
  outcomes 2968→3072, guidance 246→343, newest guidance 14:18:07Z) — the
  dashboard is reading the live database, not a snapshot.
- Same DB as the writer: both resolve to `C:\Users\ENVY\.hermes-ebtto\ebtto.db`
  (discovery fix from faa44de, unchanged).
- Read-only: `mode=ro` + `query_only` connections; no mutation endpoint
  (`/api/reset` → 404).

---

## E. GitHub Actions billing diagnosis (unchanged, evidence re-verified)

- Latest run `38143410509` (head `faa44de`), status completed / conclusion
  failure. All 8 jobs: `runner_name` = `""`, `steps` = 0, no logs — **no
  runner was ever allocated**.
- Exact annotation: *"The job was not started because your account is locked
  due to a billing issue."*
- Not a config defect: repo public, Actions enabled with `allowed_actions:
  all`, workflow labels standard, no orphaned runs.
- Billing state is not readable with the current token (needs `user` scope);
  credential scopes were not altered without authorization.

**Two official options** (user decision — no payment action taken):

1. Resolve the past-due/failed-payment issue: Settings → **Billing &
   Licensing** → Payment information → update the payment method to trigger a
   newly authorized charge. Reference:
   https://docs.github.com/en/billing/how-tos/troubleshooting/locked-account
2. **Downgrade to GitHub Free** to keep advanced features in this public
   repository, with Actions on GitHub's included free minutes and no payment.
   Reference:
   https://docs.github.com/en/billing/how-tos/manage-plan-and-licenses/downgrade-plan
   and https://docs.github.com/en/billing/concepts/product-billing/github-actions

After either, the workflow will run unchanged — the two CI defects from the
prior phase (migration assertion, ruff formatting) are already fixed on
`origin/main`.

---

## F. Known limitations (honest)

1. **Activation requires one process start** (section C). Until then the live
   process keeps writing session-id guidance events (0/343 joinable) and no
   `retrieval_events` rows. The dashboard correctly shows these stages as NOT
   RECORDED rather than fabricating them.
2. **Downstream delivery NOT VERIFIED** by architecture — no telemetry exists
   past the hook return; the dashboard says so explicitly.
3. **Behavioral improvement NOT YET PROVEN** — no controlled inference run.

---

## G. Final verdict

**PARTIAL — activation path fixed and verified in isolation; GitHub Actions
blocked on an account billing lock; one restart pending user action.**

Everything within reach is implemented, proven against the real hook
dispatch path, tested (133 + 41), lint-, format- and type-clean, packaged,
and pushed at `faa44de`. Remaining items are user actions: restart to
activate, billing resolution or downgrade to Free, and authorized inference
for the behavioral benchmark.
