#!/usr/bin/env python3
"""One-time setup of the main repo checkouts under ch_dev.

    init_toplevel.py [--no-venv]

For each repo in git_repositories.toml: clone it (if missing) into ch_dev/<name>,
check out its branch, and init submodules. Then render ch_dev/.envrc and build
the ch_dev .venv. Idempotent: existing clones are left in place (only submodules
are refreshed; a branch mismatch is warned about, not changed).

The toplevel ch_dev is your *unsandboxed* management workspace (you run these
scripts here, and they must write outside the dir), so no sandbox
.claude/settings.json is rendered for it -- only .envrc for venv activation.
"""
from __future__ import annotations

import argparse
import os
import sys

# Put this script's own directory on sys.path before the local imports below.
# The worktree .envrc exports PYTHONSAFEPATH=1 (cwd-shadowing guard), which drops
# the script dir from sys.path -- so once direnv has run in ch_dev, a bare
# `import ch_dev_helpers` would fail with ModuleNotFoundError. See README.md.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ch_dev_helpers as wl
import init_venv


def setup_repo(name: str, url: str, branch: str) -> None:
    dest = wl.ROOT / name
    if not dest.exists():
        wl.run(["git", "clone", url, str(dest)])
        wl.run(["git", "-C", str(dest), "checkout", branch])
    else:
        current = wl.capture(["git", "-C", str(dest), "branch", "--show-current"])
        if current != branch:
            wl.warn(f"{name} is on '{current}' but manifest says '{branch}' -- "
                    f"leaving as-is (checkout by hand if that is wrong)")
        else:
            wl.info(f"{name}: clone exists on '{branch}'")
    # Always (re)init submodules -- e.g. pirate's asdf-cxx, whose sources the
    # build compiles into libpirate.so. Harmless no-op for repos without any.
    wl.run(["git", "-C", str(dest), "submodule", "update", "--init", "--recursive"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Set up the main ch_dev checkouts.")
    ap.add_argument("--no-venv", action="store_true",
                    help="clone + submodules only; skip building the ch_dev venv")
    args = ap.parse_args()

    for name, cfg in wl.load_manifest().items():
        setup_repo(name, cfg["url"], cfg["branch"])

    wl.render_dotfiles(wl.ROOT, sandbox=False)

    if not args.no_venv:
        init_venv.build(wl.ROOT)

    wl.info("toplevel ready")


if __name__ == "__main__":
    main()
