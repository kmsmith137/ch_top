#!/usr/bin/env bash
# sbox-common.sh -- shared setup for the sandbox launchers (sbox-claude, sbox-shell).
#
# SOURCED, not run. Each launcher does:
#     source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/sbox-common.sh"
# then runs its own command in the container. This file does everything up to
# building the podman invocation, leaving the argument array `a` (plus `IMAGE` and
# `WT`) in the caller's scope; the launcher appends its command and runs
#     podman "${a[@]}" "$IMAGE" <command...>
#
# The sandbox is "Model B": the kernel/container is the security boundary, so the
# agent runs with --dangerously-skip-permissions and never prompts. TRACKED and
# machine-independent (no rendering): the launchers + this file live at the worktree
# root, locate the worktree from THIS file's path, resolve the grouping dir + shared
# .git stores at launch, and INHERIT your shell's PATH + CONDA_PREFIX (so ~/.local/
# bin, conda, cuda, and the direnv-activated venv carry in -- launch from an
# activated worktree shell).
#
# Filesystem access is an ALLOWLIST (default-deny): the container sees ONLY the
# paths in the toplevel top's sandbox/ policy --
#   sandbox/fs-allow.txt   host paths the agent may see ("ro <path>" / "rw <path>")
#   sandbox/devices.txt    device nodes (--device; default: all GPUs)
#   sandbox/env-allow.txt  env vars forwarded from your shell (editor, locale, ...)
# Everything else (your other files, projects, and secrets) is simply absent --
# no masking needed. The grouping dir ($CH) is always read-write. Edit those and
# re-launch -- they are read every launch. See README.md "Sandbox and GPU".
set -euo pipefail
shopt -s nullglob                      # unmatched globs vanish (devices, subdirs)

PROG="$(basename -- "$0")"             # the launcher's name (sbox-claude/sbox-shell)
die()  { echo "$PROG: $*" >&2; exit 1; }
warn() { echo "$PROG: $*" >&2; }

IMAGE=docker.io/library/ubuntu:24.04   # base image; MUST track the host distro
                                       # (host /usr is overlaid RO -- bump on upgrade)
CUDA=/usr/local/cuda                   # system CUDA (under host /usr, mounted RO)

# Inherit the toolchain from your shell (set by ~/.bashrc + conda + direnv); the
# container reuses these rather than re-deriving them. Must be launched from an
# activated shell.
[ -n "${CONDA_PREFIX:-}" ] || die "no conda env active (CONDA_PREFIX is empty) -- \
activate your toolchain env first; the container inherits PATH + CONDA_PREFIX"

# --- locate this worktree (the launchers + this file live at the worktree root) --
WT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
[ -d "$WT/.git" ] && die "$WT is the toplevel (the unsandboxed management checkout). \
Run from a feature worktree, or use plain 'claude' here."

# --- locate the policy (in the TOPLEVEL top, shared by all worktrees) --------
# The toplevel = the ch_top repo's main worktree = the parent of its git
# common-dir (<toplevel>/.git); the grouping dir is one level above that.
gcd="$(cd "$WT" && git rev-parse --git-common-dir 2>/dev/null)" \
  || die "$WT is not inside a git repo"
gcd="$(cd "$WT" && cd "$gcd" && pwd)"                 # absolutize -> <toplevel>/.git
TOPLEVEL="$(dirname "$gcd")"                           # the top checkout
CH="$(dirname "$TOPLEVEL")"                            # grouping dir: toplevel + sibling
                                                      # worktrees + shared claude config
LISTS="$TOPLEVEL/sandbox"
ALLOW="$LISTS/fs-allow.txt"; DEVS="$LISTS/devices.txt"
# Fail CLOSED: the allowlist defines everything the agent can see.
[ -f "$ALLOW" ] || die "missing allowlist $ALLOW -- refusing to launch"

mkdir -p "$CH/claude"   # the agent's per-group claude config dir (CLAUDE_CONFIG_DIR)

# --- egress proxy (network allowlist) ------------------------------------------
# Route the agent's HTTP/HTTPS through sbox-net's per-group filtering proxy
# (started on first use, shared by every worktree in the group). A domain that is
# not in sandbox/net-allow.txt is blocked; the agent reports it and you run
# `sbox-net allow <domain>`, then it retries. Set SBOX_NO_PROXY=1 to bypass (open
# egress) while debugging. See README.md "Egress proxy".
PROXY_ENV=()
if [ "${SBOX_NO_PROXY:-0}" != 1 ]; then
  "$TOPLEVEL/sbox-net" start \
    || die "egress proxy failed to start (try '$TOPLEVEL/sbox-net status', or SBOX_NO_PROXY=1 to bypass)"
  purl="$("$TOPLEVEL/sbox-net" url)"
  PROXY_ENV=( -e HTTPS_PROXY="$purl" -e HTTP_PROXY="$purl"
              -e https_proxy="$purl" -e http_proxy="$purl"
              -e NO_PROXY="localhost,127.0.0.1,::1" -e no_proxy="localhost,127.0.0.1,::1" )
fi

# clean_lines FILE -> the file's meaningful lines: strip "#" comments and the
# surrounding whitespace, drop blanks. Missing file -> nothing. The shared
# tokenizer for every policy list below (devices, env-allow, fs-allow).
clean_lines() {
  local line
  [ -f "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] && printf '%s\n' "$line"
  done < "$1"
}

# expand_path TOKEN -> absolute paths (one per line): a leading ~/$HOME expands to
# your home dir, $CH to the grouping dir; then globs/words expand.
expand_path() {
  local p="$1" g
  case "$p" in
    "~"|"~/"*)              p="$HOME${p#\~}" ;;
    '$HOME'|'$HOME/'*)      p="$HOME${p#\$HOME}" ;;
    '${HOME}'|'${HOME}/'*)  p="$HOME${p#'${HOME}'}" ;;
    '$CH'|'$CH/'*)          p="$CH${p#\$CH}" ;;
    '${CH}'|'${CH}/'*)      p="$CH${p#'${CH}'}" ;;
  esac
  for g in $p; do printf '%s\n' "$g"; done
}

# read_list FILE -> clean_lines with ~/$HOME/$CH + globs expanded (used for devices).
read_list() {
  local line
  while IFS= read -r line; do expand_path "$line"; done < <(clean_lines "$1")
}

# --- network namespace (SBOX_NETNS, default 1 = private per-sandbox loopback) ----
# SBOX_NETNS=1: each sandbox gets its OWN network namespace via pasta, so its
# 127.0.0.1 is PRIVATE -- agents in different worktrees can bind the same loopback
# ports without colliding (and cannot reach each other's loopback services).
# pasta mirrors the host's default interface rather than inventing a NAT subnet
# (slirp4netns's default 10.0.2.0/24 collides with a real data network on some of
# our hosts), so internet egress still works; --map-gw makes the HOST's loopback --
# where the sbox-net proxy listens -- reachable via the container's default
# gateway, bridged back to the container's 127.0.0.1 by the forwarder below.
# SBOX_NETNS=0 restores the old shared host netns (shared loopback, and the
# host's real networks -- e.g. the 10.0.x data nets -- visible in the sandbox).
SBOX_NETNS="${SBOX_NETNS:-1}"
if [ "$SBOX_NETNS" = 1 ]; then
  NETOPT=( --network pasta:--map-gw )
else
  NETOPT=( --network host )
fi

# --- assemble the podman invocation --------------------------------------------
# network         : see SBOX_NETNS above (claude reaches the Anthropic API through
#                   the sbox-net proxy; push creds are simply not in the allowlist).
# --ipc host + --ulimit memlock : CUDA pinned memory / RDMA.
# --group-add keep-groups : preserve chord-dev/chord-users group reads.
# IS_SANDBOX=1    : lets claude accept --dangerously-skip-permissions as uid 0
#                   (single-id userns: container uid 0 == host you). See App. D.
# CLAUDE_CONFIG_DIR=$CH/claude : the agent's claude config/auth/transcripts live in
#                   <grouping dir>/claude (NOT your personal ~/.claude); auth is
#                   per-group -- '/login' once per grouping dir.
# PATH / CONDA_PREFIX are INHERITED from your shell (venv prepended for safety).
# Caches go to the tmpfs /tmp (home dirs are read-only or absent under the allowlist).
a=( run --rm "${NETOPT[@]}" --ipc host --ulimit memlock=-1:-1 --group-add keep-groups
    --tmpfs /tmp --tmpfs /run -w "$WT"
    -e HOME="$HOME" -e IS_SANDBOX=1 -e CLAUDE_CONFIG_DIR="$CH/claude"
    -e CLAUDE_ENV_FILE="$WT/.claude/env.sh"
    -e VIRTUAL_ENV="$WT/.venv" -e CONDA_PREFIX="$CONDA_PREFIX"
    -e PYTHONSAFEPATH=1 -e CUPY_CACHE_DIR=/tmp/cupy_cache -e XDG_CACHE_HOME=/tmp/cache
    -e LD_LIBRARY_PATH="$CUDA/lib64"
    -e PATH="$WT/.venv/bin:$PATH" )
if [ -t 0 ]; then a+=( -it ); fi
if [ ${#PROXY_ENV[@]} -gt 0 ]; then a+=( "${PROXY_ENV[@]}" ); fi

# --- in-container proxy forwarder (SBOX_NETNS=1 + proxy on) ----------------------
# The agent keeps the UNCHANGED proxy address http://127.0.0.1:PORT, but under a
# private netns that loopback is the container's own -- so each launcher prepends
# $FWD to the command it runs in the container: a socat relay from the container's
# 127.0.0.1:PORT to the host's loopback (reached via the default gateway, courtesy
# of pasta --map-gw), where sbox-net actually listens. The gateway is derived at
# runtime INSIDE the container -- nothing machine- or backend-specific is baked in.
# Empty (a no-op prefix) when SBOX_NETNS=0 or SBOX_NO_PROXY=1.
FWD=""
if [ "$SBOX_NETNS" = 1 ] && [ ${#PROXY_ENV[@]} -gt 0 ]; then
  FWD='port="${HTTPS_PROXY##*:}"; gw="$(ip -4 route show default | { read -r _ _ g _ && printf %s "$g"; })"; '
  FWD+='if [ -n "$port" ] && [ -n "$gw" ]; then socat TCP-LISTEN:"$port",bind=127.0.0.1,fork,reuseaddr TCP:"$gw":"$port" 2>/dev/null & '
  FWD+='else echo "sbox: WARNING: proxy forwarder not started (port=${port:-?} gw=${gw:-?}); proxied egress will fail" >&2; fi; '
fi

# Forward a curated allowlist of PREFERENCE env vars (editor, locale, pager,
# terminal, ...) BY NAME from the shell you launch in -- listed in env-allow.txt,
# one name per line. We forward by name, not the whole host environment (podman
# --env-host would copy any secrets/tokens in your shell into the sandbox), and
# only vars actually set in your shell. The STRUCTURAL vars wired up above (PATH,
# HOME, CONDA_PREFIX, CLAUDE_*, the proxy vars, ...) are owned by this script; if
# one is listed in env-allow.txt we skip it (with a warning) so a stray PATH entry
# can't clobber the venv. Missing file -> forward nothing (safe). The matching
# binary must also be on PATH in the container (via the RO /usr + conda mounts).
ENVALLOW="$LISTS/env-allow.txt"
ENV_RESERVED=" HOME PATH CONDA_PREFIX VIRTUAL_ENV CLAUDE_CONFIG_DIR CLAUDE_ENV_FILE \
IS_SANDBOX PYTHONSAFEPATH CUPY_CACHE_DIR XDG_CACHE_HOME LD_LIBRARY_PATH \
HTTPS_PROXY HTTP_PROXY https_proxy http_proxy NO_PROXY no_proxy "
while IFS= read -r line; do
  case "$line" in
    [!A-Za-z_]*|*[!A-Za-z0-9_]*)
      warn "env-allow.txt: skipping invalid var name '$line'"; continue ;;
  esac
  case "$ENV_RESERVED" in
    *" $line "*)
      warn "env-allow.txt: ignoring '$line' (set by the sandbox itself)"; continue ;;
  esac
  [ -n "${!line:-}" ] && a+=( -e "$line=${!line}" )
done < <(clean_lines "$ENVALLOW")

# (allowlist) mount ONLY the paths in fs-allow.txt, each :ro or :rw. Anything not
# listed is absent in the container -- your other files/projects/secrets simply
# aren't there (default-deny). Missing sources are skipped.
while IFS= read -r line; do
  mode="${line%%[[:space:]]*}"                         # first token: ro|rw
  rest="${line#"$mode"}"; rest="${rest#"${rest%%[![:space:]]*}"}"   # the path
  case "$mode" in ro|rw) ;; *) die "fs-allow.txt: each line must start with 'ro' or 'rw': $line";; esac
  [ -n "$rest" ] || die "fs-allow.txt: missing path on line: $line"
  while IFS= read -r p; do
    [ -e "$p" ] && a+=( -v "$p:$p:$mode" )
  done < <(expand_path "$rest")
done < <(clean_lines "$ALLOW")

# The grouping dir is ALWAYS read-write: it holds this worktree, its siblings, the
# toplevel, every repo's shared .git store (so commits work), and the agent's
# claude config (CLAUDE_CONFIG_DIR=$CH/claude). Podman applies deeper mounts last.
a+=( -v "$CH:$CH:rw" )

# (goal 5) device nodes from devices.txt (default: all /dev/nvidia*). Only existing
# CHARACTER devices are passed (skips the /dev/nvidia-caps directory).
while IFS= read -r dev; do
  [ -c "$dev" ] && a+=( --device "$dev" )
done < <(read_list "$DEVS")

# Keep the sandbox POLICY read-only even inside the RW grouping dir, so the agent
# cannot edit its own allowlist/devices to widen the sandbox on the next launch.
[ -d "$LISTS" ] && a+=( -v "$LISTS:$LISTS:ro" )

# (commits) the shared .git object stores are RW (under $CH), so `git commit`
# works. Pin each repo's config file and hooks/ dir :ro -- they are settings/code
# that execute in YOUR unsandboxed shell. See README.md App. E. (Defensive: if a
# store somehow sits outside $CH, RW it explicitly so commits still work.)
for repo in "$WT" "$WT"/*/; do
  [ -e "$repo/.git" ] || continue
  g="$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null)" || continue
  g="$(cd "$repo" && cd "$g" && pwd)"
  case "$g/" in "$CH"/*) ;; *) a+=( -v "$g:$g:rw" );; esac
  a+=( -v "$g/config:$g/config:ro" -v "$g/hooks:$g/hooks:ro" )
done

# Make sure the base image is present (one-time pull on first use).
podman image exists "$IMAGE" >/dev/null 2>&1 || podman pull "$IMAGE"
