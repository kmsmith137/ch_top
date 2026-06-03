This directory is a "container" git repo that holds three sub-repos
(plain standalone clones, not git submodules or subtrees):

  .          container repo with orchestration scripts
  ./pipmake  pip build backend used to compile ksgpu/pirate
  ./ksgpu    GPU C++/CUDA core utils
  ./pirate   real-time FRB search engine

Our setup is as follows (all pathnames are relative to a "grouping" dir,
usually ~/ch):

  top/         -> plain clone of ch_top, pointed at github remote (main branch)  [toplevel]
  top/pipmake  -> plain clone pointed at github remote (main branch)
  top/ksgpu    -> plain clone pointed at github remote (chord branch)
  top/pirate   -> plain clone pointed at github remote (kms branch)
  
  extern/      -> external reference source trees (see below)
  claude/      -> the sandboxed agents' CLAUDE_CONFIG_DIR (.claude.json,
                   .credentials.json, projects/; per-group, separate from ~/.claude)

Then, for each feature we want to implement, we make git worktrees for all 4
repos. For example, if the feature is named 'dev', then:

  dev/        -> git worktree of top
  dev/pipmake -> git worktree of top/pipmake
  dev/ksgpu   -> git worktree of top/ksgpu
  dev/pirate  -> git worktree of top/pirate

The first thing you should do on startup is figure out whether you are
in a worktree. (Toplevel and worktrees are siblings in the grouping dir;
in a worktree, .git is a file; in the toplevel, it is a directory.)

If you are making edits in any of the sub-repos (pipmake, ksgpu, or pirate),
then you MUST read the per-subrepo CLAUDE.md (e.g. ./pirate/CLAUDE.md)
which contains additional instructions.

Network egress (HTTP/HTTPS) is filtered by an allowlisting proxy. A request to a
domain that is not on the allowlist fails -- you will see a proxy "403" / "CONNECT
tunnel failed" error, or a body beginning 'sbox-net: egress to ... is not on the
allowlist', naming the domain. This is deliberate (a guardrail against prompt
injection and data exfiltration), not a bug to route around. When you hit a block,
the ONLY acceptable response is to surface it: tell me the exact domain and why
you need it (what you were doing, the URL or command), and let me decide. I
approve a domain on the host with `sbox-net allow <domain>`, after which you can
retry. You cannot approve it yourself -- the allowlist is read-only to you.

The grouping dir's extern/ holds source trees for some external software that may
be useful as a reference. For most tasks you won't need them. From a worktree it
is a sibling, i.e. ../extern:

  ../extern/chord-frb-sifter  -> real-time code "downstream" from the FRB search

If there is anything that you would like me to add to 'extern', please let me know
(for example, source code for a third-party library, especially a case when the
egress proxy would prevent you from viewing it online).

CRITICAL: things not to do:
   - Do not git commit unless explicitly asked.
   - NEVER merge/rebase between branches (I'll do this by running the git-* scripts).
   - NEVER pull/push to the github remote (I'll do this by hand).
   - NEVER bypass or evade the egress proxy. If a domain is blocked, ask me and
     explain why -- do NOT switch to a different mirror/domain/IP to dodge the
     allowlist, unset or rewrite HTTP(S)_PROXY, open raw sockets, or reach for
     another tool to get around it. Quietly working around a block is never
     acceptable, even if the alternative looks harmless.
