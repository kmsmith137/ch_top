---
description: Multi-agent review of pirate's stoppable / thread-backed class patterns (stop cascades, wakeups, thread lifecycle, error propagation)
---

Please carefully review every stoppable and thread-backed class in pirate
against the design-pattern docs. This is a large task: split it between
parallel subagents (one per class) and aggregate the results, following the
process below.

## Background reading (orchestrator)

- Read pirate/notes/stoppable_class.md and pirate/notes/thread_backed_class.md
  into context. They define the patterns AND contain distilled rules from a
  previous review ("Error reporting", "pybind11 bindings", "Reviewer
  checklist") -- the review should measure the code against all of them.
- Read the "Concurrency" section of pirate/notes/cpp.md: the general locking /
  condition-variable / thread-lifecycle rules live there (the pattern docs
  point at it), and they are review criteria too.
- Also read the "GIL rules" and "Member bindings and thread-safety" sections
  of pirate/notes/pybind11.md (each class's pybind11 bindings are in scope).
- Do NOT read existing markdown plans (plans/*.md in any repo): the review
  should be "from scratch", unbiased by previous findings. All other file
  types are fair game.

## Enumerate the classes (orchestrator)

Make the list of stoppable and thread-backed classes by grepping
pirate/include/pirate/*.hpp for "stop(" and inspecting the results
(also grep for mentions of stoppable_class.md / thread_backed_class.md in
comments). For each hit, confirm it really implements the pattern (a
`stop(std::exception_ptr)` method plus is_stopped/error state), and classify
it: THREAD-BACKED if it owns worker std::threads whose lifetime is tied to
the object, otherwise plain STOPPABLE. Watch for classes whose header
filename differs from the class name (e.g. AssembledFrameAllocator lives in
AssembledFrame.hpp, GpuDedisperser in Dedisperser.hpp) and for several
pattern classes sharing one header. Expect on the order of 14 classes
(Barrier, CudaEventRingbuf, SlabAllocator, BumpAllocator,
AssembledFrameAllocator, FileWriter, Receiver, FrbServer, FrbGrouper,
GpuDedisperser, FakeXEngine, SimulatedFrameFactory, Hwtest, HwtestSender,
...); if you find far fewer, your grep is too narrow.

Assign each class a short stable ID prefix for findings (BAR, CER, SLB, BMP,
AFA, FIL, RCV, SRV, GRP, GPD, FXE, SFF, HWT, HWS, ...), unique across the
review.

## Process

1. Spawn one zero-context subagent per class, in parallel. Each subagent
   prompt must include:
   - the absolute repo path, the class name, which pattern applies
     (stoppable vs thread-backed), the finding-ID prefix, and the exact
     file list: the class's .hpp and .cpp, its section of
     pirate/src_pybind11/*.cpp, and any python-side injector/wrapper files;
   - an instruction to FIRST read pirate/notes/stoppable_class.md and
     pirate/notes/thread_backed_class.md (and, for the bindings, the "GIL
     rules" + "Member bindings and thread-safety" sections of
     pirate/notes/pybind11.md);
   - the requirement to verify every claim against actual code with
     file:line citations -- no speculation. Anything not fully verified is
     labeled "uncertain" with exactly what to check. Where a comment and
     the code disagree, say which is right: in the previous review, stale
     comments were about as common as real bugs, and both are findings;
   - a required output format (the agent's final message, ASCII-only
     markdown):
     (a) a one-line VERDICT (CONFORMANT / MINOR DEVIATIONS / VIOLATIONS);
     (b) a checklist table -- one row per pattern requirement, status
         OK / PARTIAL / VIOLATION / N-A, with file:line evidence;
     (c) numbered findings (prefix-1, prefix-2, ...), most severe first,
         each with: what/where (file:line), why it matters (for liveness
         bugs, the concrete hang/race scenario), and a suggested fix.
         Separate three categories: pattern violations; OTHER
         concurrency/correctness issues not directly stop-pattern-related
         (races, lost wakeups, UB -- these often matter more than
         conformance nits); and documentation/comment fixes;
   - permission to run small read-only commands (grep, sed) to verify
     findings, but no file modifications and no running of tests.

2. Priorities to emphasize in every subagent prompt: liveness first
   (hangs, deadlocks, lost/missed wakeups, waits that stop() cannot
   interrupt), then error-text propagation (cascades that drop the
   exception, generic messages where the root cause should surface), then
   data races (state published or read outside the mutex -- thread handles
   are the recurring case), then conformance details, then docs.

3. Spot-verify the highest-severity claims yourself (read the cited code)
   before reporting them. Kill findings that don't survive.

4. Aggregate everything into a single ASCII-only markdown file at
   pirate/plans/stoppable_pattern_review.md (ephemeral, never committed;
   overwrite any previous review). Structure:
   - a short header recording date, method, and the class list with
     per-class verdicts;
   - one section per class (verdict, checklist table, findings), keeping
     the per-class finding IDs;
   - a cross-cutting section for patterns that recur in several classes
     (IDs PAT-1, PAT-2, ...), each listing the classes it touches;
   - "Other issues (not stop-pattern related)" (OTH-*) and
     "Documentation / comment fixes" (DOC-*) sections collecting those
     categories across classes;
   - a final "Fix Summary (pick-and-choose)" section: every suggested fix
     under a stable identifier, organized by priority (P0 liveness /
     correctness, P1 error propagation, P2 conformance, docs last), one
     line each -- so that follow-up requests can say "fix SLB-1, PAT-3,
     OTH-2";
   - end with any proposed updates to the two pattern docs themselves
     (rules the review suggests adding, or doc text that is out of date).

5. In the chat, summarize: the per-class verdicts, the most severe
   findings, and any proposed pattern-doc changes. Then STOP and wait for
   me to select which findings to fix -- do not start fixing.
