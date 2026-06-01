This directory is a "container" git repo that holds two sub-repos
(plain standalone clones, not git submodules or subtrees):

  .          container repo with orchestration scripts
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

Our setup is as follows. We start by cloning all 3 repos
(these are called the "toplevel" repos):

  ~/ch_dev/        -> plain clone pointed at github remote
  ~/ch_dev/ksgpu   -> plain clone pointed at github remote
  ~/ch_dev/pirate  -> plain clone pointed at github remote

Then, for each feature we want to implement, we make git worktrees
for all 3 repos. For example, if the feature is named 'ch_test', then:

  ~/ch_test/          -> git worktree pointed at ~/ch_test
  ~/ch_test/ksgpu     -> git worktree pointed at ~/ch_test/ksgpu
  ~/ch_test/pirate    -> git worktree pointed at ~/ch_test/pirate

The first thing you should do on startup is figure out whether you are
in a worktree. (Toplevel is ~/ch_dev; a worktree is ~/ch_<feature>.
Equivalently: in a worktree, .git is a file; in the toplevel, it is a
directory.)

If you are making edits in any of the sub-repos, then you MUST
read the per-subrepo CLAUDE.md (either ./ksgpu/CLAUDE.md or
./pirate/CLAUDE.md) which contain additional instructions.

CRITICAL: things not to do:
   - Do not git commit unless explicitly asked.
   - NEVER merge/rebase between branches (I'll do this by hand).
   - NEVER pull/push to the github remote (I'l do this by hand).
