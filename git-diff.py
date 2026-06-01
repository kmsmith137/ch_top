#!/usr/bin/env python3
"""`git diff` across all repos in a ch_dev workspace.

    git-diff.py [GIT_DIFF_ARGS...]

Runs `git diff` in the workspace root (ch_dev / ch_<feature>) and in each
manifest repo subdir (ksgpu, pirate, ...), under a per-repo header. Extra args
are passed through to git, e.g. `git-diff.py --stat` or `git-diff.py --cached`.

Exits with the worst git exit code across the repos (note: a plain `git diff`
returns 0 even when there are changes; use `--exit-code` if you want non-zero).
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
    raise SystemExit(wl.run_git_all(["diff", *sys.argv[1:]]))


if __name__ == "__main__":
    main()
