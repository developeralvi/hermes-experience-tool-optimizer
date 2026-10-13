#!/usr/bin/env python
"""Sync the EBTTO package to every location a Hermes process may import it from.

WHY THIS EXISTS
---------------
Phase H of the activation audit found the package served from FOUR locations:

  1. ``src/hermes_ebtto/``        canonical source (built into the wheel)
  2. ``plugin/``                  deliberate mirror (in-repo)
  3. ``%LOCALAPPDATA%\\hermes\\plugins\\hermes_ebtto\\``
                                  directory the plugin loader discovers
  4. ``hermes-agent\\venv\\Lib\\site-packages\\hermes_ebtto\\``
                                  the path a running gateway ACTUALLY imports

The defect was not a bad copy command. It was that locations 3 and 4 were
never checked by anything, so an out-of-date copy in location 4 silently
kept serving pre-fix code to a "restarted" gateway. Mirror-consistency tests
only compared the two in-repo trees and could never see it.

Run this after any change to ``src/``::

    python tools/sync_installed.py

It is safe to run at any time: it only ever copies files that already exist
in ``src/`` and never deletes from the running interpreter's import path.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hermes_ebtto"


# The installed locations, resolved from the environment so the tool works on
# any Windows host without hardcoding a username.
def installed_targets() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    hermes = local / "hermes"
    return [
        ("plugins-dir", hermes / "plugins" / "hermes_ebtto"),
        (
            "venv-site-packages",
            hermes / "hermes-agent" / "venv" / "Lib" / "site-packages" / "hermes_ebtto",
        ),
    ]


SKIP_DIRS = {"__pycache__"}
SYNC_SUFFIXES = {".py", ".sql", ".yaml", ".yml", ".js", ".css", ".html", ".json", ".md"}


def file_digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_tree() -> dict[str, Path]:
    """Relative-path -> absolute path for every shippable file in src/."""
    out: dict[str, Path] = {}
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp = Path(root) / f
            if fp.suffix in SYNC_SUFFIXES:
                out[str(fp.relative_to(SRC)).replace("\\", "/")] = fp
    return out


def sync(dry_run: bool) -> tuple[int, int]:
    """Copy src/ into the in-repo mirror and every installed location.

    Order matters: format the source FIRST, then sync. Running
    ``ruff format src`` after a sync silently re-breaks the mirror, which is
    exactly how the mirror drifted during the Phase H audit.
    """
    copied_plugin = sync_repo_mirror(dry_run)
    src = source_tree()
    total_copied = total_unchanged = copied_plugin
    for label, target in installed_targets():
        if not target.exists():
            print(f"  {label:20s} SKIP (not present: {target})")
            continue
        copied = unchanged = 0
        for rel, sp in sorted(src.items()):
            dp = target / rel
            if dp.exists() and file_digest(dp) == file_digest(sp):
                unchanged += 1
                continue
            copied += 1
            if not dry_run:
                dp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sp, dp)
        print(f"  {label:20s} {copied} copied, {unchanged} already current")
        total_copied += copied
        total_unchanged += unchanged
    return total_copied, total_unchanged


def sync_repo_mirror(dry_run: bool) -> int:
    """Keep the in-repo ``plugin/`` mirror byte-identical to ``src/``."""
    target = ROOT / "plugin"
    if not target.exists():
        return 0
    copied = 0
    for rel, sp in sorted(source_tree().items()):
        dp = target / rel
        if dp.exists() and file_digest(dp) == file_digest(sp):
            continue
        copied += 1
        if not dry_run:
            dp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)
    print(f"  {'plugin/ (mirror)':20s} {copied} copied")
    return copied


def verify() -> int:
    """Return 0 when every reachable installed location matches src/."""
    src = {rel: file_digest(p) for rel, p in source_tree().items()}
    rc = 0
    checked = 0
    for label, target in installed_targets():
        if not target.exists():
            continue
        checked += 1
        mismatches = []
        for rel, digest in src.items():
            dp = target / rel
            if not dp.exists():
                mismatches.append(f"MISSING {rel}")
            elif file_digest(dp) != digest:
                mismatches.append(f"STALE   {rel}")
        extras = [
            str(p.relative_to(target)).replace("\\", "/")
            for p in target.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and str(p.relative_to(target)).replace("\\", "/") not in src
            and p.suffix in SYNC_SUFFIXES
        ]
        if mismatches or extras:
            rc = 1
            print(f"  {label:20s} FAIL")
            for m in mismatches[:10]:
                print(f"      {m}")
            for e in extras[:10]:
                print(f"      ORPHAN  {e} (no src/ counterpart)")
        else:
            print(f"  {label:20s} OK ({len(src)} files identical to src/)")
    if checked == 0:
        print("  (no installed locations found on this host)")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify only, exit 1 on drift")
    ap.add_argument("--dry-run", action="store_true", help="report copies without writing")
    args = ap.parse_args(argv)

    if not SRC.exists():
        print(f"error: {SRC} not found — run from the repository", file=sys.stderr)
        return 2

    if args.check:
        print("EBTTO installed-location consistency check")
        return verify()

    print("EBTTO sync -> installed locations" + (" (dry run)" if args.dry_run else ""))
    copied, unchanged = sync(args.dry_run)
    print(f"total: {copied} copied, {unchanged} already current")
    print("\npost-sync verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
