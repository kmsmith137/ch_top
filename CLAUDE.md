This directory is a "container" git repo that holds three sub-repos
(plain standalone clones, not git submodules or subtrees):

  .          container repo (xwt.toml, this file, the ch-* skills)
  ./pipmake  pip build backend used to compile ksgpu/pirate
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

The 'pirate' directory contains a new real-time FRB search, under development
for the CHORD radio telescope, that will supersede a search code that we wrote
a few years ago for CHIME. (The old CHIME search is scattered across ~10 git
repos, mainly 'bonsai', 'rf_pipelines', and 'ch_frb_l1', see below.)

The repos are managed with xwt (named multi-repo worktrees, configured by
xwt.toml; see ~/git/xwt/README.md). All pathnames below are relative to a
"grouping" dir, usually ~/ch:

  top/         -> the toplevel: plain clone of ch_top (main branch)
  top/pipmake  -> plain clone (main branch)
  top/ksgpu    -> plain clone (kms branch)
  top/pirate   -> plain clone (kms branch)

  extern/      -> external reference source trees (see below)

For each feature, `xwt new NAME` makes a worktree of all 4 repos, on a new
branch NAME. For example, if the feature is named 'dev':

  dev/        -> git worktree of top
  dev/pipmake -> git worktree of top/pipmake
  dev/ksgpu   -> git worktree of top/ksgpu
  dev/pirate  -> git worktree of top/pirate

Each workspace (the toplevel or a worktree) has its own .venv, with editable
installs of pipmake, ksgpu and pirate, activated by direnv (.envrc, generated
by xwt). After changing compiled code, rebuild with `xwt venv`, run from the
workspace root.

The first thing you should do on startup is run `xwt status`: it says
whether you are in the toplevel or a worktree, and shows the state of every
repo.

If you are making edits in any of the sub-repos (pipmake, ksgpu, or pirate),
then you MUST read the per-subrepo CLAUDE.md (e.g. ./pirate/CLAUDE.md)
which contains additional instructions.

The grouping dir's extern/ holds source trees for some external software that may
be useful as a reference. For most tasks you won't need them. From a worktree it
is a sibling, i.e. ../extern.

Libraries which are directly related to pirate:

  ../extern/asdf-cxx          -> Erik Schnetter's asdf reader/writer (submoduled into 'pirate')
  ../extern/chord-frb-sifter  -> real-time code "downstream" from pirate
  ../extern/simpulse          -> python2 simulation code (vendored into 'pirate' with modifications)

Libraries which are consumers of 'ksgpu', but not directly related to 'pirate'.
(Rarely needed, but sometimes relevant if we're making backward-incompatible changes
to ksgpu):

  ../extern/direct_sht        -> real-time code "downstream" from the FRB search
  ../extern/gpu_mm            -> real-time code "downstream" from the FRB search
  ../extern/n2k               -> real-time code "downstream" from the FRB search

The old CHIME FRB search code (split across 12 repos):

  ../extern/bonsai            -> dedispersion transform [dstn-sps]
  ../extern/ch_frb_io         -> file and networking IO code [kms_chord]
  ../extern/ch_frb_l1         -> top-level FRB search server for CHIME [dstn-master]
  ../extern/ch_frb_rfi        -> helper functions for constructing RFI transform chains
  ../extern/pyclops           -> python linkage (low-budget homegrown pybind11)
  ../extern/rf_kernels        -> x86 compute kernels (not gpu kernels)
  ../extern/rf_pipelines      -> high-level framework for organizing RFI flagging, plotting, etc. [dstn-master]
  ../extern/simd_helpers      -> x86 inline helpers
  ../extern/simpulse          -> python2 simulation code (vendored into 'pirate' with modifications)
  ../extern/sp_hdf5           -> higher-level interface for libhdf5 [kms_1_10]
  ../extern/spshuff           -> supports a compressed format [apr_slow_pulsar]
  ../extern/web_viewer        -> web viewer, for inspecting "offline" analysis

These repos should be on main/master branches, except for cases where [branch_name]
is noted in square brackets.

If there is anything that you would like me to add to 'extern', please let me know
(for example, source code for a third-party library).

CRITICAL: things not to do:
   - Do not git commit unless explicitly asked.
   - NEVER merge/rebase between branches (I'll do this with `xwt rebase-down`
     and `xwt merge-up`). Don't run the xwt commands that change branches,
     worktrees or clones: xwt merge-up, rebase-down, new, delete, init,
     add-repo. (xwt status, diff and venv are fine.)
   - NEVER pull/push to the github remote (I'll do this by hand).
