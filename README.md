# ch_dev -- personal multi-repo, multi-agent dev workspace

## Introduction

This repo is work in progress and very rough around the edges!
It's my personal system for organizing CHORD development into multiple
git worktrees, with a small number (usually one) of LLM agents per worktree.

 - Orchestration scripts for creating/deleting worktrees with pre-initialized
   dotfiles (`.envrc`, `.claude/*`), and moving commits around.
 
 - Allows multiple git repos in each worktree (currently `ch_dev`, `ksgpu`, `pirate`).
 
 - Each worktree has its own venv, which is automatically activated/deactivated.
   (For humans, this is done with `direnv`. For LLMs, this is done with `.claude/*`.)
 
 - Sandboxing: per-worktree agents run with os-level filesystem sandboxing,
   and therefore don't need to request permission very often. (The "top-level"
   ch_dev agent(s) aren't sandboxed, only the agents that run in worktrees.)

## Contents

- [Layout](#layout)
- [Quick start](#quick-start)
- [One-time setup (per machine)](#one-time-setup-per-machine)
- [Scripts](#scripts)
- [Daily workflow](#daily-workflow)
- [Sandbox and GPU (summary)](#sandbox-and-gpu-summary)
- [Gotchas](#gotchas)
- [Appendix A: cwd shadowing](#appendix-a-cwd-shadowing)
- [Appendix B: activating the per-worktree venv for an agent](#appendix-b-activating-the-per-worktree-venv-for-an-agent)
- [Appendix C: GPU compute inside the sandbox](#appendix-c-gpu-compute-inside-the-sandbox)
- [Appendix D: sandbox security trade-offs and mitigations](#appendix-d-sandbox-security-trade-offs-and-mitigations)
- [Appendix E: git commit from a worktree (shared .git)](#appendix-e-git-commit-from-a-worktree-shared-git)

## Layout

Base tree:
```
  ~/ch_dev/        -> plain clone pointed at github remote (main branch)
  ~/ch_dev/ksgpu   -> plain clone pointed at github remote (chord branch)
  ~/ch_dev/pirate  -> plain clone pointed at github remote (kms branch)
```
Worktree (named `ch_test` for concreteness):
```
  ~/ch_test/          -> git worktree pointed at ~/ch_dev
  ~/ch_test/ksgpu     -> git worktree pointed at ~/ch_dev/ksgpu
  ~/ch_test/pirate    -> git worktree pointed at ~/ch_dev/pirate
```
Note that we don't use git submodules or git subtrees.

## Quick start

    # one-time, in a fresh ch_dev clone:
    python3 init_toplevel.py                 # clone ksgpu+pirate, build ch_dev/.venv
    direnv allow .                           # activate ch_dev's venv

    # per feature:
    python3 init_worktree.py ch_myfeature    # make ../ch_myfeature (worktrees + venv)
    cd ../ch_myfeature && direnv allow .
    tmux new -s ch_myfeature && claude       # run the agent from the worktree

    # the two init_* scripts above build the .venv for you (via init_venv.py);
    # run init_venv.py directly only to REBUILD an existing workspace's venv:
    # python3 init_venv.py . --recreate      # e.g. after a dependency/build change

    # inspect all 3 repos at once (from any workspace):
    ./git-status.py                          # status + per-worktree branch relations
    ./git-diff.py [--stat|--cached|...]

    # move commits between feature and integration branches (all 3 repos);
    # both run from the worktree:
    cd ../ch_myfeature && ./git-rebase-down.py   # sync down: rebase onto integration
    cd ../ch_myfeature && ./git-merge-up.py      # land up: fast-forward integration

    # tear down (after landing):
    python3 ~/ch_dev/delete_worktree.py ch_myfeature

This assumes the machine is already set up as described next. `init_*.py` are
idempotent and safe to re-run.

## One-time setup (per machine)

The `init_*.py` scripts assume a machine prepared like this. Steps 3-4 (sandbox)
are optional -- skip them if you don't use the Claude Code sandbox.

**Prerequisites:**

- **NVIDIA GPU + CUDA toolchain** (`nvcc`): the build compiles CUDA; tests run on
  the GPU.
- **`git` >= 2.40** and **SSH access to the GitHub repos**: the manifest clones
  via a `github:` host alias in `~/.ssh/config`, so have your key in an ssh-agent.
  Needed so `init_toplevel.py` can clone, and so you can `git push`.
- **`node`/`npm`** -- only for the sandbox seccomp helper (step 3).
- **`~/.local/bin` on `$PATH`, ahead of `/usr/bin`** -- `claude`, `direnv`, and
  the bwrap shim live there.

**1. Conda toolchain env.** Create a conda env with the compiled dependencies
(cupy, cuda-nvcc, cublas/cufft/curand, mathdx, grpc-cpp + grpcio + grpcio-tools +
protoletariat, yaml-cpp, asdf, pybind11, argcomplete, setuptools=80, ...). The
authoritative list is in `ksgpu/README.md` and `pirate/notes/install.md`; roughly:

    conda create -c conda-forge -n ENVNAME \
      grpc-cpp grpcio grpcio-tools protoletariat \
      cupy mathdx pybind11 yaml-cpp asdf argcomplete setuptools=80

Nothing in ch_dev names this env; the scripts seed each `.venv` from whatever
`python` is active. Activate it in `~/.bashrc`:

    conda activate ENVNAME

**2. direnv.** Install it on `$PATH` in *every* shell, independent of which conda
env is active (do NOT put it inside a conda env -- it vanishes when a different
env, or none, is active):

    sudo apt-get install direnv        # or drop the static binary into ~/.local/bin

Add the hook to `~/.bashrc`, AFTER the `conda activate` line:

    eval "$(direnv hook bash)"

Each worktree's `.envrc` then needs a one-time `direnv allow ~/ch_<feature>`.

**3. Sandbox dependencies** (optional). Install bubblewrap (the sandbox), socat
(network proxy), and the seccomp filter (Unix-socket blocking):

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
Config tabs (not a Dependencies-only view), all deps are present.

**4. GPU inside the sandbox** (optional). Install the no-root `bwrap` shim that
makes the GPU visible inside the sandbox (the *why* is Appendix C):

    install -m 0755 misc/bwrap_shim ~/.local/bin/bwrap
    hash -r; command -v bwrap          # must print ~/.local/bin/bwrap

That is the only machine-wide GPU step. The matching per-worktree settings are
rendered automatically by `init_worktree.py` (Appendix C/D). After it, launch
`claude` from a worktree and `nvidia-smi`, `pirate_frb test -n 1`, and cupy all
run on the GPU.

## Scripts

- `git_repositories.toml` -- manifest of repos + integration branches. The git
  scripts are manifest-driven; **`init_venv.py` is not** -- its `BUILD` list is
  separate, so when you add a repo, add it there too (see the reminder in the
  manifest).
- `init_toplevel.py` -- one-time: clone/checkout each repo, init submodules,
  build the `ch_dev` `.venv`. Idempotent.
- `init_worktree.py NAME [--no-venv]` -- create `../NAME`: a worktree of ch_dev +
  each repo (new branch NAME off each integration branch), render the dotfiles,
  build the `.venv`.
- `init_venv.py [WORKDIR] [--recreate] [--test]` -- (re)build a workspace's
  `.venv` overlay. Called by the two scripts above; also runnable standalone.
- `delete_worktree.py NAME [--force]` -- tear a feature workspace down (keeps the
  feature branches; `--force` overrides the dirty-tree check).
- `git-status.py` / `git-diff.py [ARGS...]` -- run `git status` / `git diff`
  across all 3 repos in the current workspace, under per-repo headers (extra args
  pass through to git). `git-status.py` also prints how each worktree branch
  relates to its integration branch, e.g. `pirate/ch_evrb is 2 commits ahead of
  pirate/kms`.
- `git-rebase-down.py [--dry-run]` -- in a WORKTREE: rebase this feature's branch
  onto each repo's integration branch (sync down). `git-merge-up.py [--dry-run]
  [--no-ff]` -- also in the WORKTREE: fast-forward this feature onto each repo's
  integration branch (land up; the merge itself runs in the toplevel checkout,
  where the integration branch lives). See "Branch workflow" below.
- `ch_dev_helpers.py` -- shared helpers (manifest, paths, dotfile rendering,
  the multi-repo git logic).
- `dotfile_templates/` -- source templates for `.envrc`, `.claude/env.sh`, and
  the per-worktree sandbox `.claude/settings.json`. `render_dotfiles` substitutes
  `{{WORKTREE}}`, `{{UID}}`, and the shared-`.git` paths (Appendix D/E).
- `misc/bwrap_shim` -- no-root GPU shim for the sandbox (setup step 4, Appendix C).

## Daily workflow

**Run the agent from inside the worktree.** `cd ~/ch_<feature>` (direnv fires,
activating the venv and exporting `CLAUDE_ENV_FILE`), then `claude`. Verify with
`which python` -> `~/ch_<feature>/.venv/bin/python`. Launching from elsewhere
breaks venv activation for the agent (Appendix A).

**Committing.** A commit in a worktree is immediately part of each repo's shared
history (no inter-worktree push). Commit per-repo as usual, or use `git-status.py`
to see all 3 at once. In a sandboxed worktree, `git commit` works without a
prompt (Appendix E).

**Branch workflow (rebase-then-fast-forward).** Each feature is the same branch
name across all 3 repos; the integration branches are `main`/`chord`/`kms`. Two
helpers move commits between a feature branch and its integration branch, keeping
history linear (feature commits land individually, no merge bubbles). BOTH run
from the worktree, and each infers the feature branch from what is checked out
there (no branch-name argument):

    # sync down: rebase the feature branch onto latest integration, per repo.
    # Run whenever an integration branch has moved.
    cd ~/ch_<feature> && ./git-rebase-down.py        # --dry-run to preview

    # land up: fast-forward the feature onto each integration branch (only after
    # a clean rebase-down). The merge runs in the toplevel checkout, where the
    # integration branch is checked out -- the output shows that path.
    cd ~/ch_<feature> && ./git-merge-up.py           # --dry-run to preview

Both skip repos that need nothing (`git-status.py` shows which do). `--ff-only`
(the default for `git-merge-up.py`) refuses rather than create a merge commit if
the integration branch moved since you rebased -- just rebase-down again and
retry. Landing does NOT delete the worktree (worktrees are persistent here); if
you do want to tear one down, run from the toplevel:

    python3 ~/ch_dev/delete_worktree.py ch_<feature>

It refuses (in any of the 3 repos) if the worktree has uncommitted changes,
stray untracked files, or commits not yet merged up -- then deletes each repo's
feature branch with `git branch -d` (which itself refuses an unmerged branch, so
nothing committed is lost). `--force` overrides the dir checks but still keeps
any unmerged branch.

*Conflicts during rebase-down.* Rebase replays the feature's commits one at a
time onto the integration branch, so a conflict stops at the FIRST offending
commit (you may hit several in turn, one resolution each -- unlike merge's single
combined resolution). `git-rebase-down.py` does not auto-resolve: it prints
git's conflict message, leaves that repo in the rebase-in-progress state, and
exits non-zero (a conflict in one repo does NOT roll back repos that already
rebased cleanly). Finish by hand, with plain git, in the repo it stopped in:

    cd ~/ch_<feature>/<repo>         # the repo named in the error
    # edit the conflicted files (look for <<<<<<< markers), then:
    git add <resolved-files>
    git rebase --continue            # replays the next commit; repeat if it conflicts
    # or, to bail out completely (returns the branch to its pre-rebase state):
    git rebase --abort

Do NOT re-run `./git-rebase-down.py` to resume -- it would try to start a fresh
rebase, which git refuses mid-rebase. Use `git rebase --continue`/`--abort`
directly. `git rebase --abort` is always safe: a rebase is fully undoable until
it finishes, so it is safe to attempt one just to see the conflicts.

**Pushing / fetching is done by you, outside the sandbox.** The sandbox denies
`~/.ssh` and network egress, so the agent commits locally only; you `git push` /
`git fetch` from your own shell when ready.

**The toplevel `ch_dev` is intentionally NOT sandboxed** -- it is where you run
these management scripts, which must write outside their own directory (clone
repos, create sibling worktrees). Feature worktrees ARE sandboxed.

## Sandbox and GPU (summary)

Feature-worktree `.claude/settings.json` (rendered by `init_worktree.py`) is set
up so an agent can do real work -- including GPU compute -- with minimal prompts:

- **`permissions.defaultMode: "acceptEdits"`** -- file edits auto-accept;
  sandboxed Bash auto-runs (the sandbox boundary is the safety layer). You are
  still prompted only for genuine escapes (a new network domain, or a command
  that falls back to running unsandboxed).
- **GPU compute works** -- via the machine-wide shim (setup step 4) plus
  per-worktree settings. Two distinct barriers had to be removed; see Appendix C.
- **Security mitigations** offset the one broad setting GPU compute requires
  (`allowAllUnixSockets`); see Appendix D.
- **`git commit` works** without escaping the sandbox; see Appendix E.

These are machine-specific (absolute paths, your UID), so the rendered
`.venv`, `.envrc`, and `.claude/{env.sh,settings.json}` are gitignored; only the
templates are tracked.

## Gotchas

- **cwd shadowing.** Running Python from a workspace root can make `import ksgpu`
  pick up the `ksgpu/` *directory* instead of the installed package, with a
  cryptic `undefined symbol` failure downstream. Three guards make this invisible
  in normal use; full mechanism and the manual escape hatch in Appendix A.

--------------------------------------------------------------------------------

# Appendix A: cwd shadowing

Because the layout nests the repos under the workspace root, the root contains a
directory named `ksgpu/` -- the same name as the `ksgpu` Python package. Python
puts the current directory at the front of `sys.path` (`python -c`, `python -m`,
and the REPL use the cwd; `python script.py` uses the script's dir). So running
Python *from the workspace root* makes `import ksgpu` pick up that `ksgpu/`
directory as an empty PEP 420 namespace package, shadowing the editable-installed
package. Its `__init__.py` -- and the ctypes trick that publishes ksgpu's C++
symbols with `RTLD_GLOBAL` -- never runs, and `import pirate_frb` then fails with
a cryptic `undefined symbol: ksgpu::convert_array_from_python`. Activating the
venv does NOT help: the cwd entry sits ahead of site-packages regardless.
(`pirate`'s checkout dir is `pirate` but its package is `pirate_frb`, so it is
never *directly* shadowed -- it only fails transitively via `ksgpu`.)

Three layers guard against this, so you normally never see it:

1. Each worktree's `.envrc` (for you) and `.claude/env.sh` + `settings.json` env
   (for agents) set `PYTHONSAFEPATH=1`, which drops the current directory from
   `sys.path` for every Python invocation -- verified safe for the build too.
2. `pirate_frb/__init__.py` detects the shadow and raises a clear, actionable
   error instead of the cryptic undefined-symbol crash.
3. `init_venv.py` runs its smoke test from a throwaway directory.

If you ever run Python in a shell WITHOUT the worktree env active (e.g. a bare
login shell where direnv has not fired), either run from inside a repo dir
(`ksgpu/` or `pirate/`, which have no shadowing child) or prefix the command with
`PYTHONSAFEPATH=1`. Any non-empty value enables it; to turn it off you must
*unset* it -- `PYTHONSAFEPATH=0` still enables it.

# Appendix B: activating the per-worktree venv for an agent

Activating the venv for an *agent* is trickier than for a human. Claude Code
sources `~/.bashrc` (your conda activation) once at session start, does NOT
persist env between Bash commands, and its `settings.json` `env` values are NOT
variable-expanded -- so `"PATH": ".venv/bin:${PATH}"` would be set to that literal
string and clobber PATH (dropping `~/.local/bin`, where `claude` lives). The
mechanism that works is Claude's **`CLAUDE_ENV_FILE`**: a script Claude sources
before every Bash command, where `$PATH` *does* expand.

- `.envrc` exports `CLAUDE_ENV_FILE="$PWD/.claude/env.sh"`.
- `.claude/env.sh` (generated) does `export PATH="<worktree>/.venv/bin:$PATH"`
  (plus `VIRTUAL_ENV`, `PYTHONSAFEPATH`, and the sandbox env `CUPY_CACHE_DIR` +
  `unset SSH_AUTH_SOCK`). It is sourced *after* bashrc's conda activation, so the
  venv wins.

Hence "launch `claude` from the worktree": it inherits `CLAUDE_ENV_FILE` from
the `.envrc` direnv already loaded. `settings.json` `env` still sets
`VIRTUAL_ENV` + `PYTHONSAFEPATH`, but it cannot set PATH.

The `init_*` scripts themselves also feel `PYTHONSAFEPATH=1`: once direnv has run
in ch_dev, a bare `import ch_dev_helpers` would fail (the script dir is dropped
from `sys.path`), so each entry-point script prepends its own directory to
`sys.path` before importing.

# Appendix C: GPU compute inside the sandbox

Claude's Bash sandbox (bubblewrap) blocks GPU *compute* via two independent
barriers. Both must be removed; the fixes are orthogonal and both wired into the
setup (machine-wide shim + per-worktree template).

Symptom -> barrier:

    nvidia-smi fails ("couldn't communicate with the NVIDIA driver")  -> Barrier 1
    nvidia-smi works, but cudaSetDevice/compute fails with code 304    -> Barrier 2

**Barrier 1 -- device nodes (the shim).** The sandbox builds a fresh `/dev` with
`bwrap --dev /dev`, a minimal devtmpfs that does NOT contain the `/dev/nvidia*`
nodes, so CUDA sees no devices. There is no `settings.json` knob for device binds
(the sandbox even drops `/dev/*` entries from `allowWrite`). The fix is a thin
shim around `bwrap` (`misc/bwrap_shim`) that injects
`--dev-bind-try /dev/nvidiaX /dev/nvidiaX` for each GPU node immediately after the
`--dev /dev` that creates the fresh devtmpfs (the binds MUST come after it, or the
fresh mount shadows them). Claude resolves the bwrap binary through `$PATH` (it
spawns `bwrap` unqualified; the `bwrapPath` setting is managed-only), so a shim at
`~/.local/bin/bwrap` -- ahead of `/usr/bin` -- intercepts it with NO root. The
shim is a no-op for bwrap calls that don't create a fresh `/dev`. (A root
`dpkg-divert` install is possible but unnecessary; the shim header documents it.)

**Barrier 2 -- the seccomp stage (`allowAllUnixSockets`).** Even with the nodes
present, CUDA context init fails: `cudaSetDevice(...) returned 304` (OS call
failed). To enforce its Unix-socket block, the sandbox wraps the command in
`apply-seccomp`, which creates a nested PID + mount namespace and remounts
`/proc`. NVIDIA's UVM / CUDA context init does not survive that nesting and
returns 304. (`nvidia-smi` is unaffected: it opens no CUDA context, so no UVM.)
The fix is `"network": { "allowAllUnixSockets": true }` in the worktree
`settings.json`, which skips the `apply-seccomp` stage entirely. This is a
first-class sandbox-runtime key; it was preferred over patching/forking
`apply-seccomp` (a maintained binary kept in sync on every upgrade, and the exact
sub-step that breaks UVM was never isolated). The template sets it, along with
`CUPY_CACHE_DIR=/tmp/cupy_cache` (cupy's default `~/.cupy` is read-only in the
sandbox; `/tmp` is writable).

Re-verify after upgrading `@anthropic-ai/sandbox-runtime` or Claude Code: the
repro is the outer bwrap with vs without `apply-seccomp` around
`ksgpu.set_cuda_device(0)`.

# Appendix D: sandbox security trade-offs and mitigations

The two GPU fixes weaken the sandbox in specific ways. For a trusted single-user
dev box these are acceptable trades, but know what they are. Filesystem, network,
and secret-file isolation (`~/.ssh`, etc.) are otherwise unchanged.

**The shim exposes the GPU to every bubblewrap sandbox you run** (not just
Claude), since it intercepts `bwrap` on `$PATH`. The injection only fires when a
`--dev` arg is present, which limits it, but keep the shim minimal and audited --
it is code in your sandbox's trusted setup path.

**`allowAllUnixSockets` disables the sandbox's block on connecting to host
Unix-domain sockets.** That block's job is to stop a sandboxed process from
reaching host services over `AF_UNIX`. The two that matter here are re-closed by
the template:

- **ssh-agent** -- `.claude/env.sh` does `unset SSH_AUTH_SOCK`. This is the
  primary, path-independent guard: ssh/git/ssh-add then find no agent regardless
  of socket path (including the unpredictable `/tmp/ssh-XXXX` that
  `eval $(ssh-agent)` creates, which `denyRead` can't target). Costs nothing --
  agents commit locally; you push/fetch outside the sandbox.
- **docker socket** -- `denyRead` masks `/run/docker.sock` (membership in the
  `docker` group makes it root-equivalent). One entry covers both `/run` and the
  `/var/run -> /run` symlink; do NOT also list `/var/run/docker.sock` -- bwrap
  can't make a mountpoint through the symlink and sandbox setup then fails.
- **ssh-agent fixed path** -- `denyRead` also masks
  `/run/user/<UID>/ssh-agent.socket` (the predictable systemd path) as
  belt-and-suspenders. `render_dotfiles` fills `<UID>` from `os.getuid()`.

**Residual risk (accepted):** `unset SSH_AUTH_SOCK` defeats *cooperative* clients
-- the real threat, your own agent misusing a key. It does NOT stop code that
deliberately scans `/tmp` + `/run` for socket inodes and connects by raw path.
Closing that means re-enabling the AF_UNIX block, which re-breaks CUDA -- the same
trade as exposing the GPU at all.

# Appendix E: `git commit` from a worktree (shared .git)

A commit in a feature worktree writes to each repo's SHARED `.git` common-dir,
which in this nested layout lives in the main checkout (`ch_dev/.git`,
`ch_dev/ksgpu/.git`, `ch_dev/pirate/.git`) -- OUTSIDE the worktree, so read-only
under the sandbox by default. The agent would otherwise be prompted for every
commit (and Claude's built-in "allow the worktree's shared `.git`" handles only
the normal sibling layout, not these three nested dirs).

`render_dotfiles` resolves those common-dirs (`git rev-parse --git-common-dir`,
kept only when outside the worktree) and templates them into the worktree
`settings.json`:

- **`allowWrite`** the shared `.git` dirs -> `git commit` works with no prompt.
- **`denyWrite`** each dir's `hooks/` and `config`. This matters: those are
  code/settings that execute in YOUR unsandboxed shell, and because they sit
  outside the worktree, the sandbox's built-in hooks/config denial (which scans
  only the cwd) does not cover them -- so we mask them explicitly. Verified: a
  commit succeeds, while overwriting `.git/config` or planting a
  `.git/hooks/post-commit` are both blocked.

Note the residual: the agent can write the shared object store and refs of the
main checkouts, so it could in principle rewrite refs/history there (not just in
its own worktree). `config`/`hooks` are protected; history is not.

For a plain checkout (toplevel `ch_dev`), `.git` is inside the dir and already
writable, so these placeholders render empty.
