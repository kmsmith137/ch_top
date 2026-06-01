#!/usr/bin/env python3
"""`git status` across all repos in a ch_dev workspace, plus a branch-relation
summary.

    git-status.py [GIT_STATUS_ARGS...]

Runs `git status` in the workspace root (ch_dev / ch_<feature>) and in each
manifest repo subdir (ksgpu, pirate, ...), under a per-repo header. Extra args
are passed through to git, e.g. `git-status.py -s` or `git-status.py -sb`.

Then prints, for each repo, how the feature-worktree branch relates to that
repo's integration branch (the one checked out in the main worktree), e.g.
'pirate/ch_evrb is 2 commits ahead of pirate/kms'. Run from the toplevel ch_dev
this covers every feature worktree; run from a feature worktree it covers only
that worktree's own branch.

Exits with the worst git exit code across the repos.
"""
from __future__ import annotations

import os
import sys

# Put this script's own directory on sys.path before the local import below.
# The worktree .envrc exports PYTHONSAFEPATH=1 (cwd-shadowing guard), which drops
# the script dir from sys.path -- so once direnv has run in ch_dev, a bare
# `import ch_dev_helpers` would fail with ModuleNotFoundError. See README.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ch_dev_helpers as wl


def main() -> None:
    rc = wl.run_git_all(["status", *sys.argv[1:]])
    relations = wl.branch_relations()
    if relations:
        print("==================== branch relations ====================")
        for line in relations:
            print(line)
        print()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
