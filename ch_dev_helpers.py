"""Shared helpers for the ch_dev workspace scripts.

ch_dev is a personal multi-repo workspace. The inner repos (ksgpu, pirate, ...)
are plain clones listed in git_repositories.toml; feature workspaces are git
worktrees. See README.md and plans/multi_agent_workspace.md for the design.

NOTE: nothing here names or activates a conda env. Every script assumes the
correct conda toolchain env is already active in your shell (you load it in
~/.bashrc). Venvs are seeded from whatever interpreter is active.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

# Root of the ch_dev checkout = the directory containing these scripts.
ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "git_repositories.toml"
TEMPLATES = ROOT / "dotfile_templates"


def die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def info(msg: str) -> None:
    print(f"[ch_dev] {msg}")


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def run(cmd, cwd=None, env=None, check=True):
    """Echo and run a command given as a list. Returns the CompletedProcess."""
    printable = " ".join(shlex.quote(str(c)) for c in cmd)
    loc = f"  (cwd={cwd})" if cwd else ""
    info(f"$ {printable}{loc}")
    return subprocess.run(cmd, cwd=cwd, env=env, check=check)


def capture(cmd, cwd=None) -> str:
    """Run a command and return its stripped stdout."""
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def load_manifest() -> dict:
    """Return {name: {'url':..., 'branch':...}} from the manifest, in file order.

    Order is preserved (dependencies first, e.g. ksgpu before pirate), which is
    the clone/build/install order.
    """
    if not MANIFEST.is_file():
        die(f"manifest not found: {MANIFEST}")
    with open(MANIFEST, "rb") as f:
        data = tomllib.load(f)
    repos = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict) or "url" not in cfg or "branch" not in cfg:
            die(f"manifest entry [{name}] must have both 'url' and 'branch'")
        repos[name] = {"url": cfg["url"], "branch": cfg["branch"]}
    if not repos:
        die("manifest lists no repos")
    return repos


def workspace_repos(workdir=ROOT):
    """Ordered (label, path) for every git repo in a workspace.

    The workspace root itself comes first (labelled by its own dirname, e.g.
    'ch_dev' or 'ch_evrb'), then each manifest repo subdir that exists ('ksgpu',
    'pirate', ...). Subdirs that are missing (workspace not fully set up) are
    skipped rather than erroring.
    """
    workdir = Path(workdir).resolve()
    if not (workdir / ".git").exists():
        die(f"{workdir} is not a git repo (run init_toplevel.py / init_worktree.py?)")
    repos = [(workdir.name, workdir)]
    for name in load_manifest():
        sub = workdir / name
        if (sub / ".git").exists():
            repos.append((name, sub))
    return repos


def run_git_all(git_args, workdir=ROOT) -> int:
    """Run `git <git_args>` in each workspace repo, under a per-repo header.

    Returns the worst (max) git exit code. Color is enabled when stdout is a
    terminal and suppressed when piped/redirected, so `git-diff.py | less` keeps
    color while `git-diff.py > out.txt` stays plain.
    """
    color = "always" if sys.stdout.isatty() else "auto"
    repos = workspace_repos(workdir)
    worst = 0
    for label, path in repos:
        cmd = ["git", "-C", str(path), "-c", f"color.ui={color}", *git_args]
        res = subprocess.run(cmd, capture_output=True, text=True)
        worst = max(worst, res.returncode)
        print(f"==================== {label}  ({path}) ====================")
        body = (res.stdout if res.returncode == 0 else res.stdout + res.stderr).rstrip("\n")
        print(body if body else "(no output)")
        print()
    return worst


def _parse_worktrees(repo_path):
    """[(worktree_path: Path, branch: str|None)] for repo_path, main worktree first.

    branch is None for a detached HEAD. Uses `git worktree list --porcelain`,
    whose first block is always the repo's main worktree.
    """
    out = capture(["git", "-C", str(repo_path), "worktree", "list", "--porcelain"])
    entries, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = [Path(line[len("worktree "):]).resolve(), None]
            entries.append(cur)
        elif line.startswith("branch ") and cur is not None:
            cur[1] = line[len("branch refs/heads/"):]
    return [(p, b) for p, b in entries]


def _ahead_behind(repo_path, base, branch):
    """(ahead, behind) of `branch` relative to `base`, or None if uncomputable.

    ahead  = commits in branch not in base; behind = commits in base not in branch.
    """
    res = subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--left-right", "--count",
         f"{base}...{branch}"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    behind, ahead = (int(n) for n in res.stdout.split())
    return ahead, behind


def _relation_phrase(ahead, behind):
    plural = lambda k: f"{k} commit" + ("" if k == 1 else "s")
    if ahead == 0 and behind == 0:
        return "up-to-date with"
    if behind == 0:
        return f"{plural(ahead)} ahead of"
    if ahead == 0:
        return f"{plural(behind)} behind"
    return f"{plural(ahead)} ahead and {plural(behind)} behind"


def branch_relations(workdir=ROOT):
    """Lines describing how each feature worktree's branch relates to its repo's
    integration branch (the branch checked out in that repo's main worktree).

    For each repo in the workspace, X = the main-worktree branch (main/chord/kms)
    and Y = a feature-worktree branch. Run from the toplevel ch_dev, covers every
    feature worktree of every repo; run from a feature worktree, only that
    worktree's own branch. Returns formatted strings like
    'pirate/ch_evrb is 2 commits ahead of pirate/kms'.
    """
    workdir = Path(workdir).resolve()
    toplevel = (workdir / ".git").is_dir()
    lines = []
    for _, path in workspace_repos(workdir):
        wts = _parse_worktrees(path)
        if not wts or wts[0][1] is None:
            continue  # repo with a detached main worktree -- nothing to compare to
        main_path, base = wts[0]
        repo = main_path.name
        if toplevel:
            targets = [(p, b) for p, b in wts[1:] if b is not None]
        else:
            targets = [(p, b) for p, b in wts if p == path and b is not None]
        for _wt_path, branch in targets:
            ab = _ahead_behind(path, base, branch)
            rel = _relation_phrase(*ab) if ab else "cannot be compared to"
            lines.append(f"{repo}/{branch} is {rel} {repo}/{base}")
    return lines


def base_python() -> str:
    """Path to the *base* (non-venv) interpreter, i.e. the conda env's python.

    If init_venv is run from inside an already-active venv overlay, seeding the
    new venv from that overlay would chain its editable installs in. Using the
    base interpreter avoids that.
    """
    if sys.prefix != sys.base_prefix:  # running inside a venv
        for cand in ("python3", "python"):
            p = Path(sys.base_prefix) / "bin" / cand
            if p.exists():
                return str(p)
    return sys.executable


def venv_env(workdir: Path) -> dict:
    """os.environ with <workdir>/.venv overlaid on PATH (venv/bin first).

    python/pip then resolve to the venv, while the conda toolchain already on
    PATH (nvcc, headers, libs) stays available for `make`.
    """
    venv = Path(workdir) / ".venv"
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = f"{venv / 'bin'}:{env['PATH']}"
    env.pop("PYTHONHOME", None)
    return env


def render_dotfiles(workdir: Path, *, sandbox: bool) -> None:
    """Render the per-workspace dotfiles into workdir.

    Always writes .envrc and .claude/env.sh; writes .claude/settings.json only
    when sandbox=True. Substitutes {{WORKTREE}} -> absolute workdir path and
    {{UID}} -> this user's numeric UID (baked into the sandbox ssh-agent-socket
    deny path, which is machine-specific). A literal $PATH in env.sh is left
    untouched (the shell expands it when Claude sources the file before each
    Bash command).
    """
    workdir = Path(workdir).resolve()

    envrc = (TEMPLATES / "envrc.tmpl").read_text()
    (workdir / ".envrc").write_text(envrc)
    info(f"wrote {workdir / '.envrc'}  (then run: direnv allow {workdir})")

    claude_dir = workdir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # env.sh is sourced by Claude before each Bash command (via CLAUDE_ENV_FILE,
    # which .envrc exports); it prepends the venv to PATH -- the one thing
    # settings.json 'env' cannot do, since it does not expand ${PATH}.
    env_sh = (TEMPLATES / "claude-env.sh.tmpl").read_text().replace("{{WORKTREE}}", str(workdir))
    (claude_dir / "env.sh").write_text(env_sh)
    info(f"wrote {claude_dir / 'env.sh'}")

    if sandbox:
        settings = ((TEMPLATES / "claude-settings.tmpl").read_text()
                    .replace("{{WORKTREE}}", str(workdir))
                    .replace("{{UID}}", str(os.getuid())))
        (claude_dir / "settings.json").write_text(settings)
        info(f"wrote {claude_dir / 'settings.json'}")
