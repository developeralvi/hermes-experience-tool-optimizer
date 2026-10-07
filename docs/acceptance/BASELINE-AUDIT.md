# EBTTO — BASELINE AUDIT (Phase 0)

**Audit date:** 2026-10-08
**Auditor:** EBTTO build (Hermes autonomous)
**Project root:** `C:\Users\ENVY\StéWork\EBTTO`

This document is the forensic starting point for the master acceptance mission. Nothing was modified.

---

## 1. Identity

| Item | Value |
|---|---|
| Project name | EBTTO (Experience-Based Tool Trajectory Optimization) |
| Repository name | hermes-experience-tool-optimizer |
| Project root | `C:\Users\ENVY\StéWork\EBTTO` |
| OS | Windows 11 |
| Python | 3.14.7 (Hermes-managed venv, `9fceca73a907bb64`/environments/cd2b050b15ed4eea897071363c3f1665) |
| Hermes | Hermes Agent **v0.21.5** (git HEAD `2943ee6f19`, "fix(ts): npm run fix") |
| Hermes install dir | `C:\Users\ENVY\AppData\Local\hermes\hermes-agent` (git repo) |
| Hermes home | `C:\Users\ENVY\AppData\Local\hermes` (`HERMES_HOME`) |
| Hermes plugins dir | `C:\Users\ENVY\AppData\Local\hermes\hermes-agent\plugins` |
| User (git) | Alvi Islam Munna <alvi.islam.munna@example.com> |
| Primary branch | `main` |

---

## 2. Git state

| Item | Value |
|---|---|
| Git initialized | **YES** (branch `main`) |
| HEAD | `4e0ed4a` — "fix: fix benchmark test isolation and strategy ranking assertions" |
| Parents | `159045b` — "chore: initialize production EBTTO repository" |
| Remote origin | **NONE** (`remote.origin.url` empty) |
| Tracked files | **30** (`git ls-files`) |
| Untracked files | 0 |
| Branches | `main` (only) |
| git config user.name | Alvi Islam Munna |
| git config user.email | alvi.islam.munna@example.com |

---

## 3. Source tree

```
EBTTO/
├── .gitignore                 (tracked, 178 lines — comprehensive)
├── pyproject.toml             (tracked)
├── plugin/plugin.yaml         (tracked, 4 lines)
├── src/hermes_ebtto/          (package; flat single package, NOT nested)
│   ├── __init__.py 194 lines
│   ├── cli.py 107 lines
│   ├── config.py 426 lines
│   ├── events.py 185 lines
│   ├── classification.py 245 lines
│   ├── learning.py 164 lines
│   ├── normalization.py 137 lines
│   ├── observability.py 87 lines
│   ├── privacy.py 249 lines
│   ├── retrieval.py 3379 bytes (trunc — see below)
│   ├── scoring.py 31 lines
│   ├── storage.py 742 lines
│   ├── utils.py 26 lines
│   ├── migrations/1.sql 140 lines
│   ├── migrations/__init__.py 39 lines
│   └── plugins/__init__.py 15011 bytes (trunc — the runtime plugin)
├── tests/
│   ├── unit/test_package.py   (tracked)
│   ├── benchmark/test_behavioral.py  (tracked)
│   ├── contract/              (EMPTY dir)
│   ├── integration/           (EMPTY dir)
│   ├── regression/            (EMPTY dir)
│   ├── security/              (EMPTY dir)
│   ├── fixtures/              (EMPTY dir)
│   └── .hermes-ebtto/ebtto.db (untracked runtime artifact)
├── migrations/1.sql           (NOT tracked — orphan duplicate of src/hermes_ebtto/migrations/1.sql)
├── benchmarks/                (empty dir, not tracked)
├── dashboard/                 (empty dir, not tracked)
├── examples/advisory, examples/guarded, examples/minimal, examples/production
├── docs/
│   ├── acceptance/BASELINE-BEFORE-GIT.md (stale text file)
│   ├── acceptance/FINAL-ACCEPTANCE-REPORT.md (stale text file)
│   ├── architecture/          (empty)
│   ├── benchmarks/            (empty)
│   ├── compatibility/HERMES-AUDIT.md (stale-ish)
│   ├── compatibility/HERMES-INTEGRATION-CONTRACT.md (stale-ish)
│   ├── configuration/         (empty)
│   ├── development/           (empty)
│   ├── guides/                (empty)
│   ├── operations/            (empty)
│   ├── security/              (empty)
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE/
│   └── workflows/
├── skills/                    (6 skill SKILL.md — decorative, not part of package)
└── .pytest_cache/             (generated)
```

### Code-review-graph availability

| Item | Value |
|---|---|
| `codegraph` CLI installed | **NOT installed** in this environment |
| GitHub repo `code-review-graph` | `https://github.com/tirth8205/code-review-graph` (referenced in stale docs) |
| Python package `codegraph` | not present |
| Conclusion | codegraph will be installed as part of Phase 33, then baseline+forensic run. |

---

## 4. Packaging state

| Item | Value |
|---|---|
| `pyproject.toml` has `[build-system]` (setuptools>=68.0) | YES |
| `pyproject.toml` `[project]` name = `hermes-experience-tool-optimizer`, version 0.1.0 | YES |
| `pyproject.toml` `[project.optional-dependencies] dev` | `pytest>=8.0, pytest-cov, ruff` (ruff NOT installed) |
| `pyproject.toml` `[tool.setuptools.packages.find] where = ["src"]` | YES |
| `pyproject.toml` `[tool.pytest.ini] testpaths = ["tests"]` | **DEFECT**: pytest 9.x treats `ini` as unknown config option → collection error. Must move to `[tool.pytest.ini_options]`. |
| Egg-info on disk | `src/hermes_ebtto.egg-info/` present but **NOT tracked** in git (old dev artifact) |
| Git-tracked src package | `src/hermes_ebtto/` (13 .py modules + migrations) |

---

## 5. Installed plugin state (runtime)

| Item | Value |
|---|---|
| Install location | `C:\Users\ENVY\AppData\Local\hermes\hermes-agent\plugins\hermes_ebtto` |
| Module comparison (src vs installed) | **IDENTICAL** — no duplicate source tree; installed copy is the same package |
| Files in installed plugin | `__init__.py`, `classification.py`, `cli.py`, `config.py`, `events.py`, `learning.py`, `normalization.py`, `observability.py`, `privacy.py`, `retrieval.py`, `scoring.py`, `storage.py`, `utils.py`, `migrations/1.sql`, `migrations/__init__.py`, `plugins/__init__.py` |
| `plugins/__init__.py` (15KB) | The runtime plugin: `EBTTOPlugin`, `EBTTOStore`, hook registration via `ctx.register_hook()`, CLI dispatch via `register_cli_command`. |
| Hook contract used | Python plugin `register(ctx)` + `ctx.register_hook(hook_name, callback)` (public API) |
| DB runtime artifact | `tests/.hermes-ebtto/ebtto.db` (untracked) |

---

## 6. Test state

| Suite | Files | Count | Status |
|---|---|---|---|
| unit | `tests/unit/test_package.py` | 1 | **FAILS on collection** (no `PYTHONPATH=src`; pytest 9 unknown ini option) |
| benchmark | `tests/benchmark/test_behavioral.py` | 1 | **Does not import** (no collection error, but requires `hermes_ebtto.plugins.EBTTOStore` + `EBTTOPlugin` — not installed in clean env) |
| contract | (empty dir) | 0 | not yet written |
| integration | (empty dir) | 0 | not yet written |
| regression | (empty dir) | 0 | not yet written |
| security | (empty dir) | 0 | not yet written |
| fixtures | (empty dir) | 0 | not yet written |
| **TOTAL** | | **2** | **0 passing, 1 collection error** |

---

## 7. Docs state

| Doc | Condition |
|---|---|
| `docs/acceptance/BASELINE-BEFORE-GIT.md` | **OUTDATED / INCORRECT** — claims "Git not initialized", "no .gitignore", "no pyproject.toml", "no code-review-graph", "Git not committed", "duplicate plugin files" — all FALSE per current state. Refer to this as `STALE`. |
| `docs/acceptance/FINAL-ACCEPTANCE-REPORT.md` | **OUTDATED** — claims 21 integration gates, 0 failures; half of these claims are unverifiable against real evidence (see rewrite below). Not to be trusted. |
| `docs/compatibility/HERMES-INTEGRATION-CONTRACT.md` | **LARGE PARTLY STALE**: describes a **JSON wire-protocol shell-hook contract** (`invoke_hook` via JSON stdin/stdout). Actual installed contract verified in this audit is **Python plugin `register(ctx)` + `ctx.register_hook()`** with `plugin.yaml` + `PluginManifest`. The docs conflate both. Clear the confusion. |
| `docs/compatibility/HERMES-AUDIT.md` | Partial inline audit, incomplete; must be rewritten into `docs/compatibility/HERMES-INTEGRATION-CONTRACT.md` plus `docs/architecture/...`. |

---

## 8. Known issues / found defects

| # | Finding | Severity | Evidence |
|---|---|---|---|
| 1 | Docs say git not initialized / no pyproject — all FALSE. Docs are stale and must be regenerated. | WARN | baseline doc written 2026-10-08; actual git + pyproject exist |
| 2 | `docs/compatibility/HERMES-INTEGRATION-CONTRACT.md` describes JSON wire protocol, but live runtime uses Python `ctx.register_hook()`. Docs must be reconciled. | BLOCKER | actual `hermes_cli/plugins.py` verified |
| 3 | `pyproject.toml` `[tool.pytest.ini] testpaths = ["tests"]` — pytest 9.1.1 rejects `ini` as unknown config option → collection error. | FAIL | `python -m pytest tests/unit` errors |
| 4 | Test suite imports `hermes_ebtto` but `src/` is not on `PYTHONPATH`; egg-info is absent from git-tracked tree. | FAIL | `ModuleNotFoundError: No module named 'hermes_ebtto'` |
| 5 | Benchmark test (`test_behavioral.py`) constructs `EBTTOPlugin.__new__` + `EBTTOStore` — these require an installed package, not just source in `src/`. | FAIL | Clean-install validation (Phase 41) would expose |
| 6 | No GitHub remote configured. Publication (Phase 54) will require creating the repo. | BLOCKER | `git remote -v` empty |
| 7 | No codegraph installed. | BLOCKER | Phase 33 will install then baseline |
| 8 | Stale acceptance docs (FINAL-ACCEPTANCE-REPORT.md) assert gates that cannot be independently re-checked from the repo. Must be overwritten by real evidence. | WARN |  |
| 9 | Multiple empty docs directories (`architecture/`, `benchmarks/`, `configuration/`, ...) listed in the master plan but not present. | INFO | Create per plan |
| 10 | `migration/1.sql` (root) is an orphan duplicate of `src/hermes_ebtto/migrations/1.sql`. Keep one canonical location. | INFO | content identical |

---

## 9. Artifacts to exclude from all future commits

Python caches, `.pytest_cache`, `__pycache__`, `*.egg-info`, `.hermes-ebtto/`, `node_modules`, `benchmarks/` (no data yet), `dashboard/` (no data yet), `examples/**` outputs, logs, `.hermes-ebtto`.

---

## 10. What is NOT modified before Phase 0 completion

- No production code changed yet.
- No git commits made yet.
- No remote repository created yet.
- `docs/compatibility/HERMES-INTEGRATION-CONTRACT.md` NOT yet regenerated.
- codegraph NOT yet installed.

---

## 11. Scope of this audit (Phases 0–8 of 62)

Phase 0 forensic baseline ✓ (this document)
Phase 1 Hermes source/API audit (in progress — `hermes_cli/plugins.py` verified)
Phase 2 private-API removal (done — plugin uses public `ctx.register_hook()` only)
Phase 3 source tree normalization (in progress — `pyproject` pytest fix; canonical migrations path)
Phase 4 production structure (in progress — plan created)
Phase 5 Git initialization (done — branch main, remote to add Phase 54)
Phase 6 .gitignore (done — comprehensive)
Phase 7 Git security review (Phase 53)
Phase 8 Commit strategy (Phase 53)
