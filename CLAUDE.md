This directory is a "container" git repo that holds two sub-repos
(plain standalone clones, not git submodules or subtrees):

  .          container repo with orchestration scripts
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

Our setup is as follows. The toplevel clone and its feature worktrees live
together as siblings inside a "grouping" dir -- any dir except $HOME itself (call
it $CH; ~/ch in these examples, ~/docker in this dev clone). Paths below are
RELATIVE to $CH: the grouping-dir name is arbitrary, relative paths read the same
inside the sandbox container, and only fixed system/home paths (e.g. ~/.ssh,
~/miniforge3) are written absolute. We start by cloning all 3 repos into the
toplevel (the "toplevel" repos):

  ch_dev/         -> plain clone pointed at github remote (main branch)   [toplevel]
  ch_dev/ksgpu    -> plain clone pointed at github remote (chord branch)
  ch_dev/pirate   -> plain clone pointed at github remote (kms branch)

Then, for each feature we want to implement, we make git worktrees for all 3
repos. For example, if the feature is named 'ch_test', then:

  ch_test/        -> git worktree of ch_dev
  ch_test/ksgpu   -> git worktree of ch_dev/ksgpu
  ch_test/pirate  -> git worktree of ch_dev/pirate

Also in $CH (siblings of the checkouts):

  claude/         -> the sandboxed agent's CLAUDE_CONFIG_DIR (.claude.json,
                     .credentials.json, projects/; per-group, separate from ~/.claude)
  extern/         -> external reference source trees (see below)

The first thing you should do on startup is figure out whether you are
in a worktree. (Toplevel and worktrees are siblings in the grouping dir;
in a worktree, .git is a file; in the toplevel, it is a directory.)

If you are making edits in any of the sub-repos, then you MUST
read the per-subrepo CLAUDE.md (either ./ksgpu/CLAUDE.md or
./pirate/CLAUDE.md) which contain additional instructions.

The grouping dir's extern/ holds source trees for some external software that may
be useful as a reference. For most tasks you won't need them. From a worktree it
is a sibling, i.e. ../extern:

  ../extern/pipmake           -> used in build system
  ../extern/chord-frb-sifter  -> real-time code "downstream" from the FRB search

Network egress (HTTP/HTTPS) is filtered by an allowlisting proxy. A request to a
domain that is not on the allowlist fails -- you will see a proxy "403" / "CONNECT
tunnel failed" error, or a body beginning 'sbox-net: egress to ... is not on the
allowlist', naming the domain. This is deliberate (a guardrail against prompt
injection and data exfiltration), not a bug to route around. When you hit a block,
the ONLY acceptable response is to surface it: tell me the exact domain and why
you need it (what you were doing, the URL or command), and let me decide. I
approve a domain on the host with `sbox-net allow <domain>`, after which you can
retry. You cannot approve it yourself -- the allowlist is read-only to you.

CRITICAL: things not to do:
   - Do not git commit unless explicitly asked.
   - NEVER merge/rebase between branches (I'll do this by running the git-* scripts).
   - NEVER pull/push to the github remote (I'll do this by hand).
   - NEVER bypass or evade the egress proxy. If a domain is blocked, ask me and
     explain why -- do NOT switch to a different mirror/domain/IP to dodge the
     allowlist, unset or rewrite HTTP(S)_PROXY, open raw sockets, or reach for
     another tool to get around it. Quietly working around a block is never
     acceptable, even if the alternative looks harmless.
