---
name: ch-release
description: Prepare and validate PyPI sdists for pipmake/ksgpu/pirate (version gate, sdist build, completeness check, install-from-sdist test); ~30-45 min
disable-model-invocation: true
---

Prepare sdist .tar.gz files for uploading to PyPI, and verify that they
actually build. Unit tests are assumed to have already been run (see
/ch-test); this command validates the *sdists*: that the file lists are
complete, that a from-sdist compile succeeds, and that the installed
packages import.

Work from the worktree root (the directory containing pipmake/, ksgpu/,
pirate/). Run the steps IN ORDER -- each one gates the next.

Ground rules (these mirror CLAUDE.md; they apply throughout):

- Do NOT git commit, merge, rebase, pull, push, or fetch. All git
  comparisons below are against the LOCAL main branch.
- Every pip install below uses --no-build-isolation, so that builds use the
  venv's own pipmake and setuptools; this is the procedure that was
  validated. pip's default isolated build env would download its build
  dependencies from PyPI instead.
- The Bash tool timeout (default 2 min, max 10 min) is too short for the
  compiling installs, and run_in_background does NOT exempt a command from
  it. Launch the two compiling installs (ksgpu, pirate) fully detached:
      setsid nohup bash -c 'pip install ...; echo "DONE exit=$?"' > LOG 2>&1 &
  then watch LOG for the DONE marker (e.g. with a Monitor until-loop).
  Keep logs in the session scratch dir.
- Known failure signature: "make: *** [target] Interrupt" plus python
  KeyboardInterrupt tracebacks means the make process group received
  SIGINT, not that the code is broken. One confirmed source (fixed in
  pirate's autogenerate_kernel.py, but the same trap could recur in any
  new build-time python step): make -jN running N python processes that
  each import numpy, where each OpenBLAS starts one thread per core; N^2
  threads can exceed a process-count limit (the old sandbox's was 2048,
  on 64 cores), and OpenBLAS reacts to pthread_create failure by signaling its
  process group, killing the whole make run. Look for "OpenBLAS
  blas_thread_init: pthread_create failed" earlier in the log; the fix is
  os.environ.setdefault('OPENBLAS_NUM_THREADS', '1') (and OMP_NUM_THREADS)
  before numpy is imported in the offending script.
- If a step fails, the bug may be in this procedure, in a Makefile, or in
  the code. Fix, rerun the failed step, and continue; summarize every fix
  at the end so the user can review with git diff. Do not commit. If a fix
  requires a judgment call (e.g. choosing a version number), stop and ask.

## Step 0: preconditions

This task must run in a "release" workspace: a worktree created with
`xwt new NAME --no-venv` followed by `xwt venv --bare` in it (or an existing
worktree whose venv was rebuilt with `xwt venv --recreate --bare`), whose
venv is BARE -- no editable installs of the packages under test.
Verify all of:

- You are in a worktree: `.git` in the worktree root is a *file*
  (containing "gitdir: .../top/.git/worktrees/NAME"), not a directory.
- `which python pip` resolve into ./.venv/bin.
- `pip list --editable` shows no pipmake/ksgpu/pirate. (Plain,
  non-editable installs left over from a previous run of this procedure
  are fine -- step 2 uninstalls them.)
- `pip show build` succeeds (python-build is needed for the sdist builds).

If the venv has editable installs, STOP and tell the user: this workspace
doesn't have a bare venv (see above), and testing sdist installs here
would be meaningless.

## Step 1: branch/version gate

For EACH of pipmake/, ksgpu/, pirate/, compare the checked-out branch to
local main: `git rev-list --left-right --count main...HEAD` prints
"L R" = (commits only on main) (commits only on HEAD). Then read the
version from the WORKING TREE pyproject.toml and from main
(`git show main:pyproject.toml`). Exactly one of these must hold:

- Case 1 -- even with main (L=0, R=0): nothing to release for this repo;
  its sdist is built below only as a build input, not for upload.
- Case 2 -- ahead of main (L=0, R>0) AND the working-tree version is
  higher than main's: this repo WILL be uploaded.

Anything else -- behind main (L>0), or ahead of main without a version
increment -- means the user forgot to bump a version number. ABORT the
whole task and report which repo failed; the user chooses version numbers
by hand.

Notes:

- The version bump may exist only as an UNCOMMITTED pyproject.toml edit in
  the worktree. That still counts as case 2 (the sdist is built from the
  working tree), but record it: the final report must remind the user to
  commit it, and `git status --short` in each repo should show nothing
  unexpected beyond such bumps.
- Cross-check pirate's pyproject.toml: the `ksgpu >= X` constraint appears
  twice (in [project] dependencies and in [build-system] requires) and
  both should match the ksgpu version being released. Report a mismatch;
  fix it only if the correct value is obvious.

## Step 2: build sdists and install them (interleaved)

The three packages form a build-dependency chain, and with
--no-isolation/--no-build-isolation each package must be INSTALLED before
the next one can even build its sdist:

- pipmake is the build backend of ksgpu and pirate ("Backend 'pipmake' is
  not available" if missing);
- pirate's sdist build runs makefile_helper.py, which locates the
  installed ksgpu package ("Couldn't find 'ksgpu' package" if missing).

So do NOT build all three sdists first and install afterwards. Interleave:

    rm -f */dist/*.tar.gz
    pip uninstall -y pipmake ksgpu pirate    # -y; "not installed" warnings are fine

    (cd pipmake && python -m build --no-isolation --sdist)
    pip install --no-build-isolation pipmake/dist/pipmake-*.tar.gz

    (cd ksgpu && python -m build --no-isolation --sdist)
    pip install -v --no-build-isolation ksgpu/dist/ksgpu-*.tar.gz
    # ^ compiles CUDA, a few minutes: detach + log (see ground rules)

    (cd pirate && python -m build --no-isolation --sdist)
    pip install -v --no-build-isolation pirate/dist/pirate_frb-*.tar.gz
    # ^ the long one (autogenerated kernels + full CUDA build): detach + log

Notes:

- pirate's package name (and sdist basename) is pirate_frb, not pirate.
- Install from the TARBALLS, never from the source directories -- testing
  the sdists is the whole point.
- Do the completeness check (step 3) for each repo BEFORE its long
  install, so an incomplete sdist aborts before a long compile; the
  from-sdist compile succeeding is itself the strongest completeness
  check for compiled sources.
- pip unpacks and compiles under /tmp/pip-req-build-*; expect the wheel
  build during the "Preparing metadata" phase (pipmake has no separate
  prepare_metadata hook).

## Step 3: sdist completeness check (ksgpu and pirate)

Building the sdists writes {ksgpu,pirate}/sdist_files.txt (gitignored).
For each of the two repos, diff the file list against git both ways:

    git ls-files | sort > /tmp/git.txt
    sort sdist_files.txt > /tmp/sdist.txt
    comm -23 /tmp/git.txt /tmp/sdist.txt    # tracked but not in sdist
    comm -13 /tmp/git.txt /tmp/sdist.txt    # in sdist but not tracked

Then read the Makefile in each repo -- the comment block at the top ("A
note on how to add new source files") and the SDIST_FILES definition --
and reason about whether anything a from-source build or an installed
package needs is missing.

A file counts as MISSING (-> ABORT and report; do not upload) if it is
git-tracked, needed to compile or import the package, and absent from
sdist_files.txt. Concretely, everything tracked under these prefixes must
be in the sdist:

- ksgpu:  ksgpu/*.py, src_lib/, src_pybind11/, include/
- pirate: pirate_frb/ (all .py, recursively), src_lib/ (except
  src_lib/autogenerated_kernels/), src_pybind11/, include/, grpc/*.proto,
  plus misc/asdf_cxx_config.hxx

The fix for a missing file is to add it to the right Makefile variable
(PYFILES, CUDAGEN_PYFILES, HFILES, LIB_SRCFILES, PYEXT_SRCFILES, ...) --
explain which one in the report, and abort rather than guessing.

Expected, deliberate EXCLUSIONS -- do not flag these (the Makefile
comments document them): README.md, CLAUDE.md, .gitignore, .gitmodules,
notes/, docs/, configs/, misc/ (except asdf_cxx_config.hxx),
environment*.yml, loose_ends/, ksgpu's generate_device_mma_hpp.py (its
output include/ksgpu/device_mma.hpp is checked in and shipped), and
pirate's src_lib/autogenerated_kernels/* (regenerated at build time by
autogenerate_kernel.py, which IS in the sdist).

Expected in-sdist-but-NOT-tracked (pirate only): asdf-cxx/src/*.cxx and
asdf-cxx/include/asdf/*.hxx. asdf-cxx is a git submodule -- git ls-files
shows only the bare "asdf-cxx" gitlink -- and the sdist embeds its
sources deliberately (the wildcard requires the submodule to be checked
out; an empty asdf-cxx/ would surface here as those files vanishing from
the sdist).

Sanity check: `tar tzf <sdist>.tar.gz | grep -v '/$' | wc -l` equals
`wc -l sdist_files.txt` + 1 (the added PKG-INFO).

## Step 4: import smoke test

    ksgpu test
    (cd pirate && pirate_frb test -n 1)

The console scripts are `ksgpu` and `pirate_frb` (NOT `pirate`). Both
commands must exit 0 with all tests passing; they need idle GPUs.
(`ksgpu test` takes a few minutes; `pirate_frb test -n 1` is one quick
iteration, enough to check that the installed package imports and its
kernels load.)

## Step 5: final report

Finish with a report containing:

- The exact `twine upload` command/paths for the user: ONLY the dist
  tarballs of case-2 repos (case-1 versions are already on PyPI). E.g.
  "twine upload ksgpu/dist/ksgpu-1.4.0.tar.gz
  pirate/dist/pirate_frb-1.4.0.tar.gz". Never run twine yourself.
- Every change you made in the worktrees (bug fixes, uncommitted version
  bumps you found), with file references -- remind the user to review
  (git diff) and commit them by hand.
- A reminder to merge each branch that is ahead of main into main (the
  user does this by hand).
- If pirate is ahead of main: a reminder to rebuild and deploy the pirate
  docs with ./docs/deploy.sh (run from pirate/).
- Timings observed (sdist builds, ksgpu/pirate compiles, test runs), and
  anything skipped or needing the user's judgment.
