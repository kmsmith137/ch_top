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
    when sandbox=True. Substitutes {{WORKTREE}} -> absolute workdir path; a
    literal $PATH in env.sh is left untouched (the shell expands it when Claude
    sources the file before each Bash command).
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
        settings = (TEMPLATES / "claude-settings.tmpl").read_text().replace("{{WORKTREE}}", str(workdir))
        (claude_dir / "settings.json").write_text(settings)
        info(f"wrote {claude_dir / 'settings.json'}")
