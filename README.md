# EBTTO

**Experience-Based Tool Trajectory Optimization** for Hermes Agent.

[![CI](https://github.com/developeralvi/hermes-experience-tool-optimizer/actions/workflow/ci.yml/badge.svg)](https://github.com/developeralvi/hermes-experience-tool-optimizer/actions/workflows/ci.yml)

EBTTO makes agent tool-use observable, auditable, and improvable through real
execution evidence. It hooks the actual Hermes runtime — `pre_tool_call`,
`post_tool_call`, `pre_llm_call`, and `on_session_end` — to capture
trajectories, learn from failures, and inject compact guidance into future
turns **before** the model selects a tool.

---

## What is EBTTO?

EBTTO stands for **Experience-Based Tool Trajectory Optimization**.

It is a real-Hermes plugin that runs inside the Hermes Agent process and
observes every tool lifecycle event. It does **not** replace the model, and it
does **not** execute historical trajectories as code.

What it actually does:

1. **Observe** — `pre_tool_call` / `post_tool_call` fire for every tool the
   model attempts.
2. **Record** — each tool call, result, error, and duration is written to a
   local SQLite trajectory store (WAL mode, foreign keys on).
3. **Classify** — failures are classified into 18+ categories (wrong tool,
   wrong args, wrong order, tool-loop crash, etc.).
4. **Learn** — repeated failure patterns extract reusable strategies with
   confidence, evidence counts, and scope.
5. **Guide** — a *compact, intentional* guidance block is injected into
   `pre_llm_call`, before the tool-calling loop starts.
6. **Verify** — the improvement is measured against a baseline on repeated
   task-family runs.

## What it does NOT learn

EBTTO learns from observed tool-use trajectories only. It does **not**:

- learn arbitrary knowledge not grounded in a tool outcome
- execute stored historical trajectories as code
- modify the model, its prompts, or its system instructions
- change model/provider routes
- access your files, apps, or external systems beyond the tools you already use

It is an advisory optimization layer on top of normal tool execution.

## Core product loop

**RUN 1** — The model makes an avoidable tool-use mistake.

```
real Hermes → real model → tool decision → avoidable mistake
→ actual tool result → verified failure/recovery
→ trajectory captured → pattern extracted → successful strategy learned
```

**RUN 2** — The same family of task returns.

```
similar real Hermes task
→ relevant experience retrieved
→ experience reaches Hermes BEFORE the tool-selection decision (pre_llm_call)
→ Hermes uses improved strategy
→ fewer avoidable mistakes / retries / tool calls
→ independently verified success
```

This loop is the defining feature of EBTTO. Without measurable Run-1 → Run-2
behavior change, the project is explicitly **NOT** behaviorally verified.

## Repository contents

```
EBTTO/
├── plugin/                      # Hermes plugin manifest
│   └── plugin.yaml
├── src/hermes_ebtto/            # Production source package
│   ├── __init__.py              # register(cx) entry point
│   ├── plugins/__init__.py      # EBTTOPlugin + hook registration
│   ├── config.py                # Modes, storage, privacy policies
│   ├── storage.py               # SQLite WAL trajectory store
│   ├── events.py                # Event / trajectory schemas
│   ├── classification.py        # Failure classifier (18+ classes)
│   ├── retrieval.py             # Experience retrieval
│   ├── scoring.py               # Strategy scoring
│   ├── learning.py              # Lesson extraction & strategy selection
│   ├── privacy.py               # Secret redaction
│   ├── normalization.py         # Task fingerprinting
│   ├── observability.py         # Metrics publisher
│   ├── cli.py                   # 13 CLI commands
│   ├── dashboard/               # Read-only web dashboard
│   │   ├── queries.py           #   read-only query layer
│   │   ├── server.py            #   loopback HTTP server (stdlib)
│   │   └── assets/              #   static UI (no build step)
│   └── migrations/              # SQLite schema + migrations 1-4
├── tests/
│   ├── unit/                    # unit + package + dashboard tests
│   └── benchmark/               # baseline vs EBTTO behavioral tests
├── docs/
│   ├── compatibility/           # Hermes runtime contract
│   ├── configuration/           # Modes, storage, privacy
│   ├── development/             # Dashboard manual
│   ├── security/                # Threat model
│   └── acceptance/              # Forensic audit reports
├── .github/workflows/           # CI (test matrix, lint, typecheck, package)
├── .gitignore
├── pyproject.toml               # Build system & project metadata
└── Makefile                     # Common commands
```

## Installation

See the [Installation](#installation) section below, or `docs/` for the
compatibility and configuration references.

```bash
# 1. Install the package
pip install -e ".[dev]"

# 2. Enable the plugin in your Hermes
hermes plugins enable hermes-ebtto
```

The plugin is a standard Hermes plugin: `plugin.yaml` declares
`main: hermes_ebtto.plugins` and the module-level `register(ctx)`.

## Hermes compatibility

- **Hermes Agent**: 0.21.5+
- **Python**: 3.11, 3.12, 3.13
- **License**: Apache-2.0

Full compatibility contract and lifecycle detail:
[docs/compatibility/HERMES-INTEGRATION-CONTRACT.md](docs/compatibility/HERMES-INTEGRATION-CONTRACT.md)

## Provider requirements

EBTTO's behavioral claims require a **tool-capable, working Hermes provider**
for live runtime tests. This is a hard requirement of the behavioral loop,
not an optional extra:

| Priority | Provider type |
|----------|--------------|
| 1 | Provider already working in your environment |
| 2 | Local Ollama / tool-capable model |
| 3 | Another already-configured provider |
| 4 | External provider only if valid credentials exist |

The provider in this environment's Hermes config is a working tool-capable
route; the behavioral acceptance gates require it to stay available. If the
configured provider returns 401 (or otherwise cannot execute tools), live
behavioral tests cannot run and the gates remain BLOCKED.

Live runtime evidence (agent.log, this host, 2026-10-11): plugin registered
`mode=shadow`, `pre_llm_call` guidance injected 4 times, `[EBTTO SHADOW]
Guidance` logged 126 times, and 560 pattern-persistence events recorded for
tools `terminal`, `execute_code`, `patch`, `read_file`, `skill_view`, and
`skill_manage`. These prove the recording → learning → retrieval loop fires
in a live Hermes process; they do not prove a measured behavioral
improvement (see Known limitations).

## Modes

EBTTO modes control what the plugin does at two distinct hook stages. These
stages are **not** interchangeable:

- **Pre-selection guidance** (`pre_llm_call`) — content handed to the model
  *before it chooses a tool*. It is appended to the user message (never the
  system prompt).
- **Post-selection observation** (`pre_tool_call`) — what happens *around a tool
  the model has already chosen*. It can log, return a directive, or do nothing.

A mode can be passive at one stage and active at the other. `shadow` is exactly
that case — see below.

| Mode | `pre_llm_call` behavior | `pre_tool_call` behavior | Verified effect |
|------|-------------------------|--------------------------|-----------------|
| `record_only` (default) | Returns `None` immediately. No retrieval, no injection. | Records the tool call, then returns `None`. No guidance retrieved, nothing logged, nothing blocked. | Observes and records only. Cannot influence tool choice. |
| `shadow` | Retrieves applicable guidance and **returns it as `{"context": ...}`**, which Hermes appends to the user message before tool selection. | Records the call, retrieves guidance, and **logs it** (`[EBTTO SHADOW] Guidance: ...`). **Returns `None`** — the tool call is never modified or blocked. | **Mixed.** May influence tool *selection* via the prompt; never changes or blocks the tool *call* itself. |
| `advisory` | Same retrieval and injection as `shadow`. | Returns the strategy's `directive` dict (`{"action": "continue", ...}`) so the runtime receives it, without blocking. | May influence selection and surfaces a directive, but does not modify or block. |
| `guarded` | Same retrieval and injection as `shadow`. | Logs and returns `{"action": "continue", "requires_approval": True, "guidance": ...}`. | Can require approval before execution. |
| `controlled_auto` | Same retrieval and injection as `shadow`. | Calls `_apply_strategy_to_args()` and returns the result, which may rewrite the tool arguments. | Can modify the tool call's arguments. |
| `off` | Returns `None`. | Returns `None` before any recording. | Plugin inert. |

Key points:

- **The effective default is `record_only`, not `advisory`.** Mode resolves as
  `EBTTO_MODE` env var → `plugins.entries.hermes-ebtto.settings.mode` →
  `config.DEFAULT_MODE` (`record_only`), so a fresh install never injects.
  `DEFAULT_MODE` is the single constant both `config.py` and `register(ctx)`
  resolve from, so the declared and effective defaults cannot drift apart — see
  `docs/configuration/MODES.md`.
- **`shadow` is intentionally asymmetric.** It injects learned guidance into the
  *model's prompt* (pre-selection) but observes only at the *tool call*
  (post-selection). This is a deliberate design choice, not an inconsistency:
  influencing what the model is shown is treated as observation, whereas
  altering or blocking an actual tool execution is treated as intervention.
  Whether guidance injection is appropriate for a mode named `shadow` is an open
  design question — see `docs/configuration/MODES.md`.
- **Guidance presence is not proof of effect.** Guidance appearing in an
  outbound model request demonstrates only that it was *delivered before tool
  selection*. It does not prove the model's decision changed. Measuring a real
  behavioral difference requires a controlled baseline comparison.
- **Guidance is advisory, not an instruction.** The injected text is explicitly
  labelled data ("advisory, do not assume it still applies") and tells the model
  to ignore it if it does not fit the current request.
- **Guidance is absent when nothing qualifies.** If no strategy passes the
  qualification thresholds (5+ outcomes, 80%+ success rate, 3+ independent
  contexts), or the task family resolves to `general` (which has no learned
  experience), `pre_llm_call` returns nothing and the turn proceeds exactly as
  it would without EBTTO.
- **All hooks fail open.** A storage or EBTTO error is logged and returns
  `None`; the ordinary Hermes tool loop is never broken by EBTTO.
- **`auto` in the README's earlier wording maps to `controlled_auto`.** It is
  disabled by default and must be enabled explicitly.

Full implementation detail, including the mode-resolution inconsistency and the
evidence tiers for each claim: `docs/configuration/MODES.md`.

## Privacy

All tool arguments and results pass through `privacy.sanitize()` before
persistence. Redaction patterns include `Authorization: Bearer *****`,
`xoxb-`, `sk-`, `AKIA*`, `BEGIN PRIVATE KEY`, and more.

## Dashboard

A read-only, loopback-only web dashboard over the same database the plugin
writes to:

```bash
python -m hermes_ebtto.dashboard            # http://127.0.0.1:8797/
python -m hermes_ebtto.dashboard --no-browser
```

Pages: Overview (metrics + 14-day trend), Tool Calls (filter/search/drill-down
with sanitized args & errors), Failures (categories + proven recoveries),
Trajectories (per-task timeline, missing stages stated), Memory (patterns &
strategies with evidence, confidence, qualification, provenance), Guidance
(retrieval audit), System (schema/integrity/counts). Binds 127.0.0.1 only;
`mode=ro` + `query_only`; no mutating endpoints; no external assets; XSS-inert
rendering. Full documentation: [docs/development/DASHBOARD.md](docs/development/DASHBOARD.md).

## CLI

```
hermes ebtto status
hermes ebtto stats
hermes ebtto tools
hermes ebtto tasks
hermes ebtto patterns
hermes ebtto strategies
hermes ebtto failures
hermes ebtto regressions
hermes ebtto trajectory
hermes ebtto benchmark
hermes ebtto replay
hermes ebtto export
hermes ebtto prune
hermes ebtto reset
hermes ebtto mode
hermes ebtto doctor
```

## Benchmark

EBTTO ships a benchmark that compares `baseline` (no plugin) vs `ebtto`
(modes: `advisory`, `auto`) across repeated task-family cases. Only measured
values are reported.

```
hermes ebtto benchmark
```

`tests/benchmark/test_behavioral.py` is the offline, dependency-free
simulation suite (baseline vs EBTTO, smart-retry, regression detection,
poisoning resistance — 5 tests, all passing). A live baseline-vs-treatment
behavioral comparison has **not** been run and is not yet proven; see Known
limitations.

## Uninstall

```
hermes plugins disable hermes-ebtto
hermes plugins remove hermes-ebtto
rm -rf ~/.hermes-ebtto
```

## Rollback

If a behavioral mode causes issues:

```
hermes ebtto reset
```

Or restore the previous plugin version from git and reinstall.

## Known limitations

- A **live baseline-vs-treatment behavioral improvement is NOT YET PROVEN**.
  The recording → learning → retrieval loop is verified live (see Provider
  requirements); a controlled A/B run that isolates guidance as the only
  variable has not been executed. The offline `test_harness_ab.py` harness
  (41/41 checks) prepares and validates the experiment but does not perform
  inference.
- Behavioral improvement requires a **working tool-capable provider**. If the
  configured provider cannot execute tools, live tests cannot run.
- `controlled_auto` mode is opt-in only and disabled by default; the effective
  default is `record_only`.
- Parametric experience is experimental and disabled by default.
- This plugin is a **behavior-monitoring and advisory layer**; it does not
  inject system instructions into the model itself.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md).

## Support

- GitHub Issues: https://github.com/developeralvi/hermes-experience-tool-optimizer/issues
