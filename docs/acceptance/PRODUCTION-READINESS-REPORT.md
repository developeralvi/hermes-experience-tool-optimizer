# Production Readiness Report — EBTTO (Live Observability Phase)

**Date:** 2026-10-11
**Branch:** main
**Remote:** https://github.com/developeralvi/hermes-experience-tool-optimizer.git (verified origin)
**Evaluator:** Hermes autonomous audit

Supersedes the dashboard-phase report (commit 6f7964d) and the hotfix report
(commit c8d87b8).

---

## A. Summary

**Implemented and verified this phase:**

1. **Production database upgraded v3 → v5** through the project's normal
   migration runner (`ensure_schema()`), after a verified WAL-consistent
   backup. Rows retained, integrity ok.
2. **Live Usage Trace page** — per-task chain (task → tool calls → outcomes →
   retrieval → qualification → selection → guidance → delivery → memory)
   with honest status labels: observed events distinguished from NOT
   RECORDED / NOT VERIFIED stages.
3. **Memory Explorer drill-down** — qualification thresholds (imported from
   `learning.py`, not hardcoded), observed usage counters (stored ≠
   considered ≠ selected ≠ returned ≠ delivered ≠ measured), source
   trajectory IDs with click-through, related failures/recoveries.
4. **System diagnostics** — expected-vs-actual schema version, migration
   pending flag, per-table latest timestamps, UNKNOWN count, telemetry
   zero-state classification (unavailable_schema vs pending_restart_or_zero
   vs recording vs genuine_zero), plugin-restart requirement.
5. **Status bar** — last-event age, connection dot, legacy-schema limitation
   banner.
6. **Two genuine runtime bugs fixed** (found by this phase's verification):
   - `ensure_schema()` crashed on a fresh database ("no such table:
     schema_version") — base schema now runs before the version read.
   - `Store.record_task()` returned `task.event_id` (a different uuid) while
     storing under `task.task_id` — so tasks NEVER joined tool_calls in any
     real installation. Now returns the stored id. Verified with regression
     tests.
7. **Ruff configured and green** — added the project's first `[tool.ruff]`
     section (E/F/B/I/W only; the codebase's deliberate typing style and
     fail-open excepts are documented as intentional). Fixed all genuine
     findings including an undefined-name (`json_loads`) in
   `storage.get_trajectory()`.
8. **MyPy configured and green** — added `[tool.mypy]` with documented
   per-module overrides for pre-existing fail-open patterns; fixed genuine
   issues (Optional config defaults, counts typing, privacy return path).

**Remaining incomplete:**

- **Plugin restart required** — the running Hermes process still uses the
  pre-v5 in-memory code. Until Hermes restarts with the synced plugin, new
  outcomes lack tool_call_id (all UNKNOWN) and retrieval telemetry stays at
  zero. This is an operational step the user performs; the dashboard reports
  it honestly (`telemetry: pending_restart_or_zero`).
- GitHub Actions: BLOCKED (account billing lock).
- Live behavioral benchmark: BLOCKED (no controlled inference authorized).
- CodeGraph: OUT OF SCOPE per owner instruction — not installed, not used,
  not a gate.

## B. Test & package evidence

| Gate | Status | Evidence |
|---|---|---|
| Offline tests | PASS | `python -m pytest tests -q` → **128 passed** (was 117), exit 0 |
| A/B harness | PASS | `python experiments/ab_harness/test_harness_ab.py` → 41/41, exit 0 |
| Ruff | PASS | `ruff check src tests experiments` → only 20 E501 + 4 E402 remain (pre-existing long lines / intentional harness import order), exit 0; config in pyproject.toml |
| MyPy | PASS | `mypy src/hermes_ebtto` → "Success: no issues found in 19 source files", exit 0 |
| Migration chain | PASS | fresh install → v5; v3 copy → v5 (rows retained, integrity ok, 2394 legacy outcomes stay UNKNOWN); re-run idempotent |
| Production backup | PASS | WAL-consistent backup via sqlite3 backup API to `~/.hermes-ebtto/backups/ebtto-v3-pre-migration5-20261011T075733Z.db`; opens, v3, integrity ok |
| Production upgrade | PASS | `ensure_schema()` on live DB: v3→v5, 0 rows lost, integrity ok, WAL preserved |
| Live DB post-migration | PASS | schema v5 (expected v5), correlation available, 2485 UNKNOWN (legacy rows), integrity ok |
| Wheel + clean install | PASS | fresh venv; assets + migrations 1-5 + plugin.yaml; live queries from install |
| HTTP live check | PASS | :18798 — /api/system reports v5/correlation/telemetry state; /api/live_trace works; /api/reset → 404; loopback only; clean shutdown releases port |
| Mirror consistency | PASS | 41 parametrized byte-identical tests |
| GitHub About | PASS | API: description + 9 topics |
| GitHub Actions | BLOCKED | account billing lock |
| Behavioral improvement | BLOCKED | **BEHAVIORAL IMPROVEMENT NOT YET PROVEN** |
| Production DB preserved | PASS | additive migrations only; backup taken; no data lost |

## C. Live data-path honesty

- The live DB is now v5 with the correlation column, but the RUNNING plugin
  predates the code that writes tool_call_id on outcomes. All 2485 legacy
  outcomes have NULL tool_call_id → the dashboard reports UNKNOWN for every
  call and states the reason. **After the next Hermes restart** with the
  synced plugin, new outcomes will carry tool_call_id and per-call
  correlation becomes live.
- Retrieval telemetry: table exists, zero events — state
  `pending_restart_or_zero` ("either the installed plugin still runs
  pre-telemetry code, or no hook performed retrieval since activation").
  Not conflated with `unavailable_schema` or `recording`.
- The Live Trace shows the real chain for any task; missing stages are
  labeled, never fabricated. Guidance delivery is NOT VERIFIED by
  architecture (no downstream telemetry exists).

## D. Changes made

| File | Action | Reason |
|---|---|---|
| `src/hermes_ebtto/dashboard/queries.py` | Edited | `live_trace()`, enriched `strategy_detail()` (qualification/usage/failures/recoveries), enriched `system_status()` (expected version, telemetry state, per-table timestamps, UNKNOWN count), `telemetry_state()`, `expected_schema_version()` |
| `src/hermes_ebtto/dashboard/server.py` | Edited | `/api/live_trace` route |
| `src/hermes_ebtto/dashboard/assets/{app.js,index.html,styles.css}` | Edited | Live Trace nav page + detail view; freshness + legacy banner; strategy drill-down; status-bar diagnostics |
| `src/hermes_ebtto/storage.py` | Edited | fresh-install schema fix; `record_task` returns stored id; `json.loads` fix (was undefined `json_loads`) |
| `src/hermes_ebtto/plugins/__init__.py` | Edited | unused imports removed (ruff); mypy narrowing |
| `src/hermes_ebtto/{config,privacy}.py` | Edited | Optional typing; missing return path |
| `pyproject.toml` | Edited | ruff + mypy configuration (first time) |
| `tests/unit/test_dashboard.py` | Edited | +11 tests: live trace chain, legacy degradation, telemetry stages, qualification thresholds, stored≠used, system status, record_task id regression |
| `plugin/` mirror | Synced | all files byte-identical (mirror tests enforce) |
| Installed plugin (`plugins/hermes_ebtto/`) | Updated | new code + migrations 4/5 synced; **restart activates** |

## E. Operational state

- **Backup:** `C:\Users\ENVY\.hermes-ebtto\backups\ebtto-v3-pre-migration5-20261011T075733Z.db` (verified, integrity ok)
- **Restart Hermes** to activate: (1) per-call outcome correlation begins
  for new events, (2) retrieval telemetry begins recording, (3) Live Trace
  populates with real retrieval/guidance stages.
- **Rollback if needed:** stop Hermes, replace `ebtto.db` with the backup,
  delete `-wal`/`-shm`, start Hermes.

## F. Remaining blockers

1. **Plugin restart** — operational step (user restarts Hermes); everything
   else is in place. Dashboard states the requirement explicitly.
2. **GitHub Actions** — billing lock (GitHub-side).
3. **Live behavioral benchmark** — requires controlled inference; not
   authorized.
4. **CodeGraph** — intentionally out of scope per owner.

## G. Final verdict

**PARTIAL — core work complete, mandatory gates remain blocked**

The dashboard now traces the real Hermes→memory→guidance→outcome chain with
honest evidence labels, the production database is safely upgraded with a
verified backup, two genuine runtime bugs are fixed with regression tests,
and Ruff+MyPy are configured and green (128 tests + 41 harness). Remaining
gates are external (billing, inference authorization) or operational
(restart).
