"""Installed-location consistency tests.

The repository ships copies of the package in FOUR places, and a running
gateway may import any of them:

  1. ``src/hermes_ebtto/``                      canonical source
  2. ``plugin/``                                deliberate in-repo mirror
  3. ``%LOCALAPPDATA%/hermes/plugins/hermes_ebtto/``
  4. ``hermes-agent/venv/Lib/site-packages/hermes_ebtto/``
                                                the one the gateway imports

These tests exist because of a real defect: locations 3 and 4 were never
verified by anything, so a stale copy in location 4 served pre-fix code to a
gateway that had just been restarted. Mirror-consistency tests compared only
the two in-repo trees and could not see it.

Locations 3 and 4 live outside the repository and are only checked when the
host actually has them installed; the tests skip cleanly on CI and on any
machine without a Hermes installation. That keeps them useful on the
development host without making the suite host-dependent.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "hermes_ebtto"

SKIP_DIRS = {"__pycache__"}
SUFFIXES = {".py", ".sql", ".yaml", ".yml", ".js", ".css", ".html", ".json", ".md"}


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _installed_locations() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    hermes = local / "hermes"
    return [
        ("plugins-dir", hermes / "plugins" / "hermes_ebtto"),
        (
            "venv-site-packages",
            hermes / "hermes-agent" / "venv" / "Lib" / "site-packages" / "hermes_ebtto",
        ),
    ]


def _source_map() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in SRC.rglob("*"):
        if not p.is_file() or SKIP_DIRS & set(p.parts) or p.suffix not in SUFFIXES:
            continue
        out[str(p.relative_to(SRC)).replace("\\", "/")] = p
    return out


def test_source_tree_is_not_empty():
    """Guard against the tests silently passing because src/ was not found."""
    src = _source_map()
    assert len(src) >= 20, f"only {len(src)} source files found under {SRC}"
    assert "plugins/__init__.py" in src
    assert "migrations/5.sql" in src


def _present_locations():
    return [(label, path) for label, path in _installed_locations() if path.is_dir()]


def test_at_least_one_installed_location_is_present():
    """On a Hermes host at least one installed copy must exist.

    CI has no Hermes install, so absence is not a failure there — but if a
    location exists it is verified by the tests below. This test documents
    the expectation rather than enforcing it everywhere.
    """
    present = _present_locations()
    if not present:
        pytest.skip("no Hermes installed locations on this host")


@pytest.mark.parametrize(
    "label,path", _present_locations(), ids=lambda x: str(x) if isinstance(x, str) else ""
)
def test_installed_files_are_identical_to_source(label, path):
    """Every source file must be byte-identical in the installed location.

    This is the check that was missing when a stale venv copy kept serving
    pre-fix code to a restarted gateway.
    """
    src = _source_map()
    stale = [
        rel
        for rel, sp in src.items()
        if not (path / rel).exists() or _digest(path / rel) != _digest(sp)
    ]
    assert not stale, (
        f"{label}: {len(stale)} file(s) differ from src/ — run "
        f"`python tools/sync_installed.py`: {stale[:5]}"
    )


@pytest.mark.parametrize(
    "label,path", _present_locations(), ids=lambda x: str(x) if isinstance(x, str) else ""
)
def test_no_orphan_files_in_installed_location(label, path):
    """Installed locations must not contain files absent from src/.

    A stale orphan (an old ``queries.py`` at the package root was observed
    during the audit) is drift evidence even when nothing imports it.
    """
    src = _source_map()
    orphans = [
        str(p.relative_to(path)).replace("\\", "/")
        for p in path.rglob("*")
        if p.is_file()
        and not (SKIP_DIRS & set(p.parts))
        and p.suffix in SUFFIXES
        and str(p.relative_to(path)).replace("\\", "/") not in src
    ]
    assert not orphans, (
        f"{label}: {len(orphans)} orphan file(s) with no src/ counterpart: {orphans[:5]}"
    )


@pytest.mark.parametrize(
    "label,path", _present_locations(), ids=lambda x: str(x) if isinstance(x, str) else ""
)
def test_installed_location_has_all_migrations(label, path):
    """Migrations 1-5 must exist in every installed copy.

    A venv copy stuck at migrations 1-3 is exactly the failure this test
    suite exists to catch: the schema and the code disagree, and the plugin
    silently runs with half the telemetry tables.
    """
    mig = path / "migrations"
    assert mig.is_dir(), f"{label}: no migrations/ directory"
    present = {p.stem for p in mig.glob("*.sql")}
    missing = {"1", "2", "3", "4", "5"} - present
    assert not missing, f"{label}: migrations {sorted(missing)} missing (have {sorted(present)})"
