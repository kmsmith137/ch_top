#!/usr/bin/env python3
"""Create (or refresh) a workspace's .venv overlay over the active conda env.

    init_venv.py [WORKDIR] [--recreate] [--test]

WORKDIR defaults to the ch_dev root. The .venv is seeded (--system-site-packages)
from the active conda interpreter, then each repo in BUILD is compiled with
`make` and installed editable. See plans/multi_agent_workspace.md Section 5.

IMPORTANT: BUILD below is NOT derived from git_repositories.toml. When you add a
repo to the manifest, add its build step here too, in dependency order. See the
REMINDER in git_repositories.toml. (This script warns about any manifest repo it
does not build.)
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import ch_dev_helpers as wl

# Per-repo build recipe, in dependency order (ksgpu before pirate). Each entry
# is (repo_subdir, make_args); the editable install is always
# `pip install --no-build-isolation -e .` run in that repo.
BUILD = [
    ("ksgpu", ["make", "-j", "32"]),
    ("pirate", ["make", "-j", "32"]),
]

# Fast import check (always run). The heavy GPU unit test is gated behind --test.
SMOKE_IMPORT = "import ksgpu, pirate_frb; print('import ok')"
HEAVY_TEST = ["-m", "pirate_frb", "test", "-n", "1"]


def build(workdir, *, recreate: bool = False, test: bool = False) -> None:
    workdir = Path(workdir).resolve()
    if not workdir.is_dir():
        wl.die(f"workdir does not exist: {workdir}")

    # Reminder enforcement: warn about manifest repos this script does not build.
    built = {name for name, _ in BUILD}
    for name in wl.load_manifest():
        if name not in built:
            wl.warn(f"repo '{name}' is in the manifest but init_venv.py does not "
                    f"build it -- add it to BUILD in {Path(__file__).name}")

    venv = workdir / ".venv"
    if venv.exists() and recreate:
        wl.info(f"removing existing venv {venv}")
        shutil.rmtree(venv)

    if not venv.exists():
        wl.run([wl.base_python(), "-m", "venv", "--system-site-packages", str(venv)])
    else:
        wl.info(f"reusing existing venv {venv} (use --recreate to rebuild)")

    env = wl.venv_env(workdir)
    pip = str(venv / "bin" / "pip")
    py = str(venv / "bin" / "python")

    # Build backend for the --no-build-isolation editable installs.
    wl.run([pip, "install", "pipmake"], env=env)
    # `editables` must live IN the venv, not merely be visible via
    # --system-site-packages: an editable install's .pth imports it during
    # interpreter startup, before the conda site-packages are on sys.path, so
    # the conda copy is not yet importable and the .pth (hence the package it
    # registers) is silently dropped ("No module named 'editables'"). Force it
    # into the venv's own site-packages.
    wl.run([pip, "install", "--ignore-installed", "editables"], env=env)

    for name, make_args in BUILD:
        repo = workdir / name
        if not repo.is_dir():
            wl.die(f"repo dir missing: {repo}  (run init_toplevel.py first?)")
        wl.run(make_args, cwd=str(repo), env=env)
        wl.run([pip, "install", "--no-build-isolation", "-e", "."],
               cwd=str(repo), env=env)

    # Smoke test from a throwaway directory, NOT the workspace root. The root
    # contains 'ksgpu/' (and 'pirate/') source subdirs that Python would pick up
    # from sys.path[0] as empty PEP 420 namespace packages, shadowing the
    # editable-installed packages -- hiding ksgpu's __init__.py and its ctypes
    # RTLD_GLOBAL trick (=> "undefined symbol: ksgpu::convert_array_from_python").
    # The worktree env (.envrc / .claude/settings.json) also sets
    # PYTHONSAFEPATH=1 to neutralize this for every cwd, but init_venv must not
    # depend on that being active -- it can run during first-time setup, before
    # those dotfiles exist. See README.md "cwd shadowing".
    with tempfile.TemporaryDirectory() as tmp:
        wl.run([py, "-c", SMOKE_IMPORT], cwd=tmp, env=env)
        if test:
            wl.run([py, *HEAVY_TEST], cwd=tmp, env=env)

    wl.info(f"venv ready: {venv}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a workspace .venv overlay.")
    ap.add_argument("workdir", nargs="?", default=str(wl.ROOT),
                    help="workspace dir (default: ch_dev root)")
    ap.add_argument("--recreate", action="store_true",
                    help="delete and rebuild .venv from scratch")
    ap.add_argument("--test", action="store_true",
                    help="also run the slow GPU unit test (pirate_frb test -n 1)")
    args = ap.parse_args()
    build(args.workdir, recreate=args.recreate, test=args.test)


if __name__ == "__main__":
    main()
