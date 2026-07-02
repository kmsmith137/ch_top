# ch_top -- personal multi-repo, multi-agent dev workspace

## Introduction

This repo is work in progress and very rough around the edges!
It's my personal system for organizing CHORD development into multiple
git worktrees, with a small number (usually one) of LLM agents per worktree.

 - Orchestration scripts for creating/deleting worktrees with pre-initialized
   dotfiles (`.envrc`, `.claude/*`), and moving commits around.
 
 - Allows multiple git repos in each worktree (currently `ch_top`, `pipmake`, `ksgpu`, `pirate`).
 
 - Each worktree has its own venv, which is automatically activated/deactivated.
   (For humans, this is done with `direnv`. For LLMs, this is done with `.claude/*`.)
 
 - Sandboxing: per-worktree agents run inside a rootless-Podman container
   (launched with `./sbox-claude`) under `--dangerously-skip-permissions`, so they
   do real work -- including GPU compute -- with no permission prompts, while
   being unable to read your secrets or escape the container. (The toplevel
   agent(s) in `top` aren't containerized, only the agents that run in worktrees.)

## Contents

- [Layout](#layout)
- [Quick start](#quick-start)
- [One-time setup (per machine)](#one-time-setup-per-machine)
- [Scripts](#scripts)
- [Daily workflow](#daily-workflow)
- [Sandbox and GPU (summary)](#sandbox-and-gpu-summary)
- [Egress proxy (network allowlist)](#egress-proxy-network-allowlist)
- [Gotchas](#gotchas)
- [Appendix A: cwd shadowing](#appendix-a-cwd-shadowing)
- [Appendix B: activating the per-worktree venv for an agent](#appendix-b-activating-the-per-worktree-venv-for-an-agent)
- [Appendix C: GPU compute inside the container](#appendix-c-gpu-compute-inside-the-container)
- [Appendix D: container sandbox security trade-offs](#appendix-d-container-sandbox-security-trade-offs)
- [Appendix E: git commit from a worktree (shared .git)](#appendix-e-git-commit-from-a-worktree-shared-git)
- [Appendix F: richer egress-approval options (B-D, not implemented)](#appendix-f-richer-egress-approval-options-b-d-not-implemented)

## Layout

The toplevel clone and its feature worktrees live together as siblings inside a
**grouping dir** -- any directory except `$HOME` itself (call it `$CH`; `~/ch` in
these examples). `init-worktree` refuses to run if the toplevel sits directly in
`$HOME`, since the sibling worktrees it creates would then land in `$HOME`.

Paths within the workspace are written **relative to the grouping dir** below: the
grouping-dir name is arbitrary, relative paths read the same inside the sandbox
container, and only fixed system/home paths (`~/.ssh`, `~/miniforge3`, ...) are
absolute. The container repo is `ch_top`, cloned into the toplevel dir `top`.
Contents of `$CH`:
```
  top/         -> plain clone of ch_top (main branch)  [the "toplevel"]
  top/pipmake  -> plain clone (main branch)
  top/ksgpu    -> plain clone (chord branch)
  top/pirate   -> plain clone (kms branch)
  dev/         -> a feature worktree of top (one per feature)
  dev/pipmake  -> git worktree of top/pipmake
  dev/ksgpu    -> git worktree of top/ksgpu
  dev/pirate   -> git worktree of top/pirate
  claude/      -> the sandboxed agent's CLAUDE_CONFIG_DIR (.claude.json,
                  .credentials.json, projects/; per-group, see "Sandbox and GPU")
  extern/      -> external reference source trees (chord-frb-sifter, bonsai, simd_helpers, rf_kernels)
```
We don't use git submodules or git subtrees.

## Quick start

    # one-time: make the grouping dir and clone the container repo into ./top:
    mkdir ~/ch && cd ~/ch
    git clone github:kmsmith137/ch_top top   # ch_top -> the toplevel dir 'top'
    cd top
    ./init-toplevel                          # clone pipmake+ksgpu+pirate, build top/.venv
    direnv allow .                           # activate top's venv

    # per feature (run from the toplevel ~/ch/top):
    ./init-worktree dev                      # make ../dev (worktrees + venv)
    cd ../dev && direnv allow .
    tmux new -s dev && ./sbox-claude         # run the sandboxed agent (claude in a container)

    # the two init-* scripts above build the .venv for you;
    # run init-venv directly only to REBUILD an existing workspace's venv:
    # ./init-venv . --recreate               # e.g. after a dependency/build change

    # inspect all 4 repos at once (from any workspace):
    ./git-status                             # status + per-worktree branch relations
    ./git-diff [--stat|--cached|...]

    # move commits between feature and integration branches (all 4 repos);
    # both run from the worktree:
    cd ../dev && ./git-rebase-down           # sync down: rebase onto integration
    cd ../dev && ./git-merge-up              # land up: fast-forward integration

    # tear down (after landing; run from outside the worktree, e.g. the toplevel):
    ~/ch/top/delete-worktree dev

This assumes the machine is already set up as described next. `init-*` are
idempotent and safe to re-run.

## One-time setup (per machine)

The `init-*` scripts assume a machine prepared like this. Step 3 (Podman) is
only needed for the per-worktree agent sandbox -- skip it if you only use the
unsandboxed toplevel.

**Prerequisites:**

- **NVIDIA GPU + CUDA toolchain** (`nvcc`): the build compiles CUDA; tests run on
  the GPU.
- **`git` >= 2.40** and **SSH access to the GitHub repos**: the manifest clones
  via a `github:` host alias in `~/.ssh/config`, so have your key in an ssh-agent.
  Needed so `init-toplevel` can clone, and so you can `git push`.
- **rootless Podman** -- the per-worktree sandbox (step 3). On this host it works
  with no `/etc/subuid`, no `docker` group, and no root.
- **`~/.local/bin` on `$PATH`, ahead of `/usr/bin`** -- `claude` and `direnv`
  live there.

**1. Conda toolchain env.** Create a conda env with the compiled dependencies
(cupy, cuda-nvcc, cublas/cufft/curand, mathdx, grpc-cpp + grpcio + grpcio-tools +
protoletariat, yaml-cpp, asdf, pybind11, argcomplete, setuptools=80, ...). The
authoritative list is in `ksgpu/README.md` and `pirate/notes/install.md`; roughly:

    conda create -c conda-forge -n ENVNAME \
      grpc-cpp grpcio grpcio-tools protoletariat \
      cupy mathdx pybind11 yaml-cpp asdf argcomplete setuptools=80

Nothing in ch_top names this env; the scripts seed each `.venv` from whatever
`python` is active (and the sandbox launcher bakes in the active `CONDA_PREFIX`).
Activate it in `~/.bashrc`:

    conda activate ENVNAME

**2. direnv.** Install it on `$PATH` in *every* shell, independent of which conda
env is active (do NOT put it inside a conda env -- it vanishes when a different
env, or none, is active):

    sudo apt-get install direnv        # or drop the static binary into ~/.local/bin

Add the hook to `~/.bashrc`, AFTER the `conda activate` line:

    eval "$(direnv hook bash)"

Each worktree's `.envrc` then needs a one-time `direnv allow ~/ch/<feature>`.

**3. Sandbox (rootless Podman)** (optional). The per-worktree agent runs inside a
rootless-Podman container. On this host Podman needs no special setup -- no
`/etc/subuid`/`/etc/subgid` ranges, no `docker` group, no root (it uses a
single-id user namespace, so container `uid 0` maps to your host user). Install it
and pull the base image:

    sudo apt-get install podman        # or have podman on $PATH
    podman pull docker.io/library/ubuntu:24.04

`sbox-claude` pulls the image for you on first use, so the explicit pull is
optional. The base image **must match the host distro** (Ubuntu 24.04): the
container overlays the host `/usr` read-only to get your real toolchain + NVIDIA
driver libs, so a mismatched glibc breaks the dynamic loader. Bump the `IMAGE=`
line in `sbox-claude` when you upgrade the host.

Verify: `podman run --rm docker.io/library/ubuntu:24.04 true` exits 0. GPU compute
then works automatically (device passthrough + host CUDA libs) -- no shim, no
seccomp tweak, no `nvidia-container-toolkit`; see Appendix C.

## Scripts

- `git_repositories.toml` -- manifest of repos + integration branches. The git
  scripts are manifest-driven; **the venv build is not** -- the `BUILD` list (in
  `ch_top_helpers.py`) is separate, so when you add a repo, add it there too (see
  the reminder in the manifest).
- `init-toplevel` -- one-time: clone/checkout each repo, init submodules,
  build the `top` `.venv`. Idempotent.
- `init-worktree NAME [--no-venv]` -- create `../NAME`: a worktree of top +
  each repo (new branch NAME off each integration branch), render the dotfiles +
  the sandbox launcher, ensure the base image is present, build the `.venv`.
- `init-venv [WORKDIR] [--recreate] [--test]` -- (re)build a workspace's `.venv`
  overlay. A thin CLI wrapper around `ch_top_helpers.build_venv()`, which
  `init-toplevel`/`init-worktree` call directly; also runnable standalone.
- `delete-worktree NAME [--force]` -- tear a feature workspace down (keeps the
  feature branches; `--force` overrides the dirty-tree check).
- `git-status` / `git-diff [ARGS...]` -- run `git status` / `git diff`
  across all 4 repos in the current workspace, under per-repo headers (extra args
  pass through to git). `git-status` also prints how each worktree branch
  relates to its integration branch, e.g. `dev/pirate is 2 commits ahead of
  top/pirate (kms branch)`; repos already up-to-date are omitted (a fully
  up-to-date worktree collapses to a single line).
- `git-rebase-down [--dry-run]` -- in a WORKTREE: rebase this feature's branch
  onto each repo's integration branch (sync down). `git-merge-up [--dry-run]
  [--no-ff]` -- also in the WORKTREE: fast-forward this feature onto each repo's
  integration branch (land up; the merge itself runs in the toplevel checkout,
  where the integration branch lives). See "Branch workflow" below.
- `ch_top_helpers.py` -- shared helpers (manifest, paths, dotfile rendering, the
  multi-repo git logic, and `build_venv`). Imported by the other scripts, so it
  stays a `.py` module (the runnable entry-point scripts are hyphenated and
  extension-less).
- `sbox-common.sh` -- the shared setup **sourced** by both sandbox launchers below:
  self-locates the worktree, inherits your shell's `PATH` + `CONDA_PREFIX`, reads the
  `sandbox/` policy, starts the egress proxy, and builds the rootless-Podman
  invocation (mounts, env, devices). Refuses to run from the toplevel. A sourced
  library, so it keeps its `.sh` extension while the launchers stay extension-less
  (same convention as `ch_top_helpers.py`).
- `sbox-claude` -- thin launcher (tracked; run from a feature worktree,
  `./sbox-claude`): sources `sbox-common.sh`, then runs `claude
  --dangerously-skip-permissions` in the container. Extra args pass through to claude.
- `sbox-shell` -- thin launcher (`./sbox-shell`): the **same** container as
  `sbox-claude` but runs an interactive `bash` instead -- a shell that "sees what
  claude sees" (identical mounts, env, network, devices, egress proxy), for poking at
  the sandbox. Its rcfile is `~/.bashrc` + the worktree's `.claude/env.sh`, so the
  env matches what claude's Bash tool runs each command in.
- `sbox-net` -- the egress filtering proxy + approval CLI (also tracked, run on the
  host). Routes the agent's HTTP/HTTPS through a per-group domain allowlist;
  `sbox-net allow <domain>` approves a blocked domain, `sbox-net deny <domain>`
  remembers a block, `sbox-net start|stop|status|log|url` manage the proxy. See
  "Egress proxy".
- `dotfile_templates/` -- source templates for `.envrc` and `.claude/env.sh`
  (venv activation); `render_dotfiles` substitutes `{{WORKTREE}}`.
- `sandbox/` -- editable policy, read at every launch from the TOPLEVEL top (so
  edits apply to every worktree in the group, no re-render): `fs-allow.txt` (the
  default-deny filesystem allowlist -- `ro`/`rw <path>`; unlisted paths are absent
  in the container), `devices.txt` (device nodes; default: all GPUs),
  `env-allow.txt` (preference env vars -- editor, locale, pager, ... -- forwarded
  by name from your launching shell; structural/secret vars are not), and
  `net-allow.txt` / `net-deny.txt` (the egress domain allow/deny lists used by
  `sbox-net`). See Appendices C-F.

## Daily workflow

**Run the agent from inside the worktree.** `cd ~/ch/<feature>` (direnv fires,
activating the venv and exporting `CLAUDE_ENV_FILE`), then `./sbox-claude`. This
launches `claude` inside the worktree's rootless-Podman sandbox; inside it,
`which python` -> `~/ch/<feature>/.venv/bin/python`. Launching from elsewhere
breaks venv activation for the agent (Appendix A/B). To get an *unsandboxed* shell
in the worktree instead, run plain `claude`.

The sandbox authenticates per **grouping dir** (`CLAUDE_CONFIG_DIR`), separately
from your personal `~/.claude`. The first time you launch an agent in a new
grouping dir there is no token yet, so run `/login` inside it once; every worktree
in that grouping dir then shares the login. See Appendix D.

**Committing.** A commit in a worktree is immediately part of each repo's shared
history (no inter-worktree push). Commit per-repo as usual, or use `git-status`
to see all 4 at once. From inside the sandbox, `git commit` works without a
prompt (Appendix E).

**Branch workflow (rebase-then-fast-forward).** Each feature is the same branch
name across all 4 repos; the integration branches are `main` (top, pipmake),
`chord` (ksgpu), `kms` (pirate). Two
helpers move commits between a feature branch and its integration branch, keeping
history linear (feature commits land individually, no merge bubbles). BOTH run
from the worktree, and each infers the feature branch from what is checked out
there (no branch-name argument):

    # sync down: rebase the feature branch onto latest integration, per repo.
    # Run whenever an integration branch has moved.
    cd ~/ch/<feature> && ./git-rebase-down        # --dry-run to preview

    # land up: fast-forward the feature onto each integration branch (only after
    # a clean rebase-down). The merge runs in the toplevel checkout, where the
    # integration branch is checked out -- the output shows that path.
    cd ~/ch/<feature> && ./git-merge-up           # --dry-run to preview

Both skip repos that need nothing (`git-status` shows which do). `--ff-only`
(the default for `git-merge-up`) refuses rather than create a merge commit if
the integration branch moved since you rebased -- just rebase-down again and
retry. Landing does NOT delete the worktree (worktrees are persistent here); if
you do want to tear one down, run from the toplevel:

    ~/ch/top/delete-worktree <feature>

It refuses (in any of the 4 repos) if the worktree has uncommitted changes,
stray untracked files, or commits not yet merged up -- then deletes each repo's
feature branch with `git branch -d` (which itself refuses an unmerged branch, so
nothing committed is lost). `--force` overrides the dir checks but still keeps
any unmerged branch.

*Conflicts during rebase-down.* Rebase replays the feature's commits one at a
time onto the integration branch, so a conflict stops at the FIRST offending
commit (you may hit several in turn, one resolution each -- unlike merge's single
combined resolution). `git-rebase-down` does not auto-resolve: it prints
git's conflict message, leaves that repo in the rebase-in-progress state, and
exits non-zero (a conflict in one repo does NOT roll back repos that already
rebased cleanly). Finish by hand, with plain git, in the repo it stopped in:

    cd ~/ch/<feature>/<repo>         # the repo named in the error
    # edit the conflicted files (look for <<<<<<< markers), then:
    git add <resolved-files>
    git rebase --continue            # replays the next commit; repeat if it conflicts
    # or, to bail out completely (returns the branch to its pre-rebase state):
    git rebase --abort

Do NOT re-run `./git-rebase-down` to resume -- it would try to start a fresh
rebase, which git refuses mid-rebase. Use `git rebase --continue`/`--abort`
directly. `git rebase --abort` is always safe: a rebase is fully undoable until
it finishes, so it is safe to attempt one just to see the conflicts.

**Pushing / fetching is done by you, outside the sandbox.** The filesystem
allowlist doesn't include `~/.ssh`, `~/.git-credentials`, or `~/.netrc` (they are
absent in the container), and `SSH_AUTH_SOCK` is never passed in, so the agent has
no usable push credentials -- it commits locally
only; you `git push` / `git fetch` from your own shell when ready. (Network egress
itself is open inside the container -- Model B needs it for the Anthropic API; see
Appendix D.)

**The toplevel `top` is intentionally NOT containerized** -- it is where you
run these management scripts, which must write outside their own directory (clone
repos, create sibling worktrees). Feature worktrees ARE sandboxed.

## Sandbox and GPU (summary)

`./sbox-claude` (a tracked script you run from a feature worktree)
launches `claude` inside a per-worktree **rootless-Podman** container with
`--dangerously-skip-permissions` (plus `IS_SANDBOX=1`). The kernel/container is
the security boundary, so the agent does real work -- including GPU compute --
with **zero permission prompts**, and escaping is not possible. The mount
manifest IS the security model:

- **Allowlist (default-deny)** -- the container mounts ONLY the paths in
  `sandbox/fs-allow.txt` (`ro`/`rw <path>`): the system dirs it needs (`/usr`, `/etc`,
  `/var`, ...) plus your toolchain (`~/miniforge3`, `~/.local`, ...), all read-only.
  Everything else -- your other projects, data, and unlisted secrets -- is simply
  **absent**. The single-id userns also caps any read at your account (host-root
  files like `/etc/shadow` map to `nobody`).
- **Read-write (do work + commit)** -- the whole **grouping dir** is always mounted
  rw in one go: the worktree, its siblings, the toplevel, and every repo's shared
  `.git` (Appendix E). On top, the policy lists (`sandbox/*.txt`) and each `.git`'s
  `config`+`hooks/` are re-pinned `:ro`, so the agent can't rewrite its own jail or
  plant code that runs in your unsandboxed shell. Add extra writable paths with
  `rw <path>` lines in `fs-allow.txt`; files are owned by you on the host.
- **Auth (per group)** -- `CLAUDE_CONFIG_DIR` points at `<grouping dir>/claude`, so
  the agent's `.claude.json`, OAuth token, and transcripts live in `~/ch/claude/`,
  shared by every worktree in the group and separate from your personal `~/.claude`
  (which
  the allowlist omits, so it is absent). Run `/login` once per grouping dir. See
  Appendix D.
- **GPU (compute)** -- NVIDIA nodes via `--device` (`sandbox/devices.txt`) + host
  CUDA libs (RO) + default seccomp. No shim, no seccomp override (Appendix C).

The `sandbox/` lists are plain text, read at every launch, so you edit them and
just re-launch -- no re-render. `sbox-claude` is a tracked, machine-independent
script (it inherits your shell's `PATH` + `CONDA_PREFIX` rather than baking
anything in); `.venv`, `.envrc`, and `.claude/env.sh` are machine-specific and
gitignored, while it, the templates, and `sandbox/*.txt` are tracked. Security
trade-offs (`IS_SANDBOX`, writable object store) are in Appendix D; the network
allowlist is below.

## Egress proxy (network allowlist)

The agent's network egress goes through **`sbox-net`**, a small per-grouping-dir
filtering proxy on the host (the container's `HTTPS_PROXY` points at it). A domain
is reachable only if it -- or a parent domain -- is on the git-tracked allowlist
`sandbox/net-allow.txt`; everything else is blocked. HTTPS is filtered by the
`CONNECT`/SNI hostname, so there is no TLS interception (no MITM, no cert).

**The approval flow.** When the agent hits an unlisted domain the request fails
and the agent reports the domain to you. You approve it on the host:

    sbox-net allow github.com      # appends to net-allow.txt; the agent retries

The agent re-runs the request and it now succeeds. To block a domain for good (so
it never prompts again), `sbox-net deny <domain>` records a remembered denial in
`net-deny.txt` (deny wins over allow).

**One proxy, shared.** `sbox-claude` starts the proxy on first use -- one per
grouping dir, reading the toplevel's lists -- so an approval applies to **every
agent in every worktree** of the group at once. The lists live in git; approvals
auto-append (you commit them when ready). Other commands: `sbox-net status | log |
stop | url`. The lists are curated for a **prompt-injection** threat model -- the
test for the allowlist is "is the served text first-party (vendor-authored)?". It
holds what claude itself needs (`anthropic.com`, `claude.com`/`claude.ai`) plus
first-party documentation sites (CUDA, `python.org`, numpy, grpc, ...). User-
generated content (`github.com`, pypi/conda *project pages*, stackoverflow, ...)
is deliberately NOT allowlisted -- that is the injection vector, and you run
pip/conda by hand -- so it stays blocked-by-default and is approved per-use only
if a real need arises. `net-deny.txt` (empty by default) is for UGC you never want
to be even asked about. The header comments in `net-allow.txt` spell out the full
policy.

**Caveats.** The proxy filters every client that honors `HTTPS_PROXY` (`pip`,
`curl`, `requests`, git-over-https, claude's own API) -- which is the
prompt-injection vector, so it meaningfully shrinks exfiltration. It is *not* yet
bypass-proof: the container still uses `--network host`, so a deliberately
malicious payload could open a raw socket around the proxy (enforcing proxy-only
egress rootless is a harder, later step). Set `SBOX_NO_PROXY=1` before
`./sbox-claude` to bypass the proxy (open egress) while debugging. Richer approval
UX (tmux prompt, hold-to-approve, phone push) is sketched in Appendix F.

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

1. Each worktree's `.envrc` (for you) and `.claude/env.sh` plus the launcher's
   `-e PYTHONSAFEPATH=1` (for agents) drop the current directory from `sys.path`
   for every Python invocation -- verified safe for the build too.
2. `pirate_frb/__init__.py` detects the shadow and raises a clear, actionable
   error instead of the cryptic undefined-symbol crash.
3. `build_venv` runs its smoke test from a throwaway directory.

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
string and clobber PATH. The mechanism that works is Claude's **`CLAUDE_ENV_FILE`**:
a script Claude sources before every Bash command, where `$PATH` *does* expand.

- `.envrc` exports `CLAUDE_ENV_FILE="$PWD/.claude/env.sh"` (for `claude` run
  directly on the host). `sbox-claude` passes the same path into the container
  with `-e CLAUDE_ENV_FILE`, so it applies there too.
- `.claude/env.sh` (generated) does `export PATH="<worktree>/.venv/bin:$PATH"`
  (plus `VIRTUAL_ENV`, `PYTHONSAFEPATH`). It is sourced *after* bashrc's conda
  activation, so the venv wins.

`sbox-claude` does NOT re-derive your toolchain: it runs in your bashrc+conda+
direnv-sourced shell, so it just forwards your live `PATH` and `CONDA_PREFIX`
into the container (prepending `<worktree>/.venv/bin` for safety) and sets
`VIRTUAL_ENV`, `PYTHONSAFEPATH`, `CUPY_CACHE_DIR`, `LD_LIBRARY_PATH`. `~/.bashrc`
still runs `conda activate` inside, and `env.sh` layers the venv on top for each
Bash command. Hence "launch from the worktree, in an activated shell":
`./sbox-claude` self-locates the worktree and wires all of this up.

The `init-*` scripts themselves also feel `PYTHONSAFEPATH=1`: once direnv has run
in top, a bare `import ch_top_helpers` would fail (the script dir is dropped
from `sys.path`), so each entry-point script prepends its own directory to
`sys.path` before importing.

# Appendix C: GPU compute inside the container

Under rootless Podman the GPU "just works" -- none of the bubblewrap-era tricks
are needed. The launcher:

- passes the NVIDIA device nodes with `--device` (from `sandbox/devices.txt`,
  default glob `/dev/nvidia*` -> all GPUs; only existing character devices are
  passed, so the `/dev/nvidia-caps` directory is skipped automatically);
- mounts the host `/usr` (and `/etc`) read-only, which brings the matching NVIDIA
  driver libs + the CUDA runtime (`/usr/local/cuda` lives under `/usr`). This is
  *why* the base image must be the same Ubuntu release -- the host glibc/loader is
  overlaid and must match;
- runs under the **default** seccomp profile, and adds `--ipc host` +
  `--ulimit memlock=-1:-1` for CUDA pinned memory / RDMA.

Verified live on this host: `nvcc` compiles and runs a kernel, and a `cupy`
reduction returns the right answer -- no `cudaSetDevice ... 304`, no shim. The two
bubblewrap barriers are simply absent here: Podman builds a normal `/dev` and we
*add* the GPU nodes (so no `--dev` devtmpfs hides them), and the default seccomp
profile does not nest PID/mount namespaces (so NVIDIA UVM is not broken). No
`nvidia-container-toolkit` is required.

Re-verify after a Podman or host-driver upgrade with a real compute test (a `cupy`
reduction, or `pirate_frb test -n 1`). `nvidia-smi` alone is NOT sufficient -- it
opens no CUDA context, so it can pass while compute fails.

# Appendix D: container sandbox security trade-offs

For a trusted single-user dev box these are acceptable trades; know what they are.

**Network egress is filtered (allowlist), not open.** Model B runs `claude`
*inside* the container, so it needs network for the Anthropic API; egress goes
through `sbox-net`'s per-group domain allowlist (see "Egress proxy"), so the agent
reaches only approved domains via any `HTTPS_PROXY`-honoring client. It is not yet
bypass-proof -- `--network host` remains, so a malicious payload could open a raw
socket around the proxy (tightening that is future work). It **cannot push or
exfiltrate via your keys**: `~/.ssh`,
`~/.git-credentials`, and `~/.netrc` are not in the allowlist (absent in the
container) and `SSH_AUTH_SOCK` is never passed in (the host agent sockets live in
`/tmp`,`/run`, which are private tmpfs inside the container, so they are simply
absent). Your **personal** Claude token is out of reach too: `~/.claude` is not
allowlisted, and the agent
authenticates from its own per-group `CLAUDE_CONFIG_DIR` (`~/ch/claude/.credentials.json`,
a separate one-time `/login`). The agent *can* still read that group token and,
via an allowlisted domain that accepts content, send it out -- but the damage is bounded by your subscription
scope (rate limits, not metered $), and you can revoke/re-login the group token
without touching your personal one. To restrict *where* it connects, run a
`pasta`/`slirp4netns` egress allowlist (only `api.anthropic.com` + your package
mirror) instead of `--network host` -- recorded as a future tightening, not built now.

**Container `uid 0` = your host uid.** With no `/etc/subuid` range the userns is
single-id, so the container process is `uid 0` mapped to you. Cosmetic (writes are
owned by you; host-root files still appear as `nobody` and are unreadable -- the
read cap holds), but it requires `IS_SANDBOX=1`, an **undocumented** Claude env
var that lets `claude` accept `--dangerously-skip-permissions` as `uid 0`.
Re-check after `claude` upgrades that this still works. (If an admin adds subuid
ranges you could run as a mapped non-root uid and drop `IS_SANDBOX`.)

**The shared object store is writable.** The agent can rewrite refs/history in the
main checkouts' `.git` (Appendix E); only `config` and `hooks/` are protected,
history is not.

**`--network host` + `--group-add keep-groups`** give the agent your network
namespace and your supplementary-group reads (`chord-dev`, ...). Fine on a trusted
single-user box; not a defense against a kernel-exploit-grade adversary.

**Default-deny filesystem.** Only the paths in `sandbox/fs-allow.txt` are mounted;
everything else is simply absent in the container (not even an empty placeholder).
Your secrets and unrelated files are invisible because they were never mounted --
not because of a mask you have to remember to add. The flip side: it fails CLOSED,
so a path the toolchain needs but you forgot to list shows up as a missing-file
error -- add it to `fs-allow.txt`.

**The base image must track the host distro** (host `/usr` is overlaid); bump the
`IMAGE=` line in `sbox-claude` on a host upgrade and re-verify GPU + a build.

# Appendix E: `git commit` from a worktree (shared .git)

A commit in a feature worktree writes to each repo's SHARED `.git` common-dir,
which in this nested layout lives in the main checkout (`top/.git`,
`top/ksgpu/.git`, `top/pirate/.git`) -- OUTSIDE the worktree, so under the
container's read-only base it would be read-only and the commit would fail.

The shared `.git` stores sit inside the grouping dir, which the launcher mounts
`:rw` as a whole -- so `git commit` writes objects/refs there with no prompt. On
top of that, `sbox-claude` resolves each repo's common-dir (`git -C <repo>
rev-parse --git-common-dir`) and re-pins its `config` file and `hooks/` dir `:ro`
(Podman applies the deeper mount last, so read-only wins over the read-write
parent). This matters: `config` and `hooks/` are settings/code that execute in
YOUR unsandboxed shell, so the agent must not be able to write them. (The
`sandbox/*.txt` policy lists are re-pinned `:ro` the same way, so the agent can't
widen its own sandbox.)

Verified live: inside the container a `git commit` succeeds, while appending to
`.git/config` or planting `.git/hooks/post-commit` are both blocked (read-only
fs). Note the residual (also in Appendix D): the agent can write the shared object
store and refs, so it could in principle rewrite refs/history of the main
checkouts -- `config`/`hooks` are protected, history is not.

For the toplevel `top` checkout, `.git` is inside the dir (and the toplevel is
not containerized anyway), so there is nothing to bind.

# Appendix F: richer egress-approval options (B-D, not implemented)

The egress proxy ("Egress proxy" above) ships with **Design A**: a blocked domain
fails, the agent reports it, you run `sbox-net allow <domain>`, the agent retries.
Three richer approval UXes were considered and deferred -- recorded so the options
aren't forgotten. All share the same backbone (one proxy, the git-tracked
`net-allow.txt`, live re-read), so moving A -> B/C/D changes only the
notify/approve front-end.

- **B -- tmux approval pane.** The proxy enqueues blocked domains; a long-running
  `sbox-net watch` in a tmux pane prompts `github.com -- allow? [y/N]` and appends
  on `y`. One keypress instead of typing the domain; needs you watching the pane.
- **C -- hold-and-approve (no retry).** Instead of failing, the proxy *holds* the
  blocked connection open, notifies you, and completes it on approval -- so the
  agent's request just pauses (like a permission prompt) and succeeds with no
  retry. Risk: HTTP client connect-timeouts if you are slow to answer.
- **D -- push to phone** (for unattended runs / when you are away from the SSH
  session). On block the proxy pushes a notification with Allow/Deny buttons;
  tapping Allow appends to the allowlist. Implement with **ntfy** (the ntfy app
  shows it; the Allow button POSTs to a second ntfy topic the host *subscribes*
  to, so the host makes only outbound connections -- no inbound endpoint needed on
  the SSH box) or a **Telegram bot** (inline buttons + long-poll). Caveat: a public
  broker sees which domains your agents hit; use random topics + a token, or
  self-host the broker.
