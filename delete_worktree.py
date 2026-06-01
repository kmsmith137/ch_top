#!/usr/bin/env python3
"""Tear down a feature workspace created by init_worktree.py.

    delete_worktree.py NAME [--force]

Removes the per-repo worktrees and the ch_dev worktree for ../NAME, prunes, and
deletes the directory. Refuses if any worktree has uncommitted (tracked) changes
unless --force is given.

Does NOT delete the feature branches -- remove them by hand if you want:
    git -C ch_dev/<repo> branch -D NAME
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Put this script's own directory on sys.path before the local import below.
# The worktree .envrc exports PYTHONSAFEPATH=1 (cwd-shadowing guard), which drops
# the script dir from sys.path -- so once direnv has run in ch_dev, a bare
# `import ch_dev_helpers` would fail with ModuleNotFoundError. See README.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ch_dev_helpers as wl


def is_dirty(path: Path) -> bool:
    """True if the git working tree at `path` has tracked modifications/untracked
    files (ignored build artifacts and .venv do not count)."""
    return bool(wl.capture(["git", "-C", str(path), "status", "--porcelain"]))


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove a feature worktree workspace.")
    ap.add_argument("name", help="feature/worktree name to remove")
    ap.add_argument("--force", action="store_true",
                    help="remove even if a worktree has uncommitted changes")
    args = ap.parse_args()

    worktree = (wl.ROOT.parent / args.name).resolve()
    if not worktree.exists():
        wl.die(f"no such worktree dir: {worktree}")

    repos = list(wl.load_manifest())

    # Safety: refuse if anything is dirty (unless --force).
    if not args.force:
        checkdirs = [worktree / r for r in repos] + [worktree]
        for p in checkdirs:
            if (p / ".git").exists() and is_dirty(p):
                wl.die(f"{p} has uncommitted changes; commit/stash or use --force")

    # Remove inner repo worktrees first, then the ch_dev worktree. We force the
    # actual removal (the dir holds ignored build artifacts + .venv); the dirty
    # check above is what protects tracked work.
    for repo in repos:
        inner = worktree / repo
        if inner.exists():
            wl.run(["git", "-C", str(wl.ROOT / repo), "worktree", "remove",
                    "--force", str(inner)], check=False)

    wl.run(["git", "-C", str(wl.ROOT), "worktree", "remove",
            "--force", str(worktree)], check=False)

    # Prune bookkeeping and delete any leftover directory.
    wl.run(["git", "-C", str(wl.ROOT), "worktree", "prune"], check=False)
    for repo in repos:
        wl.run(["git", "-C", str(wl.ROOT / repo), "worktree", "prune"], check=False)
    if worktree.exists():
        shutil.rmtree(worktree)

    wl.info(f"removed worktree {worktree}")
    wl.info(f"(feature branches '{args.name}' were kept; delete with 'git branch -D')")


if __name__ == "__main__":
    main()
