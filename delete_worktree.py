#!/usr/bin/env python3
"""Tear down a feature workspace created by init_worktree.py.

    delete_worktree.py NAME [--force]

Removes the per-repo worktrees and the ch_dev worktree for ../NAME, then deletes
each repo's feature branch NAME with `git branch -d` (which refuses unless the
branch is merged into its integration branch). Finally prunes and removes the
directory.

Refuses (in ANY of the 3 repos), unless --force is given, if the worktree has:
  - uncommitted changes to tracked files, or
  - stray untracked files (gitignored build artifacts / .venv do not count), or
  - commits not yet merged "up" to the integration branch (main/chord/kms).
A worktree that is merely BEHIND its integration branch (un-rebased) is fine.

--force overrides those three checks for removing the worktree DIR, but branch
deletion always uses `git branch -d` (never -D), so an unmerged branch is kept
(its commits are preserved) even under --force.
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


def repo_problems(repo, wt_path, main_path, integ, feat):
    """Reasons (list of strings) it is unsafe to delete this repo's worktree:
    uncommitted tracked changes, stray untracked files, unmerged commits."""
    problems = []
    porcelain = wl.capture(["git", "-C", str(wt_path), "status", "--porcelain"])
    tracked = [l for l in porcelain.splitlines() if not l.startswith("??")]
    stray = [l for l in porcelain.splitlines() if l.startswith("??")]
    if tracked:
        problems.append(f"{repo}: uncommitted changes to tracked files:\n"
                        + "\n".join("      " + l for l in tracked))
    if stray:
        problems.append(f"{repo}: stray untracked files (not gitignored):\n"
                        + "\n".join("      " + l for l in stray))
    if feat is not None and feat != integ:
        ab = wl._ahead_behind(main_path, integ, feat)  # (ahead, behind) of feat
        if ab is not None and ab[0] > 0:
            problems.append(f"{repo}: {ab[0]} commit(s) on '{feat}' not merged up "
                            f"to '{integ}' -- run git-merge-up.py first")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove a feature worktree workspace.")
    ap.add_argument("name", help="feature/worktree name to remove")
    ap.add_argument("--force", action="store_true",
                    help="remove the worktree dir even if it has uncommitted "
                         "changes, stray files, or unmerged commits")
    args = ap.parse_args()
    name = args.name

    worktree = (wl.ROOT.parent / name).resolve()
    if not worktree.exists():
        wl.die(f"no such worktree dir: {worktree}")

    # Snapshot per-repo info while the worktree still exists:
    # (repo, worktree-checkout, toplevel-checkout, integration-branch, feature-branch)
    plan = []
    for repo, wt_path, integ, feat in wl.repo_branch_info(worktree):
        plan.append((repo, wt_path, wl.repo_main_path(wt_path), integ, feat))
    if not plan:
        wl.die(f"{worktree} does not look like a workspace (no git repos found)")

    # Safety checks across all repos (unless --force).
    if not args.force:
        problems = []
        for entry in plan:
            problems += repo_problems(*entry)
        if problems:
            wl.die("refusing to delete " + str(worktree) + ":\n  "
                   + "\n  ".join(problems)
                   + "\n(commit/merge-up, clean up, or use --force)")

    # Remove inner repo worktrees first, then the ch_dev worktree. We force the
    # actual removal (the dir holds ignored build artifacts + .venv); the checks
    # above are what protect tracked/committed work.
    repos = list(wl.load_manifest())
    for repo in repos:
        inner = worktree / repo
        if inner.exists():
            wl.run(["git", "-C", str(wl.ROOT / repo), "worktree", "remove",
                    "--force", str(inner)], check=False)
    wl.run(["git", "-C", str(wl.ROOT), "worktree", "remove",
            "--force", str(worktree)], check=False)

    # Prune bookkeeping.
    wl.run(["git", "-C", str(wl.ROOT), "worktree", "prune"], check=False)
    for repo in repos:
        wl.run(["git", "-C", str(wl.ROOT / repo), "worktree", "prune"], check=False)

    # Delete each repo's feature branch with `git branch -d` (refuses unless the
    # branch is merged into HEAD = the integration branch -- a double-check that
    # nothing committed is lost, which holds even under --force).
    for repo, _wt_path, main_path, integ, feat in plan:
        if feat is None:
            wl.warn(f"{repo}: worktree had a detached HEAD; no branch to delete")
            continue
        if feat == integ:
            wl.warn(f"{repo}: worktree was on integration branch '{integ}'; "
                    f"not deleting it")
            continue
        res = wl.run(["git", "-C", str(main_path), "branch", "-d", feat], check=False)
        if res.returncode != 0:
            wl.warn(f"{repo}: kept branch '{feat}' (git branch -d refused it -- "
                    f"likely not merged into '{integ}'; its commits are preserved)")

    if worktree.exists():
        shutil.rmtree(worktree)

    wl.info(f"removed worktree {worktree}")


if __name__ == "__main__":
    main()
