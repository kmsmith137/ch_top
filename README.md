# ch_dev -- personal multi-repo, multi-agent dev workspace

Personal "container" repo holding the scripts that manage a multi-repo software
workspace (currently `ksgpu` + `pirate`) and spin up isolated per-feature
worktrees for running coding agents.

Full design rationale: `plans/multi_agent_workspace.md`.

## Setup (one-time, per machine)

These are the things `init_*.py` do NOT do -- the scripts assume a machine
already set up like this. Steps 3-4 (sandbox) are optional; skip them if you
don't use the Claude Code sandbox.

**Prerequisites (must already be present):**

- An **NVIDIA GPU + CUDA toolchain** (`nvcc`): the build compiles CUDA and the
  tests run on the GPU.
- **`git` >= 2.40** (for worktree+submodule support) and **SSH access to the
  GitHub repos**: the manifest clones via the `github:` host alias in
  `~/.ssh/config`, so have your key loaded in an ssh-agent -- needed so
  `init_toplevel.py` can clone and so you can `git push`. (Pushes are always done
  by you, never by a sandboxed agent.)
- **`node`/`npm`** -- only needed for the sandbox seccomp helper (step 3).
- **`~/.local/bin` on `$PATH`, ahead of `/usr/bin`** -- the `claude` binary lives
  there, and direnv and the bwrap shim get installed there below.

**1. Conda toolchain env.** Create a conda env with the compiled dependencies
(cupy, cuda-nvcc, cublas/cufft/curand, mathdx, grpc-cpp + grpcio + grpcio-tools +
protoletariat, yaml-cpp, asdf, pybind11, argcomplete, setuptools=80, ...). The
authoritative `conda create` line lives in `ksgpu/README.md` and
`pirate/notes/install.md` (or use `pirate/environment.yml`); roughly:

    conda create -c conda-forge -n ENVNAME \
      grpc-cpp grpcio grpcio-tools protoletariat \
      cupy mathdx pybind11 yaml-cpp asdf argcomplete setuptools=80

Nothing in ch_dev names this env; the scripts seed each `.venv` from whatever
`python` is active -- so activate it in `~/.bashrc`:

    conda activate ENVNAME

**2. direnv.** Install it somewhere on `$PATH` in *every* shell, independent of
which conda env is active (do NOT put it inside a conda env -- it disappears when
a different env, or none, is active):

    sudo apt-get install direnv        # or drop the static binary into ~/.local/bin

Add the hook to `~/.bashrc`, AFTER your `conda activate` line:

    eval "$(direnv hook bash)"

(Each worktree's `.envrc` then needs a one-time `direnv allow ~/ch_X` -- see
Quick start.)

**3. Claude Code sandbox dependencies** (optional). Install bubblewrap (the
sandbox), socat (network proxy), and the seccomp filter (Unix-socket blocking,
which closes the `$SSH_AUTH_SOCK` / `docker.sock` hole):

    sudo apt-get install bubblewrap socat
    sudo npm install -g @anthropic-ai/sandbox-runtime

On Ubuntu 24.04+ the default AppArmor policy blocks the unprivileged user
namespaces bwrap needs. If `sysctl kernel.apparmor_restrict_unprivileged_userns`
returns `1`, add a profile granting bwrap the `userns` capability:

    sudo tee /etc/apparmor.d/bwrap >/dev/null <<'EOF'
    abi <abi/4.0>,
    include <tunables/global>
    profile bwrap /usr/bin/bwrap flags=(unconfined) {
      userns,
      include if exists <local/bwrap>
    }
    EOF
    sudo systemctl reload apparmor

Verify: run `/sandbox` in Claude. If it shows the normal Mode / Overrides /
Config tabs (and NOT a Dependencies-only view), all deps are present.

**4. GPU inside the sandbox** (optional). Claude's sandbox builds a fresh `/dev`
without the `/dev/nvidia*` nodes, so CUDA fails inside it, and there is no
`settings.json` knob to fix it. Install the **no-root** `bwrap` shim
(`misc/bwrap_shim`), which Claude picks up via `$PATH` (it spawns `bwrap`
unqualified) and which binds the GPU nodes into the sandbox. Full story:
`plans/gpu_solution1.md`.

    install -m 0755 misc/bwrap_shim ~/.local/bin/bwrap
    hash -r; command -v bwrap          # must print ~/.local/bin/bwrap

Then launch `claude` from the worktree and `nvidia-smi` / GPU code work in the
sandbox. (cupy's kernel cache wants a writable dir; the sandbox makes `/tmp`
writable, so set `export CUPY_CACHE_DIR=/tmp/cupy_cache` in the agent env if
needed. Security note: this exposes the GPU to every bubblewrap sandbox you run;
filesystem/network/secret isolation is unchanged.)

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

## Claude Code + the venv

Activating the per-worktree venv for an *agent* is trickier than for a human.
Claude Code sources `~/.bashrc` (your conda activation) once at session start,
does NOT persist env between Bash commands, and its `settings.json` `env` values
are NOT variable-expanded -- so `"PATH": ".venv/bin:${PATH}"` gets set to that
literal string and clobbers PATH (dropping `~/.local/bin`, where `claude`
lives). The mechanism that works is Claude's **`CLAUDE_ENV_FILE`**: a script
Claude sources before every Bash command, where `$PATH` *does* expand. So:

- `.envrc` exports `CLAUDE_ENV_FILE="$PWD/.claude/env.sh"`.
- `.claude/env.sh` (generated) does `export PATH="<worktree>/.venv/bin:$PATH"`
  (plus `VIRTUAL_ENV`, `PYTHONSAFEPATH`). It is sourced *after* bashrc's conda
  activation, so the venv wins.

**Launch `claude` from the worktree** (`cd ~/ch_X` with direnv active, then
`claude`) so it inherits `CLAUDE_ENV_FILE`. Verify inside the agent with
`which python` -> it should be `~/ch_X/.venv/bin/python`. (`settings.json` still
sets `VIRTUAL_ENV` + `PYTHONSAFEPATH`, but it cannot set PATH.)

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
- `dotfile_templates/` -- source templates for `.envrc`, `.claude/env.sh`, and
  the per-worktree sandbox `.claude/settings.json`.
- `misc/bwrap_shim` -- no-root GPU shim for the Claude Code sandbox (Setup
  step 4; see `plans/gpu_solution1.md`).

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
