# ch_dev -- personal multi-repo, multi-agent dev workspace

Personal "container" repo holding the scripts that manage a multi-repo software
workspace (currently `ksgpu` + `pirate`) and spin up isolated per-feature
worktrees for running coding agents.

Full design rationale: `plans/multi_agent_workspace.md`.

## Assumptions / prerequisites

- **Conda toolchain env, activated externally.** Nothing in this repo names or
  activates a conda env. You must have your conda env (cuda/nvcc, cupy, grpc,
  yaml-cpp, asdf, pybind11, ...) active in every shell -- load it in
  `~/.bashrc`. The scripts seed each `.venv` from whatever `python` is active.
- **direnv**, on PATH in every shell (prefer an env-independent location like
  `~/.local/bin`, not a conda env), with the hook in `~/.bashrc` *after* your
  `conda activate` line:

      eval "$(direnv hook bash)"

- **A GPU + CUDA toolchain** (the build compiles CUDA and runs GPU tests).
- For sandboxing: **bubblewrap**, **socat**, and the seccomp helper
  (`@anthropic-ai/sandbox-runtime`); on Ubuntu 24.04 also the AppArmor `bwrap`
  profile. See `plans/multi_agent_workspace.md` Section 7.

## Layout

    ch_dev/                  this repo (branch main); management scripts
    ch_dev/ksgpu             plain clone, branch chord   (gitignored)
    ch_dev/pirate            plain clone, branch kms     (gitignored)
    ../ch_<feature>/         a feature workspace = git worktrees + .venv

A feature workspace is a *sibling* of `ch_dev`, itself a git worktree of
`ch_dev`, containing a worktree of each repo plus a per-workspace `.venv`,
`.envrc`, and `.claude/settings.json`.

## cwd shadowing (important)

Because the layout nests the repos under the workspace root, the root contains a
directory named `ksgpu/` -- the same name as the `ksgpu` Python package. Python
puts the current directory at the front of `sys.path` (`python -c`, `python -m`,
and the REPL use the cwd; `python script.py` uses the script's dir). So running
Python *from the workspace root* makes `import ksgpu` pick up that `ksgpu/`
directory as an empty namespace package, shadowing the editable-installed
package. Its `__init__.py` -- and the ctypes trick that publishes ksgpu's C++
symbols -- never runs, and `import pirate_frb` then fails with a cryptic
`undefined symbol: ksgpu::convert_array_from_python`. Activating the venv does
NOT help: the cwd entry sits ahead of site-packages regardless. (`pirate`'s
checkout dir is `pirate` but its package is `pirate_frb`, so it is never
*directly* shadowed -- it only fails transitively via `ksgpu`.)

Three layers guard against this, so you normally never see it:

1. Each worktree's `.envrc` (direnv, for you) and `.claude/settings.json` env
   (for agents) set `PYTHONSAFEPATH=1`, which drops the current directory from
   `sys.path` for every Python invocation -- verified safe for the build too.
2. `pirate_frb/__init__.py` detects the shadow and raises a clear, actionable
   error instead of the cryptic undefined-symbol crash.
3. `init_venv.py` runs its smoke test from a throwaway directory.

If you ever run Python in a shell WITHOUT the worktree env active (e.g. a bare
login shell where direnv has not fired), either run from inside a repo dir
(`ksgpu/` or `pirate/`, which have no shadowing child) or prefix the command
with `PYTHONSAFEPATH=1`. Any non-empty value enables it, so to turn it off you
must *unset* it -- `PYTHONSAFEPATH=0` still enables it.

## Files

- `git_repositories.toml` -- manifest of repos + branches. The git scripts are
  manifest-driven; **`init_venv.py` is not** -- when you add a repo, also add
  its build step there (see the reminder in the manifest).
- `init_toplevel.py` -- one-time: clone/checkout each repo, init submodules,
  build the `ch_dev` venv. Idempotent.
- `init_worktree.py NAME` -- create `../NAME`: worktrees of ch_dev + each repo
  (new branch NAME off each integration branch), render `.envrc` +
  `.claude/settings.json`, build the venv.
- `init_venv.py [WORKDIR] [--recreate] [--test]` -- (re)build a workspace's
  `.venv` overlay. Called by the two scripts above; also runnable standalone.
- `delete_worktree.py NAME [--force]` -- tear a feature workspace down.
- `ch_dev_helpers.py` -- shared helpers (manifest, paths, dotfile rendering).
- `dotfile_templates/` -- source templates for `.envrc` and the per-worktree
  sandbox `.claude/settings.json`.

## Quick start

    python3 init_toplevel.py                 # set up ch_dev/{ksgpu,pirate} + venv
    direnv allow .                           # activate ch_dev's venv

    python3 init_worktree.py ch_myfeature    # make ../ch_myfeature
    cd ../ch_myfeature && direnv allow .
    # once per worktree: run /sandbox in Claude, choose auto-allow mode
    tmux new -s ch_myfeature && claude

    # when done:
    python3 ~/ch_dev/delete_worktree.py ch_myfeature

## Notes

- Tmux sessions are managed by hand (no script).
- `git push` / `git fetch` are intentionally done by you, outside the sandbox
  (the sandbox denies `~/.ssh` and network). Agents commit locally.
- Per-workspace `.venv`, `.envrc`, and `.claude/settings.json` are gitignored
  (machine-specific, absolute paths).
- The toplevel `ch_dev` workspace is intentionally *not* sandboxed -- it is
  where you run these management scripts, which must write outside the dir.
