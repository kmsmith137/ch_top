This directory is a "container" git repo that holds two sub-repos
(just "bare" git clones, not git submodules or subtrees):

  .          container repo with orchestration scripts
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

Our setup is as follows. We start by bare-cloning all 3 repos
(these are called the "toplevel" repos):

  ~/ch_dev/        -> "bare" clone pointed at github remote
  ~/ch_dev/ksgpu   -> "bare" clone pointed at github remote
  ~/ch_dev/pirate  -> "bare" clone pointed at github remote

Then, for each feature we want to implement, we make git worktrees
for all 3 repos. For example, if the feature is named 'ch_test', then:

  ~/ch_test/          -> git worktree pointed at ~/ch_test
  ~/ch_test/ksgpu     -> git worktree pointed at ~/ch_test/ksgpu
  ~/ch_test/pirate    -> git worktree pointed at ~/ch_test/pirate

The first thing you should do on startup is figure out whether you are
in a worktree.

If I ask you to "git commit" (or similar) then you should commit
changes to all 3 local repos, but don't merge/rebase between branches
(if in a worktree) or push to the remote (if not).

Do not git commit unless explicitly asked.

If you are making edits in any of the sub-repos, then you MUST
read the per-subrepo CLAUDE.md (either ./ksgpu/CLAUDE.md or
./pirate/CLAUDE.md) which contain additional instructions.
