# EBTTO

**Experience-Based Tool Trajectory Optimization** for Hermes Agent.

[![CI](https://github.com/developeralvi/hermes-experience-tool-optimizer/actions/workflow/ci.yml/badge.svg)](https://github.com/developeralvi/hermes-experience-tool-optimizer/actions/workflows/ci.yml)

EBTTO makes agent tool-use observable, auditable, and improvable through real
execution evidence. It hooks the actual Hermes runtime — `pre_tool_call`,
`post_tool_call`, `pre_llm_call`, `on_session_start`, and
`on_session_finalize`/`on_session_end` — to capture trajectories, learn from
failures, and inject compact guidance into future turns **before** the model
selects a tool.

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
│   └── migrations/1.sql         # SQLite schema
├── tests/
│   ├── unit/                    # unit, contract, integration tests
│   ├── security/                # prompt injection, poisoning, path traversal
│   ├── regression/              # degraded-strategy revalidation
│   └── benchmark/               # baseline vs EBTTO behavioral tests
├── docs/
│   ├── architecture/            # System design
│   ├── compatibility/           # Hermes runtime contract
│   ├── configuration/           # Modes, storage, privacy
│   ├── development/             # Contribution guide
│   ├── operations/              # CLI reference
│   ├── security/                # Threat model
│   ├── benchmarks/              # Behavioral results
│   └── acceptance/              # Forensic audit reports
├── .github/workflows/           # CI (unit, integration, security, etc.)
├── .gitignore
├── pyproject.toml               # Build system & project metadata
└── Makefile                     # Common commands
```

## Installation

See the [Installation](docs/installation.md) page for full details.

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
[docs/compatibility/HERMES-RUNTIME-CONTRACT.md](docs/compatibility/HERMES-RUNTIME-CONTRACT.md)

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

The current `cline-free` route returns **401** and is marked unavailable.
Once a working tool-capable provider is available, the behavioral acceptance
gates (Phases 11–22) can run.

See [Provider Runtime Compatibility](docs/acceptance/PROVIDER-RUNTIME-COMPATIBILITY.md).

## Modes

- **record_only** — Observe and record everything. No guidance, no intervention.
- **advisory** (default) — Inject compact guidance in `pre_llm_call`. Never
  modifies or blocks the model's tool choice.
- **auto** — Auto mode executes safe stored strategies. **Disabled by default.**
  Must be explicitly toggled per run via the CLI.

## Privacy

All tool arguments and results pass through `privacy.sanitize()` before
persistence. Redaction patterns include `Authorization: Bearer *****`,
`xoxb-`, `sk-`, `AKIA*`, `BEGIN PRIVATE KEY`, and more.

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

See [docs/benchmarks/REAL-BEHAVIORAL-RESULTS.md](docs/benchmarks/REAL-BEHAVIORAL-RESULTS.md)
for actual measured results.

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

- Behavioral improvement requires a **working tool-capable provider**.
  The current `cline-free` provider route returns 401.
- `auto` mode is opt-in only and disabled by default.
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
