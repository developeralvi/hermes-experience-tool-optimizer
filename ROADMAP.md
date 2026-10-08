# ROADMAP

EBTTO (Experience-Based Tool Trajectory Optimization) for Hermes Agent.

---

## Status Legend

| Label | Meaning |
|-------|---------|
| `done` | Implemented and verified |
| `active` | Under active development |
| `planned` | Scheduled for a future release |
| `blocked` | Waiting on external dependency or decision |

---

## Milestone: 0.1.0 — Core Implementation

**Status: COMPLETE**

- [x] Plugin entry point (`register(ctx)`) in `hermes_ebtto/__init__.py`
- [x] Plugin entry point (`register(ctx)`) in `hermes_ebtto/plugins/__init__.py`
- [x] Hermes plugin manifest (`plugin/plugin.yaml`) with `provides_hooks`
- [x] `pre_tool_call` hook registration
- [x] `post_tool_call` hook registration
- [x] `on_session_end` hook registration
- [x] `EBTTOStore` (SQLite, WAL) for trajectory storage
- [x] Event schemas (`Task`, `ToolCall`, `Outcome`)
- [x] Classification (18+ error classes)
- [x] Retrieval (task-family-scoped, weighted scoring)
- [x] Scoring (confidence, evidence thresholds)
- [x] Lesson extraction and strategy selection
- [x] Privacy (secret redaction)
- [x] SQLite production hardening (WAL, busy_timeout, foreign_keys)
- [x] CLI (13 commands)
- [x] Tests (`tests/unit/`, `tests/benchmark/`)
- [x] Package build (`pyproject.toml`)
- [x] CodeGraph initialization (18 files, 322 nodes, 584 edges)
- [x] GitHub Action CI workflows
- [x] Production documentation (README, LICENSE, SECURITY.md, CHANGELOG, etc.)
- [x] GitHub publication and fresh-clone verification

---

## Milestone: 0.2.0 — Live Behavioral Verification

**Status: PLANNED (blocked on external model auth)**

- [ ] Live-Hermes `pre_tool_call` event capture (safe deterministic tool)
- [ ] Live-Hermes `post_tool_call` event capture
- [ ] Live-Hermes DB write proof (`PRAGMA integrity_check` = ok)
- [ ] Multi-attempt trajectory (3 attempts through live Hermes)
- [ ] Learning loop: retrieval → guidance → behavior change
- [ ] Baseline-vs-EBTTO benchmark (20+ runs per mode)
- [ ] Smart retry: repeated failure → strategy change
- [ ] Regression detection: degraded strategy demoted

---

## Milestone: 0.3.0 — Production Hardening

- [ ] `tests/integration/` — real-Hermes integration tests
- [ ] `tests/contract/` — hook contract tests
- [ ] `tests/security/` — prompt injection, poisoning, path traversal
- [ ] `tests/regression/` — degraded strategy revalidation
- [ ] Multi-profile isolation support
- [ ] Failure isolation (EBTTO exception ≠ Hermes crash)
- [ ] `codegraph` forensic review (cycles, dead code, fan-in/out)
- [ ] Dashboard (optional, CLI must work without it)
