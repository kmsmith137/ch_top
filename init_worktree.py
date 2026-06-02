#!/usr/bin/env python3
"""Create a feature workspace as a set of git worktrees, then build its venv.

    init_worktree.py NAME [--no-venv]

Creates the sibling directory ../NAME containing:
  - a worktree of ch_dev on a new branch NAME (off current HEAD)
  - a worktree of each manifest repo on a new branch NAME, based on that repo's
    integration branch (ksgpu off 'chord', pirate off 'kms', ...)
  - submodules initialized in each new worktree (e.g. pirate's asdf-cxx)
  - rendered .envrc + .claude/env.sh (venv activation) and .agent/run (the
    rootless-Podman sandbox launcher)
  - a .venv overlay with editable installs

See plans/multi_agent_workspace.md Sections 2c, 6, 7.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Put this script's own directory on sys.path before the local imports below.
# The worktree .envrc exports PYTHONSAFEPATH=1 (cwd-shadowing guard), which drops
# the script dir from sys.path -- so once direnv has run in ch_dev, a bare
# `import ch_dev_helpers` would fail with ModuleNotFoundError. See README.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ch_dev_helpers as wl
import init_venv


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a feature worktree workspace.")
    ap.add_argument("name", help="feature/worktree name, e.g. ch_dedisp")
    ap.add_argument("--no-venv", action="store_true",
                    help="create worktrees + dotfiles but skip the venv build")
    args = ap.parse_args()
    name = args.name

    worktree = (wl.ROOT.parent / name).resolve()
    if worktree.exists():
        wl.die(f"target already exists: {worktree}")

    repos = wl.load_manifest()

    # 1. Worktree of ch_dev itself (new branch NAME off current HEAD).
    wl.run(["git", "-C", str(wl.ROOT), "worktree", "add", str(worktree), "-b", name])

    # 2. Worktree of each repo (new branch NAME based on its integration branch),
    #    then init that worktree's submodules.
    for repo, cfg in repos.items():
        main_repo = wl.ROOT / repo
        if not main_repo.is_dir():
            wl.die(f"{main_repo} missing -- run init_toplevel.py first")
        inner = worktree / repo
        wl.run(["git", "-C", str(main_repo), "worktree", "add",
                str(inner), "-b", name, cfg["branch"]])
        wl.run(["git", "-C", str(inner),
                "submodule", "update", "--init", "--recursive"])

    # 3. Dotfiles: venv activation (.envrc, .claude/env.sh) + the Podman sandbox
    #    launcher (.agent/run). Then make sure its base image is pulled.
    wl.render_dotfiles(worktree, sandbox=True)
    wl.ensure_sandbox_image()

    # 4. Build the venv overlay (editable installs).
    if not args.no_venv:
        init_venv.build(worktree)

    wl.info(f"worktree ready: {worktree}")
    wl.info(f"next: 'direnv allow {worktree}', then 'cd {worktree} && ./.agent/run' "
            f"to start the sandboxed agent (or run plain 'claude' for an "
            f"unsandboxed shell there)")


if __name__ == "__main__":
    main()
