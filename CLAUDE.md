This directory is a "container" git repo that holds two sub-repos
(plain standalone clones, not git submodules or subtrees):

  .          container repo with orchestration scripts
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

Our setup is as follows. The toplevel clone and its feature worktrees live
together as siblings inside a "grouping" dir -- any dir except $HOME itself
(~/ch below; in this dev clone it's ~/docker). We start by cloning all 3 repos
into the toplevel (these are called the "toplevel" repos):

  ~/ch/ch_dev/        -> plain clone pointed at github remote (main branch)
  ~/ch/ch_dev/ksgpu   -> plain clone pointed at github remote (chord branch)
  ~/ch/ch_dev/pirate  -> plain clone pointed at github remote (kms branch)

Then, for each feature we want to implement, we make git worktrees
for all 3 repos. For example, if the feature is named 'ch_test', then:

  ~/ch/ch_test/          -> git worktree pointed at ~/ch/ch_dev
  ~/ch/ch_test/ksgpu     -> git worktree pointed at ~/ch/ch_dev/ksgpu
  ~/ch/ch_test/pirate    -> git worktree pointed at ~/ch/ch_dev/pirate

The grouping dir (~/ch) is also the sandboxed agent's Claude config home
(CLAUDE_CONFIG_DIR): ~/ch/.claude.json, ~/ch/.credentials.json, ~/ch/projects/.

The first thing you should do on startup is figure out whether you are
in a worktree. (Toplevel and worktrees are siblings in the grouping dir;
in a worktree, .git is a file; in the toplevel, it is a directory.)

If you are making edits in any of the sub-repos, then you MUST
read the per-subrepo CLAUDE.md (either ./ksgpu/CLAUDE.md or
./pirate/CLAUDE.md) which contain additional instructions.

The directory ~/git contains source trees for some external
software that may be useful as a reference. For most tasks,
you won't need to read these source trees.

  ~/git/pipmake           -> used in build system
  ~/git/chord-frb-sifter  -> real-time code "downstream" from the FRB search

CRITICAL: things not to do:
   - Do not git commit unless explicitly asked.
   - NEVER merge/rebase between branches (I'll do this by running the git-* scripts).
   - NEVER pull/push to the github remote (I'll do this by hand).
