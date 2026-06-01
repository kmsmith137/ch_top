#!/usr/bin/env python3
"""Fast-forward a finished feature branch onto its integration branch, each repo.

    git-merge-up.py FEATURE [--dry-run] [--no-ff]

Run from the TOPLEVEL ch_dev (it FAILS in a worktree -- the integration branches
are checked out here, not there). For each repo (ch_dev, ksgpu, pirate) whose
integration branch (main / chord / kms) is checked out in the toplevel, merge the
feature branch FEATURE into it.

By default uses `--ff-only`: the merge SUCCEEDS only if FEATURE is already ahead
of the integration branch in a straight line (i.e. you ran git-rebase-down.py in
the worktree first), advancing the integration branch with NO merge commit --
the linear "land" half of the rebase-then-fast-forward workflow. If --ff-only
refuses (the integration branch moved since you rebased), rebase again in the
worktree and retry. Pass --no-ff to instead create one merge commit per repo.

Repos where FEATURE is absent, or already merged, are skipped. Exits non-zero if
any repo's merge fails (e.g. --ff-only could not fast-forward).
"""
from __future__ import annotations

import argparse
import os
import sys

# Put this script's own directory on sys.path before the local import below.
# The worktree .envrc exports PYTHONSAFEPATH=1 (cwd-shadowing guard), which drops
# the script dir from sys.path -- so once direnv has run in ch_dev, a bare
# `import ch_dev_helpers` would fail with ModuleNotFoundError. See README.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ch_dev_helpers as wl


def main() -> None:
    ap = argparse.ArgumentParser(description="Land a feature branch onto its "
                                             "integration branch, in every repo.")
    ap.add_argument("feature", help="feature branch name to land, e.g. ch_evrb")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the merge each repo would run, but do nothing")
    ap.add_argument("--no-ff", action="store_true",
                    help="create a merge commit instead of fast-forward-only")
    args = ap.parse_args()
    feat = args.feature

    if not wl.is_toplevel():
        wl.die("git-merge-up.py must be run from the toplevel ch_dev, not a "
               "worktree (the integration branches main/chord/kms are checked out "
               "in the toplevel; you cannot merge into them from a worktree).")

    mode = ["--no-ff"] if args.no_ff else ["--ff-only"]
    specs = []
    for repo, path, integ, current in wl.repo_branch_info():
        if current != integ:
            wl.warn(f"{repo}: HEAD is '{current}', not integration '{integ}' -- skipping")
            continue
        if not wl.branch_exists(path, feat):
            wl.warn(f"{repo}: no branch '{feat}', skipping")
            continue
        ab = wl._ahead_behind(path, integ, feat)  # (ahead, behind) of feat vs integ
        if ab is not None and ab[0] == 0:  # feat has nothing integ lacks
            wl.info(f"{repo}: {integ} already contains {feat}, skipping")
            continue
        specs.append((f"{repo}: merge {feat} -> {integ}", path,
                      ["merge", *mode, feat]))

    if not specs:
        wl.info(f"nothing to land for '{feat}'.")
        return
    worst, failed = wl.run_git_each(specs, dry_run=args.dry_run)
    if failed:
        wl.die(f"merge failed in: {', '.join(failed)}. With --ff-only this means "
               f"the integration branch moved since you rebased -- re-run "
               f"git-rebase-down.py in the {feat} worktree, then retry.")
    elif not args.dry_run:
        wl.info(f"landed '{feat}'. Tear down with: "
                f"delete_worktree.py {feat} ; then `git branch -d {feat}` per repo.")


if __name__ == "__main__":
    main()
