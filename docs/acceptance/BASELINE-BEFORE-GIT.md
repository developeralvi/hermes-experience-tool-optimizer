# EBTTO BASELINE BEFORE GIT

**Generated:** 2026-10-08  
**Project root:** `C:\Users\ENVY\StéWork\EBTTO`  
**Documentation:** `docs/acceptance/BASELINE-BEFORE-GIT.md`

---

## 1. Project Root

```
C:\Users\ENVY\StéWork\EBTTO
```

## 2. Source Tree

```
C:\Users\ENVY\StéWork\EBTTO\src\hermes_ebtto
```

**Source modules:** 16 Python files

## 3. Test Count

- Unit tests: 11 (`tests/unit/test_package.py`)
- Benchmark tests: 7 (`tests/benchmark/test_behavioral.py`)
- **Total test files:** 2 Python test files

## 4. Current Status

- EBTTO version: 0.1.0
- Package structure: Flat `src/hermes_ebtto/`
- Files: 15 Python modules + migrations + docs

## 5. Hermes Version

- Hermes: 0.21.5 (git HEAD 2943ee6f19)
- Hermes path: `C:\Users\ENVY\AppData\Local\hermes\hermes-agent`
- Hermes exists: ✓

## 6. Python Version

```
3.14.7 (main, Sep  1 2026, 14:17:30) [MSC v.1944 64 bit (AMD64)]
```

## 7. code-review-graph Availability

- Review-changes skill: `✓`
- Review-delta skill: `✓`
- GitHub: https://github.com/tirth8205/code-review-graph

## 8. Known Warnings

(To be recorded during Phase 0-3 audit)

## 9. Known Failures

(Benchmark tests: 3 failed / 4 passed / 1 error from prior runs)

## 10. Generated Artifacts

- `*.egg-info/` — Python package metadata
- `.pytest_cache/` — pytest cache
- `__pycache__/` — Python bytecode cache
- `test_hermes_home/` — test storage directory
- `test_plugin_data/` — plugin test data

## 11. Git State

- Git: Initialized
- Branch: main
- Untracked files: 0

## 12. Key Issues from Baseline

1. **Git not initialized** — repo not under version control
2. **No .gitignore** — project has no professional ignore file
3. **No pyproject.toml** — project has no packaging configuration
4. **Duplicate plugin files** — `plugins/` directory exists in multiple places
5. **Storage.py has stale thread-local connection** — `_local = threading.local()` still present
6. **Benchmark test has syntax errors** — `test_behavioral.py` has 3 failing tests
7. **No git history** — repository not yet committed
8. **No code-review-graph initialized** — graph not yet built for the repo

---

*END OF BASELINE — 2026-10-08*
