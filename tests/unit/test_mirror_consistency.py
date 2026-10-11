"""Mirror-consistency tests.

The repository ships TWO copies of the package by design:
  * ``src/hermes_ebtto/``    — canonical source tree (built into the wheel)
  * ``plugin/hermes_ebtto/`` — installation mirror used when the plugin is
    dropped straight into a Hermes plugins directory

They are deliberately mirrored, NOT two canonical sources. These tests fail
loudly when the copies drift so a fix applied to one side can never be
forgotten on the other.
"""

import filecmp
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "hermes_ebtto"
PLUGIN = ROOT / "plugin"

# files that legitimately differ or exist only on one side
_SRC_ONLY = {"__pycache__"}


def _rel(p: Path) -> str:
    return str(p.relative_to(SRC))


@pytest.mark.parametrize("rel", sorted(
    _rel(p) for p in SRC.rglob("*") if p.is_file()
    and "__pycache__" not in p.parts and p.suffix in (".py", ".sql", ".yaml",
                                                      ".js", ".css", ".html")
))
def test_src_files_exist_in_plugin_mirror(rel):
    """Every source file must exist in the mirror."""
    mirror = PLUGIN / rel
    assert mirror.exists(), f"{rel} is missing from plugin/ mirror"


@pytest.mark.parametrize("rel", sorted(
    _rel(p) for p in SRC.rglob("*") if p.is_file()
    and "__pycache__" not in p.parts and p.suffix in (".py", ".sql", ".yaml",
                                                      ".js", ".css", ".html")
))
def test_mirror_files_are_byte_identical(rel):
    """Mirror copies must be byte-identical to the canonical source."""
    mirror = PLUGIN / rel
    if not mirror.exists():
        pytest.skip("covered by test_src_files_exist_in_plugin_mirror")
    assert filecmp.cmp(SRC / rel, mirror, shallow=False), \
        f"{rel} differs between src/ and plugin/ — sync them before commit"


def test_no_extra_files_in_mirror():
    """The mirror must not contain files absent from src/ (drift detector)."""
    for p in PLUGIN.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(PLUGIN))
        assert (SRC / rel).exists(), \
            f"plugin/{rel} has no src/ counterpart — stale mirror file"
