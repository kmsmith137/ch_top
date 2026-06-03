"""Shared helpers for the ch_top workspace scripts.

ch_top is a personal multi-repo workspace. The inner repos (ksgpu, pirate, ...)
are plain clones listed in git_repositories.toml; feature workspaces are git
worktrees. See README.md for the design.

Entry-point scripts (init-*, git-*, delete-worktree) reach this module via a
one-line `sys.path.insert(0, <script dir>)` placed before they import it. That
line is required because the worktree env sets PYTHONSAFEPATH=1 (the cwd-shadowing
guard; see README.md "cwd shadowing"), which stops Python from putting a script's
own directory on sys.path -- so once direnv has run, a bare `import ch_top_helpers`
would otherwise fail with ModuleNotFoundError.

NOTE: nothing here names or activates a conda env. Every script assumes the
correct conda toolchain env is already active in your shell (you load it in
~/.bashrc). Venvs are seeded from whatever interpreter is active.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# Root of the top checkout = the directory containing these scripts.
ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "git_repositories.toml"
TEMPLATES = ROOT / "dotfile_templates"


def die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def info(msg: str) -> None:
    print(f"[ch_top] {msg}")


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
    'top' or 'dev'), then each manifest repo subdir that exists ('ksgpu',
    'pirate', ...). Subdirs that are missing (workspace not fully set up) are
    skipped rather than erroring.
    """
    workdir = Path(workdir).resolve()
    if not (workdir / ".git").exists():
        die(f"{workdir} is not a git repo (run init-toplevel / init-worktree?)")
    repos = [(workdir.name, workdir)]
    for name in load_manifest():
        sub = workdir / name
        if (sub / ".git").exists():
            repos.append((name, sub))
    return repos


def run_git_each(specs, *, dry_run=False):
    """Run a git command in several repos, each under a per-repo header.

    `specs` is an iterable of (label, path, git_args). Returns (worst_rc,
    failed_labels). Color is enabled when stdout is a terminal and suppressed
    when piped/redirected. With dry_run=True, prints the command it WOULD run
    instead of running it (rc 0).
    """
    color = "always" if sys.stdout.isatty() else "auto"
    worst, failed = 0, []
    for label, path, git_args in specs:
        print(f"==================== {label} ====================")
        if dry_run:
            printable = " ".join(shlex.quote(str(a)) for a in ["git", "-C", str(path), *git_args])
            print(f"[dry-run] {printable}")
            print()
            continue
        cmd = ["git", "-C", str(path), "-c", f"color.ui={color}", *git_args]
        res = subprocess.run(cmd, capture_output=True, text=True)
        worst = max(worst, res.returncode)
        if res.returncode:
            failed.append(label)
        body = (res.stdout if res.returncode == 0 else res.stdout + res.stderr).rstrip("\n")
        print(body if body else "(no output)")
        print()
    return worst, failed


def run_git_all(git_args, workdir=ROOT) -> int:
    """Run `git <git_args>` in each workspace repo, under a per-repo header.

    Headers read `<workspace>/<repo>`, e.g. `dev/pirate` -- the workspace dir
    this is run from, and the repo identity (top / ksgpu / pirate). Returns
    the worst (max) git exit code.
    """
    ws = Path(workdir).resolve().name
    specs = [(f"{ws}/{repo}", path, git_args)
             for repo, path, _integ, _cur in repo_branch_info(workdir)]
    worst, _ = run_git_each(specs)
    return worst


def is_toplevel(workdir=ROOT) -> bool:
    """True if workdir is the toplevel top checkout (its .git is a directory),
    False if it is a linked worktree (its .git is a file)."""
    return (Path(workdir) / ".git").is_dir()


def require_grouping_dir(toplevel=ROOT) -> None:
    """Die unless the toplevel lives in a grouping dir, not directly in $HOME.

    Feature worktrees are created as SIBLINGS of the toplevel (../NAME), so the
    toplevel must be nested at least one level below $HOME -- e.g. ~/ch/top,
    not ~/top -- otherwise the worktrees would land directly in $HOME. The
    intermediate "grouping" dir (~/ch here) holds a toplevel together with all
    its worktrees. See README.md "Layout".
    """
    toplevel = Path(toplevel).resolve()
    home = Path.home().resolve()
    if toplevel.parent == home:
        die(f"toplevel {toplevel} sits directly in $HOME ({home}).\n"
            f"  Worktrees are created as siblings (../NAME), so they would land in\n"
            f"  $HOME too. Move the toplevel into a grouping dir first, e.g.\n"
            f"      {home}/ch/{toplevel.name}\n"
            f"  (any parent-dir name works, just not $HOME itself).")


def current_branch(repo_path):
    """The branch checked out in repo_path, or None if detached."""
    res = subprocess.run(
        ["git", "-C", str(repo_path), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True, text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else None


def branch_exists(repo_path, branch) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{branch}"],
        capture_output=True, text=True,
    ).returncode == 0


def repo_branch_info(workdir=ROOT):
    """[(repo_name, path, integration_branch, current_branch)] for each repo.

    repo_name is the repo identity (top / ksgpu / pirate), taken from the
    main-worktree dirname; path is THIS workspace's checkout of it;
    integration_branch is the branch checked out in that repo's main worktree
    (main / chord / kms); current_branch is what `path` has checked out.
    """
    out = []
    for _label, path in workspace_repos(workdir):
        wts = _parse_worktrees(path)
        if not wts:
            continue
        main_path, integ = wts[0]
        out.append((main_path.name, path, integ, current_branch(path)))
    return out


def repo_main_path(repo_path):
    """The main-worktree path of repo_path's repository -- where the integration
    branch (main/chord/kms) is checked out. For a worktree checkout this points
    back into the toplevel (e.g. ~/ch/dev/pirate -> ~/ch/top/pirate); for
    the toplevel checkout it is repo_path itself."""
    wts = _parse_worktrees(repo_path)
    return wts[0][0] if wts else Path(repo_path).resolve()


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
    and Y = a feature-worktree branch. Run from the toplevel top, covers every
    feature worktree of every repo; run from a feature worktree, only that
    worktree's own branch. Returns formatted strings like
    'dev/pirate is 2 commits ahead of top/pirate (kms branch)' --
    '<branch>/<repo>' vs '<toplevel-workspace>/<repo> (<integration-branch> branch)'.

    Lines are grouped by feature branch (all of dev's repos, then all of
    test's, ...), each group in repo order (top, ksgpu, pirate), with an
    empty string between groups so callers print a blank line between them.
    """
    workdir = Path(workdir).resolve()
    toplevel = (workdir / ".git").is_dir()
    # The toplevel workspace name is the container repo's main-worktree dirname
    # (e.g. 'top'). workspace_repos lists the container repo first.
    repos = workspace_repos(workdir)
    top_ws = _parse_worktrees(repos[0][1])[0][0].name if repos else "top"
    # Collect lines per feature branch, preserving first-seen branch order and
    # repo order (repos are iterated in workspace_repos order).
    by_branch = {}  # branch -> [line, ...]
    for _, path in repos:
        wts = _parse_worktrees(path)
        if not wts or wts[0][1] is None:
            continue  # repo with a detached main worktree -- nothing to compare to
        main_path, base = wts[0]
        repo = main_path.name             # repo identity: top / ksgpu / pirate
        if toplevel:
            targets = [(p, b) for p, b in wts[1:] if b is not None]
        else:
            targets = [(p, b) for p, b in wts if p == path and b is not None]
        for _wt_path, branch in targets:
            ab = _ahead_behind(path, base, branch)
            rel = _relation_phrase(*ab) if ab else "cannot be compared to"
            by_branch.setdefault(branch, []).append(
                f"{branch}/{repo} is {rel} {top_ws}/{repo} ({base} branch)")
    # Flatten, with a blank line between branch groups.
    lines = []
    for group in by_branch.values():
        if lines:
            lines.append("")
        lines.extend(group)
    return lines


def base_python() -> str:
    """Path to the *base* (non-venv) interpreter, i.e. the conda env's python.

    If init-venv is run from inside an already-active venv overlay, seeding the
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


# Repos to install into a workspace venv, in dependency order. pipmake comes
# FIRST: it is the `pipmake` build backend that ksgpu/pirate declare, so it must
# be installed (importable) in the venv before their --no-build-isolation editable
# installs run. NOT derived from the manifest: build_venv hardcodes the per-repo
# editable-install recipe, so when you add a repo to git_repositories.toml you
# must also add it here (see the REMINDER in the manifest). The editable install
# (`pip install --no-build-isolation -e .`) is what compiles the native libs:
# ksgpu/pirate use the `pipmake` backend, whose build_editable runs `make
# build_wheel` -- which builds the import-critical .so's (pipmake itself is pure
# Python, a plain setuptools editable install -- no make). We deliberately do NOT
# run a separate `make`/`make all` first: `all` pulls in pirate's `lib` target,
# whose `configs/asdf_header.yml` rule runs `python -m pirate_frb ...` (not
# importable until AFTER the editable install, and its `> asdf_header.yml` redirect
# would truncate that file). Installing is sufficient and correctly ordered.
BUILD = ["pipmake", "ksgpu", "pirate"]

# Fast import check (always run). The heavy GPU unit test is gated behind test=.
SMOKE_IMPORT = "import ksgpu, pirate_frb; print('import ok')"
HEAVY_TEST = ["-m", "pirate_frb", "test", "-n", "1"]


def build_venv(workdir, *, recreate: bool = False, test: bool = False) -> None:
    """Create (or refresh) <workdir>/.venv: a --system-site-packages overlay on
    the active conda env, with each repo in BUILD compiled + installed editable.

    Called in-process by init-toplevel / init-worktree, and standalone via the
    init-venv CLI. See README.md.
    """
    workdir = Path(workdir).resolve()
    if not workdir.is_dir():
        die(f"workdir does not exist: {workdir}")

    # Reminder enforcement: warn about manifest repos this does not build.
    built = set(BUILD)
    for name in load_manifest():
        if name not in built:
            warn(f"repo '{name}' is in the manifest but build_venv does not build "
                 f"it -- add it to BUILD in {Path(__file__).name}")

    venv = workdir / ".venv"
    if venv.exists() and recreate:
        info(f"removing existing venv {venv}")
        shutil.rmtree(venv)

    if not venv.exists():
        run([base_python(), "-m", "venv", "--system-site-packages", str(venv)])
    else:
        info(f"reusing existing venv {venv} (use --recreate to rebuild)")

    env = venv_env(workdir)
    pip = str(venv / "bin" / "pip")
    py = str(venv / "bin" / "python")

    # `editables` must live IN the venv, not merely be visible via
    # --system-site-packages: an editable install's .pth imports it during
    # interpreter startup, before the conda site-packages are on sys.path, so the
    # conda copy is not yet importable and the .pth (hence the package it
    # registers) is silently dropped ("No module named 'editables'"). Force it
    # into the venv's own site-packages. (The `pipmake` build backend for the
    # --no-build-isolation installs below is no longer pip-installed from PyPI --
    # it is built from the workspace as the first BUILD entry, so it too lands in
    # the venv ahead of ksgpu/pirate, which then import it at build time.)
    run([pip, "install", "--ignore-installed", "editables"], env=env)

    for name in BUILD:
        repo = workdir / name
        if not repo.is_dir():
            die(f"repo dir missing: {repo}  (run init-toplevel first?)")
        # For ksgpu/pirate the editable install runs `make build_wheel` (via the
        # pipmake backend) to compile the native libs; pipmake itself is a plain
        # setuptools editable install. No separate `make` step -- see BUILD above.
        run([pip, "install", "--no-build-isolation", "-e", "."], cwd=str(repo), env=env)

    # Smoke test from a throwaway directory, NOT the workspace root. The root
    # contains 'ksgpu/' (and 'pirate/') source subdirs that Python would pick up
    # from sys.path[0] as empty PEP 420 namespace packages, shadowing the
    # editable-installed packages -- hiding ksgpu's __init__.py and its ctypes
    # RTLD_GLOBAL trick (=> "undefined symbol: ksgpu::convert_array_from_python").
    # The worktree env sets PYTHONSAFEPATH=1 to neutralize this for every cwd, but
    # build_venv must not depend on that being active -- it can run during
    # first-time setup, before those dotfiles exist. See README.md "cwd shadowing".
    with tempfile.TemporaryDirectory() as tmp:
        run([py, "-c", SMOKE_IMPORT], cwd=tmp, env=env)
        if test:
            run([py, *HEAVY_TEST], cwd=tmp, env=env)

    info(f"venv ready: {venv}")


def _write_if_changed(path: Path, content: str, *, announce: bool, hint: str = "") -> bool:
    """Write `content` to `path` only if it differs (or `path` is missing).

    Returns True if it wrote (i.e. the file changed). When `announce` and it
    wrote, prints an info() line. Avoids needless rewrites so re-rendering an
    already-current worktree is a quiet no-op.
    """
    existing = path.read_text() if path.exists() else None
    if existing == content:
        return False
    path.write_text(content)
    if announce:
        info(f"wrote {path}{hint}")
    return True


def render_dotfiles(workdir: Path, *, announce: bool = True) -> list:
    """Render the per-workspace dotfiles (.envrc and .claude/env.sh) into workdir.

    Substitutes {{WORKTREE}} -> absolute workdir path. A literal $PATH in env.sh
    is left untouched (the shell expands it when Claude sources the file before
    each Bash command). The Podman sandbox launcher is the tracked `sbox-claude`
    script (run from a worktree), not a rendered dotfile.

    Files are written only if their content changed (idempotent re-render).
    Returns the list of Paths actually written. With announce=True (default)
    prints an info() line per written file; callers that want their own
    reporting (e.g. git-rebase-down) pass announce=False.
    """
    workdir = Path(workdir).resolve()
    changed = []

    envrc = (TEMPLATES / "envrc.tmpl").read_text()
    if _write_if_changed(workdir / ".envrc", envrc, announce=announce,
                         hint=f"  (then run: direnv allow {workdir})"):
        changed.append(workdir / ".envrc")

    claude_dir = workdir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # env.sh is sourced by Claude before each Bash command (via CLAUDE_ENV_FILE);
    # it prepends the venv to PATH -- the one thing Claude's settings.json 'env'
    # cannot do, since it does not expand ${PATH}. See README.md Appendix B.
    env_sh = (TEMPLATES / "claude-env.sh.tmpl").read_text().replace("{{WORKTREE}}", str(workdir))
    if _write_if_changed(claude_dir / "env.sh", env_sh, announce=announce):
        changed.append(claude_dir / "env.sh")

    return changed
