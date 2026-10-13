"""The CI secret-scan job must actually detect secrets.

Two defects were found in ``.github/workflows/ci.yml``:

1. ``git grep`` defaults to **basic** regex, where ``{20,}`` is literal text
   rather than a quantifier. Every token pattern (``sk-``, ``ghp_``, ``AKIA``…)
   silently matched nothing — the scanner could only ever have fired on the
   private-key literal.
2. The scan pathspec included ``*.yml``, which covers ``.github/workflows/``,
   so the job matched the pattern list in its own definition and failed on
   every run.

These tests pin both behaviours so neither can regress silently. They execute
the exact command the workflow runs, in a throwaway git repo, and assert both
directions: a planted secret must be caught, and a clean tree must pass.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _secret_scan_run() -> str:
    with open(CI_YML, encoding="utf-8") as fh:
        workflow = yaml.safe_load(fh)
    steps = workflow["jobs"]["secret-scan"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Secret scan")


def _scan_script() -> str:
    """The workflow's grep logic, runnable standalone.

    Takes the whole ``run:`` block and neutralises only the CI-specific parts:
    the ``set -e`` (so a non-matching grep does not abort the script — the exit
    status is what we assert on) and the ``echo "::error::…"`` annotation. All
    pattern and pathspec lines are kept verbatim, including continuations,
    which a line-prefix filter would silently drop and break.
    """
    run = _secret_scan_run()
    lines = []
    for line in run.splitlines():
        stripped = line.strip()
        if stripped == "set -e":
            continue
        if stripped.startswith('echo "::error::'):
            continue
        if stripped == "exit 1":
            lines.append('  echo "SECRET-DETECTED"')
            continue
        if stripped.startswith('echo "No secrets'):
            lines.append('  echo "NO-SECRETS"')
            continue
        lines.append(line)
    lines.append('echo "exit=$?"')
    return "\n".join(lines) + "\n"


def _bash() -> str:
    """The git-bash binary, resolved explicitly.

    A bare ``bash`` on PATH is not reliable here: this host also has
    ``wsl.exe``, and a WSL bash cannot see the Windows filesystem the repos
    live on, which silently turned a real scan into a WSL usage banner.
    """
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return "bash"


def _run_scan(repo: Path) -> tuple[str, int]:
    """Run the scan logic in *repo* via a script file."""
    script = repo / "_secret_scan.sh"
    script.write_text(_scan_script(), encoding="utf-8", newline="\n")
    try:
        r = subprocess.run(
            [_bash(), str(script)],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=120,
        )
        return r.stdout.strip(), r.returncode
    finally:
        script.unlink(missing_ok=True)


@pytest.fixture()
def scan_repo(tmp_path):
    """A real git repo containing ci.yml plus a scannable source file."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    shutil.copy2(CI_YML, tmp_path / ".github" / "workflows" / "ci.yml")
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_secret_scan_uses_extended_regex():
    """git grep must run with -E, or the {20,} quantifiers are inert."""
    assert "git grep -l -E" in _secret_scan_run(), (
        "secret-scan must use -E: basic regex treats {20,} as literal text, "
        "so the token patterns match nothing"
    )


def test_secret_scan_excludes_its_own_workflow():
    """The pathspec must exclude .github/workflows or the job matches itself."""
    assert ":(exclude).github/workflows/*" in _secret_scan_run(), (
        "pathspec must exclude .github/workflows/* — the file contains the "
        "private-key pattern as a literal string"
    )


def test_secret_scan_passes_on_clean_tree(scan_repo):
    out, rc = _run_scan(scan_repo)
    assert "NO-SECRETS" in out, f"clean tree must report no secrets; got exit={rc} ({out})"
    assert rc == 0, f"clean tree must pass the scan; got exit={rc} ({out})"


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAA1234",
        "gho_BBBBBBBBBBBBBBBBBBBBBB1234",
        "sk-CCCCCCCCCCCCCCCCCCCCCC1234",
        "AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_secret_scan_detects_planted_token(scan_repo, secret):
    """Negative control: each token pattern must actually fire.

    This is the assertion that caught the original defect — without -E every
    one of these tokens was invisible to the scanner.
    """
    (scan_repo / "app.py").write_text(f"TOKEN = '{secret}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=scan_repo, check=True)
    out, rc = _run_scan(scan_repo)
    assert "SECRET-DETECTED" in out, f"secret {secret[:8]}… must be detected; got exit={rc} ({out})"
    assert "app.py" in out, f"scan must name the offending file; got: {out}"
