---
description: Full test sweep (rebuild, ksgpu + pirate unit tests, chimefrb spot checks, toy + production quickstart searches with offline dedispersion); ~2.5 hours
---

Please run the full test sweep for the ch repos. Work from the worktree
root (the directory containing ksgpu/, pirate/, pipmake/). Total expected
runtime is roughly 2.5 hours; most of it is steps 6 and 7, and step 7 alone
is over an hour. The per-step estimates below are wallclock times actually
observed on cf05 -- treat them as a rough scale, not a budget: they move with
the hardware and with how much the unit-test suite has grown. Run the steps IN
ORDER -- each one gates the next. If a step fails, diagnose and fix it (see
"Bugs" below), then rerun that step before moving on.

Ground rules (these mirror CLAUDE.md; they apply throughout):

- Build with `make -j 32`, never plain `make`.
- Do NOT git commit, merge, rebase, pull, or push.
- Never bypass the network egress proxy.
- Set PYTHONUNBUFFERED=1 in the environment of every long-running process
  whose stdout you redirect to a file: python block-buffers redirected
  stdout, so log lines (including the readiness markers below) otherwise sit
  invisible in the buffer. C++ output flushes itself; python output does not.
- Keep all scratch files (logs, pid files, config copies) in an untracked
  location: the session scratch dir, /tmp, or pirate/plans/ (plans are
  never git-added). Put anything you would be sorry to lose -- the logs a
  step's verdict rests on -- in pirate/plans/. The session scratch dir does
  NOT survive a machine reboot, and a reboot mid-sweep otherwise takes the
  evidence for every step you have already passed with it.
- Waiting is not a plain `sleep`: the harness BLOCKS a foreground sleep, so
  `sleep 180; check` is refused outright. To wait for something, background
  an until-loop that exits when the condition is met -- `until <check>; do
  sleep N; done` with run_in_background -- and let the completion
  notification wake you. Most of this sweep is waiting (a ~20 min production
  stream, a ~10 min test suite and a ~90 min one), so get this right early
  rather than
  burning a tool call on the refusal.
- Anything that runs longer than ~15 minutes should be DETACHED rather than
  launched as a tracked background task -- step 7 above all (~90 min):

      setsid nohup env PYTHONUNBUFFERED=1 bash -c \
          '(time CMD) > pirate/plans/step7.log 2>&1; echo "exit=$?" >> pirate/plans/step7.log' \
          >/dev/null 2>&1 < /dev/null &

  then poll that log from later tool calls. The harness kills tracked
  background tasks when it believes the machine is low on memory, and on
  this machine it always believes so: step 0's hugepage pool is 1536 GiB of
  PINNED memory, so MemAvailable can never exceed ~24% of MemTotal however
  idle the box is. Step 7 was killed twice that way while peaking at 3.7 GB
  RSS with 449 GB free. A detached process is not tracked, so it survives --
  and it also survives the agent session restarting, which a tracked task
  does not.
- `pgrep -f` and `pkill -f` match YOUR OWN command line: the pattern you
  are searching for is sitting in the `bash -c` that does the searching. So
  a watcher like `until ! pgrep -f "bin/ksgpu test"; do sleep 10; done`
  never exits (it keeps finding itself), and `pkill -f memmon.sh` kills the
  very tool call that runs it. Both happened during the run these notes come
  from; the watcher spun for five days. Defeat it with a bracket in the
  pattern -- `pgrep -f 'pirate_fr[b] test$'` -- which still matches the
  target but not the literal text of your own command line.
- At the very start, record the sweep's start time -- `touch
  $SCRATCH/sweep-start` -- so the final inventory can tell what this run
  created from what was already on disk.

## Helper scripts

`pirate/misc/ch_test/` holds helpers for the mechanical parts of steps 5 and
6: launching a pipeline, checking the shutdown cascade, scanning logs, the
truth cross-check, the production preflight, the loopback config rewrite,
and the inventory table. Read `pirate/misc/ch_test/README.md` first; each
script also takes --help.

Use them -- they encode two harness facts that otherwise cost a wasted
pipeline run to rediscover (a backgrounded process does not survive across
your tool calls, and bash async jobs inherit SIGINT=SIG_IGN into python, so
`kill -INT` silently does nothing). But they are tools, not a substitute for
looking: they print numbers, and the judgment about what those numbers mean
stays yours. If a script's output disagrees with what you see in the logs,
believe the logs and treat the script as the bug (see "Bugs" below).

## Step 0: check the hugepage configuration (seconds -- but a HARD GATE)

This machine's hugepage pool gets switched to a smaller "debugging" layout
(256+256 GiB) from time to time. The sweep is only meaningful in the
intended layout, 768 GiB per NUMA node. Check it before anything else:

    for f in /sys/devices/system/node/node*/hugepages/hugepages-2048kB/nr_hugepages; do
        echo "$f = $(cat $f)"
    done
    grep -E '^HugePages_(Total|Free)' /proc/meminfo

Every node must read 393216 (393216 x 2 MiB = 768 GiB), and
HugePages_Total must be 786432 (= 1536 GiB across the two nodes).

If it does not match, STOP: do not run step 1, and do not run any later
step. Report the numbers you found in the chat, quote these commands for
the user to run, and wait for them:

    echo 393216 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages
    echo 393216 | sudo tee /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages

Do NOT run those yourself. They need sudo, and reconfiguring the machine is
the user's call, not yours. Once the user says they have run them, re-run
the check above and start the sweep only when both nodes read 393216.

Why this is a gate and not a warning: step 6 starts two production servers
at 'host_memory_per_server: 768 GiB' each, so a smaller pool fails that
step's preflight -- but not until ~45 minutes in, after steps 1-5 have
already been paid for. And the pool is pinned memory, so the two layouts
leave the machine with different amounts of ordinary RAM: timings and
memory behaviour measured under one do not carry over to the other, which
makes a sweep run under the wrong layout misleading rather than merely
incomplete. Checking costs a second.

(HugePages_Free well below HugePages_Total is a different problem -- some
process is still holding the pool. That is a stale-process question, not a
configuration one; see the leftover-process checks in step 5.)

## Step 1: rebuild both repos, then refresh the venv (fast if up to date)

The user may have merged or rebased since the last build. Rebuild ksgpu
FIRST (pirate links against it), then pirate:

    make -C ksgpu -j 32
    make -C pirate -j 32

Both must exit 0. After a merge/rebase an INCREMENTAL build occasionally
fails on stale objects; if a build fails with errors that look like
stale-state (missing generated files, undefined symbols that clearly exist),
run `make clean` in that repo and rebuild before treating it as a real
compile error.

Then refresh the venv's editable installs, from the worktree root:

    ./init-venv .

`make` rebuilds the native libs but does NOT update what pip has installed,
and a merge may have bumped a version or added a `[project.scripts]` entry
point. A stale editable install is how `ksgpu test` ends up "command not
found" while the source tree is perfectly fine. init-venv reinstalls
pipmake/ksgpu/pirate in dependency order (pirate requires `ksgpu >= 1.3.0`,
so ksgpu MUST be reinstalled first, or pip tries to fetch ksgpu from PyPI)
and finishes with an import smoke test. It must exit 0. It is a fast no-op
when everything is already current.

Do NOT `pip uninstall` anything first. `pip install -e .` already replaces
the old version, and it builds the new wheel BEFORE uninstalling the old
one, so a failed rebuild leaves the venv intact; uninstalling first turns a
build failure into an unusable venv that cannot be repaired without network
access.

init-venv needs no network as long as every declared dependency is already
satisfied. If it does reach for PyPI, something genuinely new is needed
(a newly added dependency, or a from-scratch `--recreate` venv, which must
fetch `editables`): report the blocked domain per CLAUDE.md, do NOT work
around it.

## Step 2: ksgpu unit tests (~3 min)

    ksgpu test

(equivalently `python -m ksgpu test`). Every test must report pass and the
command must exit 0.

## Step 3: pirate quick unit tests (~10 min)

    cd pirate && pirate_frb test -n 10

Must exit 0 with all tests passing.

## Step 4: chimefrb spot checks (~2 min)

A "spot check" runs one piece of the OLD CHIME FRB search -- the 11 repos
in ../extern that pirate supersedes -- and compares it against pirate's
equivalent. They are one-off correctness checks from the porting work, and
are deliberately NOT dispatched from `pirate_frb test`, since they need the
old pipeline built and the normal test suite must never require that. So
this sweep is the only thing that runs them regularly. Background:
pirate/notes/chimefrb.md, appendices A and B.

Two commands, both from the pirate/ directory:

    misc/chimefrb/build_oldpipe.sh                  # ~1 min
    misc/chimefrb/spot_checks/run_spot_tests.py     # ~40 s

The first builds the old pipeline into misc/chimefrb/oldpipe/ -- gitignored,
per-worktree, and safe to delete and rebuild at any time. It never touches
../extern (each repo is rsynced into oldpipe/src/ and patched there). Just
run it: it takes a minute whether or not oldpipe/ already exists, and the
spot-check drivers link against what it produces.

The second runs each check as a separate process and ends with "N/M spot
tests passed". All must pass and it must exit 0. `-l` lists the checks, and
a name argument runs one, which is how to iterate on a failure; a check's
test.py also runs directly, which is easier to read when debugging one.

- The build needs a conda env named `chimefrb` (python 2.7 plus the old
  C/C++ libraries) at /home/kmsmith/miniforge3/envs/chimefrb. It SHOULD
  ALREADY EXIST: the sandbox cannot create one, since miniforge3 is mounted
  read-only and the conda channels are not on the egress allowlist. If it
  is missing, STOP and ask the user.

- Several checks run pirate GPU transforms, so the GPUs must be free, as
  for the unit tests.

- An ImportError out of `pirate_frb.chimefrb` is NOT a failed comparison:
  it means the compiled pirate library is older than the python importing
  from it, i.e. step 1 did not really rebuild. Fix that and rerun. (This is
  what a skipped step 1 looks like here -- 12 of 14 checks died on
  `cannot import name 'AssembledChunk'` -- so it is worth recognizing on
  sight rather than debugging as a broken port.)

- Judging a numeric disagreement: each check states a tolerance and says
  WHY in the same place, so read that before deciding anything. Exact
  agreement is often the wrong expectation -- bonsai and pirate use
  dispersion constants that differ by 4.8e-7, and the old side is built
  -march=haswell with -ffast-math, so float32 agreement is at the 1e-5
  level. The checks are deterministic (each generates its input from a seed
  written down in its test.py), so a real disagreement reproduces; one that
  does not reproduce is itself worth reporting.

If the old pipeline fails to BUILD, misc/chimefrb/README.md has the
details: which branch each extern repo must be on and why, what the two
patches do, and two known issues. Several of its constraints look arbitrary
and are not (the `hdf5=1.10` pin especially), so read it before changing
anything.

## Step 5: toy quickstart search (~5 min)

Run the "toy search" end-to-end: fake X-engine -> FRB search server ->
grouper -> sifter, plus RPC monitoring, streaming to disk, a random-write
RPC, a clean shutdown-cascade check, and an offline-dedisperser pass over
the acquired data.

Before starting:

- Read pirate/notes/quick_start.md ("Running a toy search" and "Running an
  offline dedisperser"). It is the authoritative list of commands, ports,
  and flags -- do NOT rely on command lines memorized from this file, since
  the details may have changed. If anything is unclear, read the source of
  the command in question (pirate_frb/__main__.py and the run_*.py modules).
- Run every pirate_frb command from the pirate/ directory: the config
  files are passed by relative path.
- Check that the ports named in the configs are free and that no stale
  pirate_frb processes are running.

Launching the persistent processes (sifter, grouper, server, fake X-engine,
rpc_status -- each runs until interrupted):

- Write a plan file and launch them with
  `pirate/misc/ch_test/launch-pipeline.sh PLANFILE LOGDIR`, run in the
  BACKGROUND (it blocks until the pipeline exits). It launches each process
  with stdout+stderr to LOGDIR/name.log and its pid in LOGDIR/name.pid,
  gates each launch on the previous process's readiness marker, watches
  every log for errors while it waits, and writes LOGDIR/supervisor.log --
  poll that for "ALL READY" or "STARTUP FAILED". Name the processes sifter,
  grouper, server, xengine, rpc_status, which is what check-logs.py expects.
- Launch order is downstream-first: sifter, grouper, server, fake X-engine,
  then rpc_status (i.e. list them in the plan file in that order).
- The plan file supplies the readiness markers. As of this writing they are:
    - sifter:        "waiting for grouper(s) to connect"
    - grouper:       "waiting for FrbServer to connect"
    - server:        "server(s) started"  (the RPC port is not bound
                     until this line; toy init takes a few seconds)
    - fake X-engine: "FakeXEngine(s) running"
    - rpc_status:    "Running get_status"
  Re-derive them from the source if they have changed -- they live in
  run_toy_sifter.py, src_lib/FrbGrouper.cpp, run_server.py,
  run_fake_xengine.py and run_rpc_status.py. A marker that never arrives
  shows up as a supervisor timeout, so a stale marker is loud, not silent.

Streaming:

- Start a stream with rpc_start_stream, using the flags from
  quick_start.md. Save the printed acqdir name; the directory is created
  under the server's nfs_dir (printed at server startup).
- Use `-D` (run indefinitely) rather than a `-d DURATION`. -d is in seconds
  of DATA time, and the toy pipeline runs ~16x faster than real time, so
  quick_start's '-d 1000' expires after only ~60 s of wallclock -- which is
  about how long it takes to reach 2000 files and then do the random-write
  step, so the stream tends to deactivate itself moments before you cancel
  it, and the cancel path goes untested. With -D the stream ends only when
  you cancel it.
- Poll rpc_show_streams every few seconds until the stream has written 2000
  files (the "files: ... written = N" line). This takes ~30-40 seconds
  (the toy runs ~16x faster than real time). If the count stops growing,
  investigate.
- Note: with fpga_seq_start=0 ("start asap"), the acqdir's first time-chunk
  index is wherever the ring buffer currently is, NOT t=0. Expected.

Random-write RPC (while the stream is still active):

- Run rpc_rand_write (see quick_start.md). Verify it exits 0 and prints the
  filenames it wrote, that the same filenames are reported as received by
  the running rpc_status process, and that the files exist on disk in a
  rand_write_{date}_{time} acqdir under the NFS dir. ("metadata not yet
  available" here would be a real failure -- data is already flowing.)

Cancel + shutdown cascade:

- End the stream with
  `pirate_frb rpc cancel_stream -a STREAM_NAME ADDRESS...`. The flag is
  `-a`/`--stream-name`; `-s` is start_stream's filename STEM, and passing
  `-s` here fails with a bare argparse usage error that never mentions
  streams. Then verify via rpc_show_streams: status "inactive (cancelled)",
  files queued == written, errored == 0.
  Check the exit status carefully here: `cmd | tail -5` reports TAIL's
  status, not cmd's, so a failed RPC reads as a success. Use
  ${PIPESTATUS[0]}, or do not pipe.
- Send SIGINT to the sifter (the END of the pipeline) and verify the
  shutdown cascades: within a few seconds ALL five processes must exit.
  `pirate/misc/ch_test/check-cascade.sh LOGDIR sifter` does this: it finds
  every pid (including child processes, which matters for the production
  groupers), sends the signal, reports each process's exit time, the time its
  cascade message was PRINTED, and the last few matching log lines, and checks
  the resources came back. Read its output against the expectations below
  rather than just its exit status.
  Expected per-process behavior (these error messages are the documented
  "errors cascade backwards" path, not failures):
    - sifter: "interrupted; shutting down", exit 0
    - grouper: RuntimeError, sifter event not delivered
    - server: RuntimeError, grouper Session stream closed unexpectedly
    - fake X-engine: RuntimeError (MonitorRingbuf stream closed, or its own
      sifter send failing -- either is a valid cascade edge)
    - rpc_status: subscribe_files error, then "RPC client(s) stopped"
  Verify by PID that nothing lingers for more than ~10 seconds -- EXCEPT the
  production server (step 6), which takes ~25 s: it prints its RuntimeError
  within ~2 s like everything else, then spends the rest tearing down the
  1.5 TiB hugepage pool and 80 GiB of GPU memory. Judge the cascade by when
  the error is PRINTED, not when the process disappears; the toy server exits
  in ~1 s. The script's "cascade message times" block gives the print times
  directly -- read those, and expect every process (production server
  included) to be within a few seconds. Afterwards confirm the resources
  actually came back (HugePages_Free in /proc/meminfo, nvidia-smi at 0 MiB).
  (If you check for leftovers with pgrep -f, remember that it matches your
  own command line -- see the ground rules for the bracket trick. Note also
  that a process which has exited but not been reaped stays visible as a
  zombie -- PID 1 does not reap in this sandbox -- and a zombie still
  answers kill(pid, 0), so a naive liveness check reports long-dead
  processes as alive. Read the state field of /proc/PID/stat and treat 'Z'
  as exited.)

Offline dedisperser:

- Run 'pirate_frb run offline_dedisperser' on the stream's acqdir, with the SAME
  dedispersion config the toy server used (see quick_start.md). It must
  enumerate the beam(s), process every chunk, and exit 0.

What "looks reasonable" means -- check ALL of these in the logs, not just
exit codes. `pirate/misc/ch_test/check-logs.py --logdir LOGDIR --cascade
--acqdir NAME` mechanizes most of the list below and prints the numbers;
`check-truth.py` does the offline-dedisperser cross-check (the last and
fiddliest item). Both fail loudly rather than reporting a vacuous pass if a
log format has changed. Read what they print -- a green exit status with
implausible numbers is still a problem, and the numbers are the point:

- server: per-chunk lines advance steadily, each well-formed and
  newline-terminated (including the FIRST per-chunk line).
- grouper: per-chunk coarse_snr_max baseline roughly 5-9, spikes near the
  injected SNR when an FRB is present; nevents 0 on baseline chunks,
  >= 1 on spike chunks.
- fake X-engine: "injected FRB" lines with sane beam_id/dm/fpga_timestamp/
  snr fields, spaced by the configured gap.
- sifter: BOTH event streams arrive -- FROM_SIMULATOR (truth) and search
  events (grouper) -- and search detections correspond to earlier truth
  injections with similar beam_id and DM. (A truth message's fpga window
  can trail its events' timestamps; events are reported when scheduled.)
- rpc_status: ring-buffer counters advance monotonically; streamed
  filenames are reported; no errors before the deliberate SIGINT.
- rpc_show_streams: written grows, errored stays 0.
- rpc_rand_write: filenames in its output, in rpc_status, and on disk.
- offline dedisperser: baseline snr_max roughly 5, and a spike (near the
  injected SNR) for EVERY truth FRB on the streamed beam inside the
  acquired chunk range -- check this explicitly, don't eyeball it:

      pirate/misc/ch_test/check-truth.py --xengine-log LOGDIR/xengine.log \
          --dedisp-log DEDISP.log --beam 10 --freq-lo 400 --freq-hi 800

  (--freq-lo/--freq-hi are the first and last entries of zone_freq_edges in
  the dedispersion config used for the OFFLINE pass.) It converts each truth
  event's fpga_timestamp to a chunk index, opens a window running from a few
  chunks before it out to the end of the pulse's dispersion sweep, and
  requires a spike inside that window. Adjacent-chunk echoes are expected
  (rudimentary peak-finding), as are spikes BEFORE high-DM events
  (early-trigger trees); both are inside the window it uses.
- Scan every log for unexpected errors/warnings from before the SIGINT.

## Step 6: production quickstart search (~30-45 min)

Repeat the whole step-5 exercise using the "Running a production search
(cf00/cf05)" section of quick_start.md, with these deviations:

- Run EVERYTHING on the same node, including the fake X-engine (ignore the
  "MUST BE ON CF00" note).
- Environment check FIRST:

      pirate/misc/ch_test/preflight-prod.py configs/frb_server/cf05_production.yml

  It checks the check_mountpoints directories really are mountpoints, the
  ssd_dirs exist and are writable, the nfs_dir resolves ({user} needs $USER)
  and is writable, free hugepages >= num_servers * host_memory_per_server,
  the GPUs are visible and idle, the rpc_ip_addrs globs resolve and are
  exempt from the egress proxy, and loopback's MTU clears min_data_mtu.
  Run it when the GPUs are actually quiet: the idleness check reports any
  resident memory, so running it while step 3 or 7 is still going produces
  a 'warn gpu N: ... MiB used' that is just the unit tests, not a real
  problem. If anything is missing -- e.g. the sandbox was launched without
  the production storage mounts -- STOP and ask the user; the sandbox can only
  be changed from outside.
- The production config assumes the node's physical 10.x.x.x data NICs,
  which are not visible inside the sandbox (private network namespace).
  Rewrite them to loopback, into an UNTRACKED file (never edit the tracked
  config):

      pirate/misc/ch_test/make-loopback-config.py \
          configs/frb_server/cf05_production.yml $SCRATCH/cf05_loopback.yml

  Every data_ip_addrs entry becomes 127.0.0.1 with a UNIQUE port (all
  receivers now share one IP), and everything else -- memory sizes,
  dedispersion config, ssd/nfs dirs, check_mountpoints, MTU minimums -- is
  left byte-identical; loopback's MTU 65536 passes min_data_mtu. The script
  prints the lines it changed, so confirm nothing else moved. Pass the
  rewritten filename to 'run server' in place of the tracked one. If preflight
  reported that the rpc_ip_addrs globs do NOT resolve, re-run it with
  --rpc-loopback and use those addresses in all rpc_* commands.
- The production server takes on the order of a minute to initialize
  (async allocation of very large memory pools). Do NOT start the fake
  X-engine before the "All N server(s) started" line.
- There are multiple servers and groupers (one per GPU). Given multiple
  addresses, 'run toy_grouper' runs each grouper in a child subprocess; wait
  for BOTH "waiting for FrbServer" lines before starting the server (set the
  grouper line's count field to 2 in the plan file), and remember the
  cascade must take down the children too (check-cascade.sh tracks child
  pids, so they appear in its table as "grouper.child"). Give the server
  line a generous timeout -- ~300 s, since production init takes a minute.
- Use `-D` here too, for the same reason as in step 5: the point is to
  exercise the cancel path, and only -D guarantees the stream is still
  active when you cancel it. The arithmetic for -d is given below only so
  you can recognize a stream that expired on its own.
- Poll until the stream has written 1000 files (not 2000). If you do use
  -d, choose a duration that cannot expire early: -d is in seconds of DATA
  time; a stream writes one file per time chunk per streamed beam, and a
  chunk lasts time_samples_per_chunk * time_sample_ms (~2 s at production
  scale) -- so quick_start's example '-d 1000' yields only ~490 files and
  then deactivates naturally. For 1000 files use e.g. '-d 2500'. If a
  stream DOES expire naturally, that is not an error: verify its status is
  "inactive" WITHOUT "(cancelled)", then start a longer one.
- Expect ~20-30 minutes of streaming for the 1000 files: the production
  pipeline runs at only ~1.5x real time (~50 files/min). Sample the rate
  over a couple of minutes before trusting an ETA -- the first ~30 s reads
  far slower, because the stream only starts filling once the ring buffer
  has caught up.
- rpc_rand_write, cancel, cascade: as in step 5.
- Offline dedisperser: run on the 1000-file acqdir with the dedispersion
  config quick_start.md specifies for production acquisitions (NOTE: it
  differs from the config the server was started with). Expect a few
  minutes (~3 chunks/s at production scale).
- Truth cross-check as in step 5, but with the production band and a warmup
  allowance:

      pirate/misc/ch_test/check-truth.py --xengine-log LOGDIR/xengine.log \
          --dedisp-log DEDISP.log --beam 100 --freq-lo 300 --freq-hi 1500 \
          --warmup 8

  The two production-specific effects are already handled: a high-DM pulse
  sweeps MANY chunks (the window extends to truth tci + sweep, computed from
  the band edges), and a truth event within the first few chunks of the
  acquisition may legitimately have NO spike (dedisperser warmup -- the
  documented "boundary effects near the beginning of the acquisition").
  Those are reported as "warm" and excluded from the pass/fail count, so
  check how many there were rather than only the exit status.
- Diagnostic note: if an rpc command to the host's own IP fails with
  "HTTP proxy returned response code 403", the sandbox launcher predates
  the NO_PROXY node-local exemption in sbox-common.sh; report it (the user
  must relaunch the sandbox) rather than working around the proxy.

## Step 7: pirate full unit tests (~90 min)

    cd pirate && pirate_frb test

(the default is 100 iterations). Must exit 0 with all tests passing. Run
this AFTER the searches so a mid-sweep failure surfaces in the cheaper
steps first, and make sure no pipeline processes are still running (the
tests need the GPUs).

## Bugs

If a step fails, it is possible the bug is in the test procedure, not the
code being tested; you may also find errors in the documentation, the
config files, or the helper scripts in pirate/misc/ch_test/ (a script that
parses a log format is exactly the kind of thing that goes stale when the
format changes -- they are written to fail loudly rather than pass
vacuously, so a sudden "format changed?" error usually means the script
needs updating, not the code). Fix such bugs/errors as appropriate: fix,
rebuild, and rerun the failed step to verify. Do NOT git-commit anything --
summarize every fix at the end so the user can review with `git diff`. If a
failure requires a judgment call or design decision, pause and ask the user.

## Improving this procedure

You have just run this end-to-end, so you are the only one who knows where
it actually costs time. As you go, note anything that made the sweep rougher
than it needed to be:

- a fact you had to rediscover by experiment, rather than reading it here;
- a check you did by hand that is mechanical enough to script;
- an instruction that was ambiguous, stale, or left you guessing;
- a helper script that was missing a flag, produced output you had to
  post-process, or failed in a way that took a while to interpret;
- a judgment call you had to make on the fly that could be decided once,
  here, for every future run.

At the end, suggest concrete changes: prose edits to this file, or changes
to the scripts in pirate/misc/ch_test/. Roughly, mechanics and
deterministic analysis belong in the scripts; judgment, context and
warnings belong here (see pirate/misc/ch_test/README.md, including its "no
vacuous passes" rule for anything you add to a script). Suggest rather than
rewrite -- a test sweep should not turn into a refactor. An outright BUG in
the procedure or a script is different: fix that, per "Bugs" above. Having
nothing to suggest is a fine answer; don't invent friction.

## Final report

Finish with a complete report containing ALL of the following:

- Pass/fail for each step, 0 through 7.
- The timings you observed: build time, per-step durations, server init
  time, files/sec while streaming, offline chunks/sec.
- The acquisition inventory table (see below).
- Every fix you made, with file references, so the user can review with
  `git diff`.
- Anything you skipped, worked around, or that needs the user's judgment.
- Suggested improvements to this file or to pirate/misc/ch_test/, per
  "Improving this procedure" above (or a note that you had none).

### Acquisition inventory

The sweep writes tens of GB, so end the report with a table of everything
it created on disk -- one row per directory: path, size (`du -sh`), and a
short note on the contents (file count and chunk range for an acqdir).
Sweep BOTH nfs_dirs, and include the incidental directories (rand_write_*,
any cancelled or naturally-expired stream), not just the two main acqdirs:

    pirate/misc/ch_test/inventory.sh --since $SCRATCH/sweep-start \
        ~/pirate_toy /mnt/cs00/data/$USER

--since takes the file you touched at the start of the sweep, and classifies
each row as "this sweep" or "pre-existing" -- both nfs_dirs usually hold
acqdirs from earlier runs, and only the user can decide what to keep.

Format:

    | Path                                            | Size | Contents                    |
    |-------------------------------------------------|------|-----------------------------|
    | /mnt/cs00/data/{user}/prod_stream_{date}_{time}  | 28G  | 1014 files, chunks 29-1042  |
    | ~/pirate_toy/toy_stream_{date}_{time}            | 337M | 3913 files, chunks 2435-6347|
    | ~/pirate_toy/rand_write_{date}_{time}            | 180K | 2 files                     |

Do NOT delete any of it -- the user decides what to keep. But DO mark the
rows that are throwaway scratch (e.g. acqdirs from a debugging experiment
rather than from steps 5 and 6) so the user can clean up selectively.
