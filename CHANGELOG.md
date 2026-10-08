# CHANGELOG

All notable changes to the EBTTO project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-10-08

### Added
- `register(ctx)` entry point in `src/hermes_ebtto/__init__.py`
- `register(ctx)` in `src/hermes_ebtto/plugins/__init__.py`
- Hermes plugin manifest (`plugin/plugin.yaml`) with `provides_hooks`
- `pre_tool_call` hook registration
- `post_tool_call` hook registration
- `on_session_end` hook registration
- `EBTTOStore` (SQLite, WAL) for trajectory storage
- `events.Task`, `events.ToolCall`, `events.Outcome` event schemas
- `classification.py` (18+ error classes)
- `retrieval.py` (task-family-scoped, weighted scoring)
- `scoring.py` (strategy scoring, confidence, evidence)
- `learning.py` (lesson extraction, strategy selection)
- `privacy.py` (secret redaction)
- `sqlite_production_hardening.py` (WAL, busy_timeout, foreign_keys)
- `cli.py` (13 CLI commands: status, stats, tools, tasks, patterns, strategies, failures, regressions, trajectory, benchmark, replay, export, prune, reset, mode, doctor)
- `observability.py` (MetricsPublisher for metrics)
- Package structure (`src/hermes_ebtto/`)
- Tests (`tests/unit/`, `tests/benchmark/`)
- GitHub Actions CI (`.github/workflows/`)
- `pyproject.toml` (build system, project metadata)
- CodeGraph initialization (`codegraph init`, 18 files, 322 nodes, 584 edges)

### Changed
- `src/hermes_ebtto/__init__.py` — `register(ctx)` added as module-level entry point
- `src/hermes_ebtto/plugins/__init__.py` — `register(ctx)` added as module-level entry point
- `plugin/plugin.yaml` — `provides_hooks` added

### Fixed
- `src/hermes_ebtto/plugins/__init__.py` — relative import (`from .. import config`)
- `src/hermes_ebtto/plugins/__init__.py` — added missing `_record_metrics` and `_start_recording` methods

## [Unreleased]

### Planned
- `docs/architecture/` — system design
- `docs/compatibility/` — Hermes integration contract
- `docs/configuration/` — modes, storage, privacy
- `docs/development/` — contribution guide
- `docs/operations/` — CLI reference, maintenance
- `docs/security/` — threat model, secret handling
- `docs/benchmarks/` — behavioral results, baseline vs EBTTO
- `docs/acceptance/` — forensic audit reports
- `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `ROADMAP.md`, `AUTHORS.md`, `Makefile`
