# Production Readiness Report — EBTTO

**Date:** 2026-10-11
**Commit:** d240f97 (before: 8987984)
**Branch:** main
**Remote:** https://github.com/developeralvi/hermes-experience-tool-optimizer.git (verified origin)
**Evaluator:** Hermes autonomous audit

Supersedes the 2026-10-08 edition of this report (commit aff8821).

---

## A. Summary

Implemented and verified:

1. Removed the invalid workflow file `.github/workflows/ebtto-pack.yaml` (a
   plugin manifest mistakenly placed under `workflows/` — no `on:`/`jobs:`,
   causing an instant failing "workflow" run on every push). Canonical
   manifest remains `plugin/plugin.yaml`.
2. Rewrote `.github/workflows/ci.yml` into a deterministic, correct pipeline.
3. Updated GitHub About metadata (description + 9 topics) via `gh repo edit`
   and read the values back.
4. Corrected README documentation defects: non-existent hooks, broken doc
   links, false test-tree claims, unsupported behavioral claims; added
   verified live-runtime evidence.
5. `.gitignore` hardened for the local clean-install venv.
6. Pushed commit d240f97 to origin/main (normal push, no force).

Remaining incomplete:

- **GitHub Actions execution is BLOCKED** by an account-level billing lock:
  every job fails at startup with "The job was not started because your
  account is locked due to a billing issue." This is not an application
  defect. Local equivalents of every CI gate were executed instead.
- **Live behavioral benchmark: BLOCKED.** A controlled baseline-vs-treatment
  inference experiment has not been run. The offline A/B harness passes
  41/41 checks but performs no inference.
- **CodeGraph rebuild: NOT PERFORMED** this session; the prior
  `CODEGRAPH-FINAL-REVIEW.md` is retained as historical evidence.
- **GitHub Release: NOT CREATED** (release gates cannot pass in the GitHub
  environment while Actions are billing-locked).

## B. Repository and GitHub identity

| Item | Value |
|---|---|
| Local root | `C:\Users\ENVY\StéWork\EBTTO` |
| Git root | same |
| origin | `https://github.com/developeralvi/hermes-experience-tool-optimizer.git` (matches expected repo) |
| Branch | main |
| Before | 8987984c434c6e74d1ad81ef35178e7cf65c0dea |
| After | d240f97 |
| Push status | Pushed normally (no force), verified via `git fetch` + `gh run list` |

## C. Changes made

| File | Action | Reason |
|---|---|---|
| `.github/workflows/ebtto-pack.yaml` | Deleted | Invalid workflow (plugin manifest under workflows/); nothing references it; caused a failing workflow run on every push. |
| `.github/workflows/ci.yml` | Rewritten | Deterministic pipeline; removed `|| true` on mypy, `continue-on-error` on benchmark step, jobs for nonexistent test dirs, and the false-positive `eyJ` secret pattern. |
| `README.md` | Edited | Removed non-existent hooks; fixed broken doc links; corrected test tree; replaced unproven claims with verified evidence + explicit NOT-YET-PROVEN statement. |
| `.gitignore` | Edited | Ignore `.venv-clean-install/`. |
| `docs/acceptance/PRODUCTION-READINESS-REPORT.md` | Rewritten | This report (supersedes the 2026-10-08 edition, which claimed unverified PASS gates including "behavioral improvement verified"). |

Untracked but intentionally not committed: `experiments/` (local A/B
harness dev tool; no secrets found in scan).

## D. GitHub metadata and CI

- About description set to: "Evidence-based tool-trajectory recording,
  failure classification, and advisory guidance for Hermes Agent."
  Read back via `gh repo view --json description`: confirmed.
- Topics added: hermes-agent, ai-agents, tool-use, trajectory-optimization,
  python, sqlite, observability, developer-tools, llm. Read back via
  `gh repo view --json repositoryTopics`: all 9 confirmed.
- Homepage: left empty (no project website exists).
- CI run after push: https://github.com/developeralvi/hermes-experience-tool-optimizer/actions/runs/38079030067
  — **all jobs failed with "account is locked due to a billing issue"**
  (GitHub-level blocker, not a workflow defect). Workflow YAML parses and
  all job structures validate locally.

## E. Tests and package verification (local execution)

| Gate | Status | Evidence |
|---|---|---|
| Offline tests | PASS | `python -m pytest tests -q` → 16 passed, exit 0 |
| A/B harness | PASS | `python experiments/ab_harness/test_harness_ab.py` → 41/41, exit 0 |
| Package build | PASS | `python -m build --sdist --wheel` → sdist + wheel built |
| Clean-venv install | PASS | wheel installed in fresh venv; `hermes_ebtto.__version__==0.1.0`; `register` importable; migrations 1/2/3 present in installed package |
| Plugin manifest validation | PASS | `plugin/plugin.yaml` + `src/hermes_ebtto/plugin.yaml` both parse, identical, hooks match registered hooks |
| Secret scan (tracked files) | PASS | No real secrets; only redaction-pattern literals in `privacy.py` and doc mentions |
| ruff / mypy | NOT AVAILABLE | Not installed in the local Python environment; CI declares them |
| GitHub Actions run | BLOCKED | Account billing lock (GitHub-side) |

## F. Hermes runtime and learning

- **Offline/mocked:** 16 pytest + 41 harness checks pass.
- **Actual runtime evidence (live Hermes agent.log, 2026-10-11):**
  - `EBTTO plugin registering for mode=shadow` × 26; `registered
    (mode=shadow, hooks=4)` × 24 — plugin discovery + hook registration
    verified live.
  - `[EBTTO pre_llm_call] injecting guidance` × 4 — guidance reaches the
    model before tool selection (the Run-1 → Run-2 loop path fires).
  - `[EBTTO SHADOW] Guidance: terminal best practice` × 126 — retrieval +
    guidance path verified live.
  - `[EBTTO] Pattern persisted` × 560 across terminal/execute_code/patch/
    read_file/skill_view/skill_manage with evidence counts and success
    rates — learning path qualified and persisted patterns live.
  - `[EBTTO] Failure on ...` × 10 — failure classification live.
- **Production database (read-only):** integrity_check ok, 0 FK
  violations, WAL mode; 1691 tool_calls, 1682 outcomes, 66 errors, 22
  patterns, 23 strategies. Never written during this audit (opened
  `mode=ro`); live writer may change counts between reads.
- **Behavioral improvement:** NOT PROVEN. No controlled A/B inference run
  was performed.

## G. CodeGraph

- `.codegraph/` (codegraph.db, 0.87 MB) is git-ignored and untracked —
  generated state correctly excluded from the published tree.
- Prior report `docs/acceptance/CODEGRAPH-FINAL-REVIEW.md` (2026-10-08,
  codegraph 1.5.0: 18 files, 322 nodes, 584 edges) is retained as
  historical evidence. A fresh re-index was not run this session; those
  counts have not been re-verified against the current (grown) source
  tree.

## H. Security and data integrity

- Secret scan on all tracked files: no real credentials (only pattern
  literals in privacy.py and doc prose).
- Production DB `C:\Users\ENVY\.hermes-ebtto\ebtto.db` untouched —
  opened read-only for observational counts only.
- No force-push, no history rewrite, no `git reset --hard`.
- `git add` limited to reviewed files; final working tree clean except the
  intentionally-untracked `experiments/`.

## I. Remaining blockers

1. **GitHub Actions billing lock** — exact message: "The job was not
   started because your account is locked due to a billing issue." Minimum
   action: resolve billing on the GitHub account; then re-run the CI
   workflow (no code change needed — the pipeline is now correct).
2. **Live behavioral benchmark BLOCKED** — requires a controlled inference
   experiment through a tool-capable provider. The offline harness
   (`test_harness_ab.py`, 41/41) prepares and validates the experiment;
   the adapter that performs actual requests has not been authorized
   (zero-cost entitlement unverified).
3. **ruff/mypy local verification NOT AVAILABLE** — not installed locally;
   CI declares them. Once GitHub billing is resolved, the CI runs provide
   this evidence.
4. **CodeGraph re-verification** — not performed this session.

## J. Final verdict

**PARTIAL — core work complete, mandatory gates remain blocked**

All fixable local defects were fixed with evidence; the two mandatory
gates that remain open (GitHub Actions execution, live behavioral
benchmark) are blocked by an account-level billing lock and an
unverified inference entitlement, respectively — not by code defects.
