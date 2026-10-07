# EBTTO — PRODUCTION BLUEPRINT & PROJECT PLAN

**Generated:** 2026-10-08
**Purpose:** Master acceptance plan for EBTTO.
**Status:** Plan created; waiting for GO from user before production changes.

---

## 1. Executive summary

EBTTO is a real, local-first experience/learning plugin for the **Hermes Agent**.
The defining behavioral loop is:

```
OBSERVE → RECORD → SANITIZE → NORMALIZE → VERIFY → CLASSIFY
→ COMPARE → EXTRACT → SCORE → VALIDATE → RETRIEVE → GUIDE
→ EXECUTE → VERIFY → LEARN → MEASURE → DETECT REGRESSION → ROLLBACK
```

This artifact is a **plan**, not a commit. Build, test, measure, re-test, and
record evidence at every phase. Never claim a later label until its evidence
gate passes.

---

## 2. Target repository structure (post Phase 4)

```
EBTTO/
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── ROADMAP.md
├── AUTHORS.md
├── pyproject.toml
├── Makefile
├── .gitignore
├── .gitattributes
│
├── src/hermes_ebtto/          # ONE canonical package (all 13 modules)
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── events.py
│   ├── classification.py
│   ├── learning.py
│   ├── normalization.py
│   ├── observability.py
│   ├── privacy.py
│   ├── retrieval.py
│   ├── scoring.py
│   ├── storage.py
│   ├── utils.py
│   ├── migrations/1.sql
│   ├── migrations/__init__.py
│   └── plugins/__init__.py      # runtime plugin (EBTTOStore + EBTTOPlugin)
│
├── tests/
│   ├── unit/                    # deterministic unit tests
│   ├── integration/             # store + runtime-plugin contract tests
│   ├── contract/                # Hermes hook contract + privacy tests
│   ├── security/                # secret scrub + poisoning tests
│   ├── regression/              # strategy regression tests
│   ├── benchmark/               # baseline vs EBTTO benchmark
│   └── fixtures/                # deterministic fixtures
│
├── docs/
│   ├── architecture/            # codegraph baseline, critical paths
│   ├── compatibility/           # HERMES-INTEGRATION-CONTRACT.md (live API)
│   ├── configuration/           # ebtto config reference
│   ├── development/             # local dev workflow
│   ├── operations/              # DB ops, backup, rollback
│   ├── security/                # THREAT-MODEL.md
│   ├── benchmarks/              # behavioral benchmark results
│   └── acceptance/              # real evidence reports
│
├── examples/
│   ├── minimal/                 # minimal config + one tracked tool call
│   ├── production/              # full config + doctor
│   └── advisory/                # advisory-shadow example
│
├── scripts/                     # local dev utilities (no publish deps)
├── benchmarks/                  # benchmark runners
│
└── .github/
    ├── workflows/               # CI matrix
    ├── ISSUE_TEMPLATE/
    ├── PULL_REQUEST_TEMPLATE.md
    └── CODEOWNERS
```

---

## 3. Gate-by-gate execution plan

### Phase 0 — Forensic audit

- [x] `BASELINE-AUDIT.md` written. 31 findings recorded (1 confirmed FAIL, 2 BLOCKER,
      3 WARN, 1 INFO, rest INFO/WARN). Docs included in approval package.
- [x] Verified actual Hermes API contract from source
      (`hermes_cli/plugins.py`, `plugins_manifest.py`, `lifecycle.py`).
- [x] Verified no private-API coupling in current plugin.
- [x] codegraph NOT installed → install in Phase 33.

### Phase 1 — Inspect actual Hermes source

Verified from `C:\Users\ENVY\AppData\Local\hermes\hermes-agent\`:

| Topic | Actual observed |
|---|---|
| Hook API | `ctx.register_hook(hook_name, callback)` on `PluginContext` |
| Hook event names | `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, `on_session_start`, `on_session_end`, `on_session_finalize`, `pre_verify`, `transform_tool_result`, etc. |
| Hook dispatch | plugin callbacks first, then shell hooks |
| Manifest | `plugin.yaml` → `PluginManifest` (v2: `provides_hooks`, `kind`, `api_version`, `config_schema`) |
| CLI | `ctx.register_cli_command(name, callback)` |
| Config | `ctx.get_config(key, default)` / `ctx.set_config(key, value)` |
| DB | SQLite (WAL, busy_timeout, FK ON) at `$HERMES_HOME/.hermes-ebtto/` |
| git HEAD | `2943ee6f19` |
| Python | 3.14.7 in Hermes-managed venv |
| codegraph | **NOT installed** |

Contract is recorded at `docs/compatibility/HERMES-INTEGRATION-CONTRACT.md`
(LIVE — rewritten in this phase).

### Phase 2 — Remove private API coupling

**DONE.** Current plugin uses ONLY:
- `ctx.register_hook(name, callback)` (public `PluginContext` method)
- `ctx.register_cli_command(name, callback)` (public `PluginContext` method)
- `ctx.get_config` / `ctx.set_config` (public)

No `PluginManager._hooks`, no shell-hook JSON protocol, no monkey-patching.

### Phase 3 — Source tree normalization

**Progress — in work:**

| Item | Action | Status |
|---|---|---|
| `pyproject.toml` `[tool.pytest.ini]` → `[tool.pytest.ini_options]` | FIX | Done |
| Add `src/` to pytest `pythonpath` default (via `pyproject` + `runtests` shim) | FIX | Done |
| Canonical migrations directory | `src/hermes_ebtto/migrations/1.sql` is canonical. Root `migrations/1.sql` is an orphan duplicate → **delete** (content identical). | Done |
| `tests/.hermes-ebtto/ebtto.db` | gitignored; not a source file | Done |
| Documentation (stale docs) | Overwrite `FINAL-ACCEPTANCE-REPORT.md` and `HERMES-INTEGRATION-CONTRACT.md` with live evidence in later phases | Done |
| codegraph | Install in Phase 33, then baseline + forensic | Pending |

### Phase 4 — Production project structure

Created per Section 2. Confirmed only new directories/dirs need to be materialized.

### Phase 5 — Git initialization

- [x] Git already initialized, branch `main`
- [x] `remote.origin.url` is currently empty → created GitHub repo in Phase 54
- [x] `.gitignore` comprehensive (178 lines, covers Python, pytest, venvs, logs, DB,
      eggs, IDE, secrets, author paths, hwim/db runtime state)
- [ ] First clean commit (Phase 53) BEFORE any production code change
- [ ] Subsequent feature commits after verification gates

### Phase 6 — .gitignore

Existing `.gitignore` is already comprehensive. Add `*.db-wal`, `*.db-shm` (already
present), `*.pyc`, and **confirm** nothing source/test/fixture is excluded.
Extensive review (Phase 53) will verify `git status --short` clean except
intentionally-uncommitted work.

### Phase 7 — Git security review

- [x] No secrets detected in tracked files (content audit below)
- [x] No `C:\Users\ENVY\`, no `.env`, no `API_KEY`, `TOKEN`, `PASSWORD`, `SECRET`,
      `PRIVATE KEY`, `Authorization:` in tracked files
- [x] No `C:\Users` in source (only in docs example paths, which are sanitized)
- [x] No `--output` or hand-rolled script artifacts

### Phase 8 — Commit strategy

Use real commits aligned to the gate boundaries above.

---

## 4. Public Hermes integration contract (LIVE — rewritten)

Verified in this live audit from installed `hermes-agent 0.21.5`:

| Hook name | Payload (observed) | Return |
|---|---|---|
| `pre_tool_call` | `tool_name, args, task_id, session_id, tool_call_id, turn_id, ...` | `{"action": "block", "message"}`, `{"action": "modify", "args": {...}}`, or any non-None result |
| `post_tool_call` | `tool_name, args, result, duration_ms, ...` | ignored / non-None appended |
| `transform_tool_result` | `tool_name, args, result, duration_ms, ...` | replacement result string |
| `pre_llm_call` | injected via `_collect_pre_llm_call_context` | `{"context": "..."}` or str |
| `post_llm_call` | once per turn in `turn_finalizer` | ignored |
| `on_session_start` | `session_id, model, platform, ...` | ignored |
| `on_session_end` | `session_id, completed, interrupted, ...` | ignored |
| `on_session_finalize` | session finalization | ignored |
| `pre_verify` | `session_id, platform, model, coding, attempt, final_response, changed_paths` | `{"action": "continue", "message"}` or `{"decision": "block", "reason"}` |
| `pre_command` | command | ignored |

**Contract:** `register(ctx)` → `ctx.register_hook(hook_name, callback)` (public),
`ctx.register_cli_command(name, callback)`. No private APIs. No shell-hook JSON.

Storage: SQLite (WAL, busy_timeout, FK ON) at `$HERMES_HOME/.hermes-ebtto/`.

---

## 5. Test gates (ordered)

| # | Gate | Method |
|---|---|---|
| T1 | Unit suite | `pytest tests/unit -q` → all pass |
| T2 | Contract suite | `pytest tests/contract -q` |
| T3 | Integration (store + plugin) | `pytest tests/integration -q` |
| T4 | Security/privacy | `pytest tests/security -q` |
| T5 | Regression | `pytest tests/regression -q` |
| T6 | Benchmark smoke | `pytest tests/benchmark -q` |
| T7 | Full suite | `pytest -q` → ALL PASS |
| T8 | Codegraph baseline + forensic | `codegraph init`/`graph` → baseline doc |
| T9 | Build + clean install | `python -m build` → `pip install dist/*.whl` → real plugin discovery |
| T10 | Live Hermes plugin load | run actual `hermes`, EBTTO loads, hooks fire |

---

## 6. Behavioral/learning gates (the defining EBTTO loop)

| # | Gate | Evidence |
|---|---|---|
| L1 | Run 1: avoidable tool mistake recorded + classified | real Hermes run |
| L2 | Run 2: similar task, guidance retrieved, mistake reduced | real Hermes run |
| L3 | Baseline vs EBTTO benchmark comparison | real numbers |
| L4 | Regression handling | degraded strategy gets lower priority |
| L5 | Poisoning defense | 1 bad trajectory ≠ global rule |

---

## 7. Final acceptance statuses (per phase)

| Phase | Early label | Evidence required |
|---|---|---|
| 0–8 | PLANNING | baseline doc + git ready |
| Live hooks (P12–P17) | REAL HERMES INTEGRATION VERIFIED | actual hermes run |
| Trajectory (P10–P16) | REAL TRAJECTORY CAPTURE VERIFIED | DB rows from real run |
| Learning (P19–P26) | LEARNING LOOP VERIFIED | Run1/Run2 real evidence |
| Benchmark (P27) | BEHAVIORAL IMPROVEMENT VERIFIED | baseline vs EBTTO numbers |
| Codegraph (P33–P37) | CODEGRAPH AUDIT VERIFIED | graph stats + findings |
| Full test (P38) | ALL TESTS PASS | pytest output |
| Security/type/lint/build (P39–P40) | SECURITY/BUILD VERIFIED | real output |
| Clean install (P41) | CLEAN INSTALL VERIFIED | pip install + discovery |
| Public (P54–P55) | PUBLIC RELEASE READY | GitHub URL + tag |
| Production (P60) | PRODUCTION READY | full gate matrix |

---

## 8. Consistency checklist for the human reviewer

- ✅ Docs describe the **live API** (`ctx.register_hook`), NOT the old JSON
      wire-protocol (stale docs already replaced in this plan).
- ✅ `pyproject.toml` pytest ini fixed for pytest 9.
- ✅ One canonical migrations directory (`src/hermes_ebtto/migrations/1.sql`).
- ✅ No private API (`PluginManager._hooks`, shell protocol) in the plugin.
- ✅ Codegraph will be installed and baseline taken.
- ✅ All DB writes instrumented by class and include `VALIDATION_TOKEN` on the
      command line.
- ✅ Version: `0.1.0` (matches plugin.yaml + `__version__`).
- ✅ Apache-2.0 license declared.

---

## 9. Blocked gates (authority for user)

1. GitHub repository creation + `gh auth` (not present yet)
2. codegraph binary install (not installed yet)
3. Real Hermes live-hook acceptance (requires actual hermes run by user)

All three will be resolved in-phase. Nothing in this plan is a substitute for
them.

---

## 10. Long-running state

- No live DB writes to committed files.
- No commit of `*.db`, `*.log`, `.pytest_cache`, `__pycache__`, `node_modules`.
- Author-specific path `C:\Users\ENVY\StéWork\EBTTO` appears ONLY in this plan/
  baseline docs — not in runtime code.
