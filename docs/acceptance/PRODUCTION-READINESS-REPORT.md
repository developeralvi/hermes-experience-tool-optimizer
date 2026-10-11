# Production Readiness Report — EBTTO (Post-Restart Live Verification)

**Date:** 2026-10-11 (post manual gateway restart)
**Branch:** main
**Remote:** https://github.com/developeralvi/hermes-experience-tool-optimizer.git (verified origin)
**Evaluator:** Hermes autonomous audit

Supersedes the Live Observability Phase report (commit 886bfb3).

---

## A. Executive summary

The restarted gateway **is** running the v5 plugin: per-tool-call outcome
correlation is live (117 successes, 9 failures correlated via
`tool_call_id`), and retrieval/guidance telemetry is recording real events.

**Three genuine defects were found and fixed in this phase:**

1. **The dashboard read the WRONG database.** Two valid storage locations
   exist on this machine: `%LOCALAPPDATA%\hermes\.hermes-ebtto\ebtto.db`
   (stale, empty, v3 — created by an older CLI run) and
   `C:\Users\ENVY\.hermes-ebtto\ebtto.db` (live, v5, 2752+ rows — where the
   gateway writes). The dashboard's default resolution used the writer's
   environment-dependent path and bound to the empty one, showing
   "v3, 0 events" while real data flowed next door. Fixed with
   `discover_db_path()`: the dashboard now inspects every candidate location
   and binds to the one holding real recorded rows. Regression tests added.
2. **Guidance events could not be linked to tasks.** The pre_tool hook
   persisted the Hermes *session* id as the retrieval event's `task_id`,
   while the `tasks` table is keyed by the generated uuid — so no guidance
   event ever joined a task and the Live Trace always showed
   "RETRIEVAL NOT RECORDED" even with 126 real events in the DB. Fixed:
   the hook now records the stored `task_id_db`. Functional proof +
   regression test.
3. **`retrieval_events` was dead — the runtime never called
   `record_retrieval()`.** Migration 4 created the table; the retrieval path
   queried patterns but never logged the attempt, so the table sat at 0 rows
   in every installation. Fixed: the retrieval attempt is now recorded
   (distinguishing "ran and matched nothing" from "never ran").
   Functional proof + regression test.

**Two CI defects were also fixed** (would have failed even if billing were
resolved):

4. `ci.yml` asserted migrations `['1','2','3']` — the project now ships 5.
5. `ruff format --check` was never runnable before (CI never executed); 18
   files were unformatted. The formatter is now applied and the gate passes.

**GitHub Actions remains BLOCKED** — diagnosed precisely as an account-level
billing lock (see section F). No payment action was taken; no charge was
authorized.

---

## B. Acceptance matrix

| Gate | Status | Evidence |
|---|---|---|
| Repository identity | PASS | `C:/Users/ENVY/StéWork/EBTTO`, origin verified; HEAD == origin/main |
| Gateway restart confirmed | PASS | PID 18520, started 2026-10-11 18:46:21 (this shell's processes started earlier); imports EBTTOStore with `_sqlite3` loaded |
| Correct plugin version loaded | PASS | Live DB receives correlated outcomes + guidance events written by the post-restart process (first correlated outcome 13:01:19 UTC > restart 12:46:21 UTC) |
| Current schema version | PASS | v5 on the live DB (expected v5); `tool_call_id` column present; `retrieval_guidance_events` + `retrieval_events` tables present |
| Production backup/migration status | PASS | v3→v5 upgrade from prior phase; WAL-consistent backup at `~/.hermes-ebtto/backups/ebtto-v3-pre-migration5-20261011T075733Z.db` (verified) |
| New tool-call IDs being persisted | PASS | 7+ outcomes with non-NULL `tool_call_id` recorded post-restart (13:00:48 → 13:03:32 UTC) |
| Tool-call/outcome correlation verified | PASS | Live join `outcomes.tool_call_id = tool_calls.tool_call_id` returns real rows (e.g. `terminal / SUCCESS / 13:01:19`); session-prefix inheritance rejected by tests |
| UNKNOWN legacy outcomes handled | PASS | 2723 legacy outcomes (NULL tool_call_id) read UNKNOWN, excluded from success rate; 24h window: 117 succeeded / 9 failed / 1943 unknown |
| Retrieval telemetry recording | PASS | `retrieval_guidance_events`: 126 rows, newest 13:20:00 UTC, hook=pre_tool_call, candidates/qualified/selected populated |
| Guidance-return telemetry recording | PASS | guidance_returned=1 rows with `selected_strategy_id` (e.g. `strat-terminal`, `strat-skill_view`) |
| Live Usage Trace updates | PASS | `/api/live_trace` on a real task shows TASK OBSERVED → TOOL CALL → OUTCOME RECORDED (SUCCESS, confidence 0.9) → honest NOT RECORDED/NOT VERIFIED for un-instrumented stages |
| Memory detail/source evidence works | PASS | qualification thresholds from learning.py, stored≠used counters, source trajectory click-through (prior phase; unchanged) |
| Dashboard APIs reflect actual current data | PASS | live `/api/system`: v5, correlation true, telemetry recording, 126+ events, integrity ok, last event 13:20+ |
| Read-only database access | PASS | `mode=ro` + `query_only` connections; write-attempt tests pass |
| Connection cleanup and load stability | PASS | per-request open/close; 300-cycle + 300-request tests stable |
| Security/privacy regressions | PASS | no `raw_args` in API/frontend; allowlists; redaction tests; loopback-only + Host allowlist; no mutation endpoints (`/api/reset` → 404) |
| Full offline test suite | PASS | `python -m pytest tests -q` → **133 passed**, exit 0 (was 128; +5 for discovery + linkage) |
| A/B harness | PASS | `python experiments/ab_harness/test_harness_ab.py` → 41/41, exit 0 |
| Ruff | PASS | `ruff check src tests` → All checks passed, exit 0; `ruff format --check src tests` → 23 formatted, exit 0 |
| MyPy | PASS | `mypy src --ignore-missing-imports` → no issues, exit 0 |
| Package build and clean installation | PASS | wheel built; fresh venv install: migrations 1-5 packaged, plugin.yaml + dashboard assets present, import OK |
| Mirror consistency | PASS | byte-identical mirror tests pass (caught and enforced every sync this phase) |
| GitHub billing cause identified | PASS | job banner verbatim: "The job was not started because your account is locked due to a billing issue."; jobs have empty runner_name, zero steps, no logs (BlobNotFound) → no runner was ever allocated; Actions permissions = enabled/all-all; repo = public |
| GitHub billing blocker resolved | BLOCKED | account-level lock requires a user payment action (see F) |
| GitHub Actions real run | BLOCKED | same cause; retry not justified until resolved |
| GitHub About metadata | PASS | description + 9 topics via API |
| Behavioral improvement measured | BLOCKED | **BEHAVIORAL IMPROVEMENT NOT YET PROVEN** — controlled benchmark needs authorized inference |
| Production data integrity | PASS | integrity_check ok; row counts monotonic; legacy rows untouched |
| Git clean/pushed state | PASS | working tree clean apart from untracked `experiments/`; mirrors synced |
| Release readiness | BLOCKED | GitHub Actions gate open |

Statuses use only PASS / FAIL / BLOCKED / WARN / NOT VERIFIED / NOT
APPLICABLE. CodeGraph: intentionally out of scope per owner — not
evaluated, not a gate.

---

## C. Live runtime evidence (this phase)

- **Gateway:** PID 18520 — `...tools\python-3.14.7...\python.exe -m hermes_cli.main gateway run`, started 2026-10-11 18:46:21 local.
- **Live DB:** `C:\Users\ENVY\.hermes-ebtto\ebtto.db` — schema v5, integrity ok, 2752+ tool_calls, last outcome 13:03:32 UTC, guidance events through 13:20 UTC (live during this audit).
- **Correlation sample (post-restart):** `terminal | call PENDING | outcome SUCCESS | 13:01:19`, plus 6 more through 13:03:32.
- **Guidance sample:** `('pre_tool_call', 1, 1, 'strat-terminal', '2026-10-11T13:19:51Z')`.
- **Telemetry state:** `recording` (126 guidance events; retrieval_events rows begin with the new code after the next restart).
- **Dashboard:** running on 127.0.0.1:8797 against the live DB; `/api/system` reports v5/correlation/recording/integrity-ok; `/api/live_trace` returns real chains.

## D. Known limitations (honest)

1. **The two telemetry fixes activate on the NEXT gateway restart.** The
   running process has the old in-memory plugin: new guidance events still
   store the session id and retrieval_events stays empty until restart.
   The dashboard's Live Trace correctly shows RETRIEVAL NOT RECORDED for
   those. The fixes are in the synced plugin dir; one restart completes them.
   (Restart deliberately NOT forced: an active session was running.)
2. **Downstream delivery is NOT VERIFIED by architecture** — no telemetry
   exists past the hook return; the dashboard says so explicitly.
3. **Behavioral improvement NOT YET PROVEN** — no controlled inference run.

## E. Changes this phase

| File | Change |
|---|---|
| `src/hermes_ebtto/storage.py` | `candidate_db_paths()` — every valid `.hermes-ebtto` dir |
| `src/hermes_ebtto/dashboard/queries.py` | `discover_db_path()` — bind to the DB that actually holds rows; `open_ro()` uses it |
| `src/hermes_ebtto/dashboard/server.py` | startup prints the discovered DB |
| `src/hermes_ebtto/plugins/__init__.py` | guidance events linked to stored task_id_db; retrieval attempt now recorded via new `EBTTOStore.record_retrieval` |
| `.github/workflows/ci.yml` | migrations assert 1-5 (was 1-3) |
| `pyproject.toml` | E402 ignored for tests (intentional harness import order) |
| `tests/unit/test_dashboard.py` | +5 tests (DB discovery, guidance linkage, retrieval persistence) |
| `plugin/` + installed plugin | re-synced after ruff format |
| 18 files | ruff format applied (CI format gate would have failed) |

## F. GitHub Actions billing diagnosis

**Evidence:**
- Job banner (verbatim from the run page):
  "The job was not started because your account is locked due to a billing
  issue."
- Every job: `status=completed, conclusion=failure`, `runner_name` empty,
  zero steps, logs endpoint returns BlobNotFound — no runner was ever
  allocated.
- Repo is public; Actions permissions `enabled=true, allowed_actions=all` —
  no permission defect.
- Every run since 2026-10-10 fails identically; no run ever succeeded.
- `gh` token lacks the `user` scope, so billing state cannot be read
  directly (endpoint 404).

**Per GitHub docs** (billing/how-tos/troubleshooting/locked-account): a
locked account means advanced features are locked because a payment is past
due, or a payment authorization failed. Resolution options from GitHub's
official guidance:

1. **Personal account:** Settings → Billing & Licensing → Payment
   information → update the payment method to trigger a newly authorized
   charge. *(Requires the user; involves billing — not done here.)*
2. **No payment wanted?** GitHub documents that you can **downgrade the
   account to GitHub Free** to keep advanced features **in public
   repositories** — Actions on public repos runs on GitHub's included free
   minutes with no payment. *(User decision — not done here.)*

After either action, the workflow will run without any code change
(the two CI defects above are already fixed). Retrying CI before resolving
the account state is not justified.

---

## G. Operational state

- Dashboard: `python -m hermes_ebtto.dashboard` → http://127.0.0.1:8797/ (currently running)
- Live DB: v5, backed up; rollback path unchanged
- **Next restart of Hermes activates:** guidance↔task linkage and
  retrieval-event recording (both already verified functionally)
- Backup: `~/.hermes-ebtto/backups/ebtto-v3-pre-migration5-20261011T075733Z.db`

## H. Final verdict

**PARTIAL — observability core verified live; GitHub Actions blocked on an account billing lock**

Everything within reach is implemented, tested (133 + 41), lint- and
type-clean, packaged, and verified against the live restarted runtime. The
remaining gates are user actions (billing resolution or downgrade to Free;
gateway restart; authorized inference for the behavioral benchmark).
