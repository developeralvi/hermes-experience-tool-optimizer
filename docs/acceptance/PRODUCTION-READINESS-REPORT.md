# Production Readiness Report — EBTTO (Dashboard Phase)

**Date:** 2026-10-10
**Branch:** main
**Remote:** https://github.com/developeralvi/hermes-experience-tool-optimizer.git (verified origin)
**Evaluator:** Hermes autonomous audit

Supersedes the 2026-10-11 hardening edition (commit 4c316c0).

---

## A. Summary

**Implemented (all verified by execution):**

1. **Read-only dashboard** (`src/hermes_ebtto/dashboard/`) — stdlib-only
   loopback HTTP server + JSON query layer + static single-page UI with 8
   pages: Overview, Tool Calls, Failures, Trajectories, Memory, Guidance,
   System. Launched via `python -m hermes_ebtto.dashboard [--port N]
   [--no-browser] [--db PATH]`.
2. **Retrieval/guidance telemetry** — additive `migrations/4.sql`
   (`retrieval_guidance_events` table) + fail-open plugin writes at both
   `pre_llm_call` and `pre_tool_call` retrieval points, so the dashboard can
   distinguish retrieval / qualification / guidance-returned stages that were
   previously unrecorded. Learning behavior unchanged.
3. **27 new dashboard tests** (`tests/unit/test_dashboard.py`) covering
   query correctness, reconciliation, pagination clamping, DB safety,
   security, and CLI.
4. **Packaging** — wheel now ships `dashboard/assets/*` + `plugin.yaml` +
   `migrations/4.sql`; verified clean-venv install + live API + clean
   shutdown.
5. **GitHub About** — description + 9 topics re-verified via `gh repo view`
   (they persist from the prior hardening session).

**Remaining incomplete:**

- GitHub Actions execution: BLOCKED (account billing lock — GitHub-side).
- ruff/mypy: NOT AVAILABLE locally (not installed).
- CodeGraph re-verification: NOT PERFORMED this session.
- Live behavioral benchmark: BLOCKED (no controlled A/B inference run).
- GitHub Release: NOT CREATED.

## B. Test & package evidence

| Gate | Status | Evidence |
|---|---|---|
| Offline tests | PASS | `python -m pytest tests -q` → **43 passed** (16 prior + 27 dashboard), exit 0 |
| A/B harness | PASS | `python experiments/ab_harness/test_harness_ab.py` → 41/41, exit 0 |
| Package build | PASS | `python -m build --sdist --wheel` — wheel contains dashboard/assets, plugin.yaml, migrations/1-4.sql |
| Clean-venv install | PASS | fresh venv install; `queries.open_ro()` resolved the LIVE production DB via `$HERMES_HOME` |
| Live HTTP API | PASS | server started on :18799; `/api/overview`, `/api/system`, `/api/tool_calls`, `/api/strategies`, `/api/guidance`, `/api/evaluations` all returned valid JSON from the live DB |
| Live data (read-only) | PASS | all-time: 2023 tool calls, 2019 succeeded (session-level), 4 failed; top tools terminal 838 / execute_code 489 / patch 202; 24 qualified strategies; integrity ok |
| Mutation endpoints | PASS | `/api/reset`, `/api/mode`, `/api/prune`, `/api/sql`, `/api/delete`, `/api/replay` → 404 (test + live curl) |
| Clean shutdown | PASS | SIGTERM → port released, server stopped |
| Read-only enforcement | PASS | test: writes raise `sqlite3.OperationalError`; `mode=ro` + `PRAGMA query_only` |
| No auto DB creation | PASS | test: missing DB → DashboardError, no file created |
| Loopback binding | PASS | test: non-loopback connect refused; live: netstat shows 127.0.0.1 only |
| XSS inertness | PASS | test: payload stored → JSON string; frontend has no `innerHTML` in code |
| Concurrency | PASS | test: writer thread + reader loop, no failures |
| GitHub Actions run | BLOCKED | account billing lock |
| ruff / mypy | NOT AVAILABLE | not installed locally |

## C. Live data-path honesty

- Success/failure counts are computed against the `outcomes` table via the
  session prefix embedded in both `turn_id` values (the pre-tool and
  post-tool hook writers assign **independent** task ids in production —
  verified directly against the live schema: `tc∩oc task_ids = 0`).
  `tool_calls.result_status` is 'PENDING' for every real row, so it is only
  a fallback.
- On the live DB the dashboard reports schema v3 and `guidance telemetry:
  False` — the pre-v4 truth. Migration 4 + telemetry writes take effect on
  the next Hermes restart with the updated plugin installed; the dashboard
  will then show retrieval events. Until then the Guidance page states the
  telemetry is unavailable rather than inventing rows.
- `retrieval_events` (the older table) remains 0 rows and is not used by
  the dashboard; the v4 table is the new telemetry path.
- Trajectory timelines show only persisted stages and list missing stages
  explicitly (pre/post task-id split means outcomes do not join by task_id
  in production — reported honestly).

## D. Changes made

| File | Action | Reason |
|---|---|---|
| `src/hermes_ebtto/dashboard/{__init__,__main__,queries,server}.py` | New | read-only query layer, loopback stdlib server, CLI entry |
| `src/hermes_ebtto/dashboard/assets/{index.html,app.js,styles.css}` | New | static UI, no build step, no external resources, textContent rendering |
| `src/hermes_ebtto/migrations/4.sql` (+ plugin mirror) | New | additive `retrieval_guidance_events` table + indexes |
| `src/hermes_ebtto/plugins/__init__.py` (+ plugin mirror) | Edited | fail-open `_record_retrieval_event()` called from both retrieval points |
| `tests/unit/test_dashboard.py` | New | 27 tests (queries, DB safety, security, HTTP, CLI) |
| `pyproject.toml` | Edited | package-data: dashboard assets + plugin.yaml |
| `README.md` | Edited | Dashboard section + repository tree update |
| `docs/development/DASHBOARD.md` | New | dashboard manual |
| `plugin/` mirror | Synced | keep plugin install tree in sync with src |

## E. Remaining blockers

1. **GitHub Actions billing lock** — jobs fail with "The job was not started
   because your account is locked due to a billing issue." Resolve billing,
   then re-run CI; the pipeline (from the prior hardening session) is
   correct and the dashboard tests will run inside `test` matrix.
2. **Live behavioral benchmark BLOCKED** — requires a controlled inference
   experiment; not authorized this session.
3. **ruff/mypy NOT AVAILABLE locally** — CI declares them.
4. **CodeGraph re-verification** — not performed this session.
5. **Guidance telemetry is dormant until the plugin restart** — the live
   plugin process still runs the pre-4.sql module; on next Hermes start with
   the synced plugin the `retrieval_guidance_events` rows begin accumulating
   and the Guidance page populates. This is an operational fact, not a code
   defect.

## F. Final verdict

**PARTIAL — core work complete, mandatory gates remain blocked**

The dashboard is implemented, tested (43/43), packaged, and verified against
the live production database read-only. The remaining open gates are
external (GitHub billing, live inference entitlement, local dev tools), not
code defects.
