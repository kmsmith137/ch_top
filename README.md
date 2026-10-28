# ch_top: workspace for CHORD FRB development

ch_top is a small "container" repo for developing the CHORD real-time FRB
search. It holds three sub-repos, as plain clones (not git submodules):

- `pipmake`: the pip build backend used to compile ksgpu and pirate;
- `ksgpu`: GPU C++/CUDA core utilities;
- `pirate`: the real-time FRB search engine.

The repos are managed with xwt (`~/git/xwt`): `xwt.toml` lists the
sub-repos and their integration branches, and sets up each workspace's
Python environment. ch_top itself holds only that file, `CLAUDE.md`, and
the ch-specific Claude Code skills in `.claude/skills/`. Generic skills
come from kms-skills (`~/git/kms-skills`).

## Layout

Everything lives in a grouping dir, usually `~/ch`:

    top/            the toplevel: plain clone of ch_top (main branch)
    top/pipmake     plain clone (main branch)
    top/ksgpu       plain clone (kms branch)
    top/pirate      plain clone (kms branch)
    dev/            a worktree, made by `xwt new dev`: a git worktree of
    dev/pipmake       each of the four repos, all on branch `dev`
    dev/ksgpu
    dev/pirate
    extern/         reference source trees (the old CHIME pipeline, etc.)

Each workspace (the toplevel or a worktree) has its own `.venv`, with
editable installs of pipmake, ksgpu and pirate, activated by direnv when you
`cd` in. xwt generates the `.envrc`.

## One-time setup (per machine)

- **A conda toolchain env named `dev`**, activated in `~/.bashrc`, holding
  the compiled dependencies (cupy, the CUDA toolchain, pybind11, grpc, ...).
  The authoritative package lists are in `ksgpu/README.md` and
  `pirate/notes/install.md`. You also need an NVIDIA GPU and `nvcc`.
- **direnv**, on `PATH` in every shell, with its hook in `~/.bashrc` after the
  `conda activate` line: `eval "$(direnv hook bash)"`.
- **xwt**, installed into the `dev` env: `pip install -e ~/git/xwt`.
- **kms-skills**, installed for Claude Code (and Codex):
  `~/git/kms-skills/install`.
- **SSH access to GitHub** through a `github` host alias in `~/.ssh/config`,
  which the URLs in `xwt.toml` use.

## Quick start

    mkdir ~/ch && cd ~/ch
    git clone github:kmsmith137/ch_top top
    cd top && xwt init        # clones the sub-repos, writes .envrc, builds .venv
    xwt new dev               # makes the worktree ../dev, with its own venv
    cd ../dev

`xwt init` and `xwt new` compile ksgpu and pirate, so they take a while;
pass `--no-venv` to skip the venv build.

## Daily workflow

- `xwt status`: git status in every repo, how each worktree's branch relates
  to the integration branches, and warnings.
- `xwt venv`: re-run the editable installs after changing compiled code.
- `xwt rebase-down` in a worktree brings its branch up to date with the
  integration branches; `xwt merge-up` then fast-forwards them to it.
- `xwt delete NAME` removes a worktree. It refuses while there is
  uncommitted or unmerged work, but it deletes ignored files without asking,
  including `pirate/plans/` (pirate ignores it), so move anything worth
  keeping out first.

xwt's README covers the details, including resolving rebase conflicts.

## Skills

The ch-specific skills, each run only when you invoke it:

| Skill | What it does |
|---|---|
| `/ch-test` | full test sweep: rebuild, ksgpu and pirate unit tests, chimefrb spot checks, toy and production searches with offline dedispersion (~2.5 hours) |
| `/ch-release` | prepare and validate PyPI sdists for pipmake, ksgpu and pirate (~30–45 min) |
| `/ch-review-docs` | review the pirate Sphinx docs for correctness and maintain their auto-cross-linking |
| `/ch-review-pybind11` | multi-agent review of the pybind11 bindings in ksgpu and pirate |
| `/ch-review-stoppable` | multi-agent review of pirate's stoppable and thread-backed classes |

kms-skills adds generic ones: kms-research (long research campaigns),
kms-review-plan, kms-report, kms-artifact and kms-humanize.

## Appendix: cwd shadowing

Because the repos are nested under the workspace root, the root contains a
directory named `ksgpu/`, the same name as the `ksgpu` Python package.
Python puts the current directory at the front of `sys.path` (`python -c`,
`python -m` and the REPL use the cwd; `python script.py` uses the script's
directory). So running Python from the workspace root makes `import ksgpu`
pick up that `ksgpu/` directory as an empty namespace package, shadowing the
editable-installed package. Its `__init__.py`, and the ctypes trick that
publishes ksgpu's C++ symbols with `RTLD_GLOBAL`, never run, and
`import pirate_frb` then fails with a cryptic
`undefined symbol: ksgpu::convert_array_from_python`. Activating the venv
doesn't help: the cwd entry sits ahead of site-packages regardless.
(pirate's package is `pirate_frb`, so it is only ever shadowed indirectly,
through ksgpu.)

Two guards:

1. `PYTHONSAFEPATH=1`, which drops the current directory from `sys.path` for
   every Python invocation. Each workspace's `.envrc` exports it (from
   `[envrc.export]` in `xwt.toml`).
2. `pirate_frb/__init__.py` detects the shadowing and raises a clear error
   instead of the undefined-symbol crash.

In a shell without the workspace environment (direnv not loaded), run Python
from inside a repo directory, or prefix the command with `PYTHONSAFEPATH=1`.
Any non-empty value enables it: `PYTHONSAFEPATH=0` still enables it; unset it
to turn it off.
