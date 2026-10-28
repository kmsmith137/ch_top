---
name: ch-review-docs
description: Review the pirate Sphinx docs for correctness (esp. stale text) and maintain the auto-cross-linking
disable-model-invocation: true
---

You have four jobs for the pirate_frb docs (in the `pirate/` sub-repo):

  1. Review the docs for CORRECTNESS -- especially "stale" text. Code is
     updated frequently and the docs are often not kept in sync, so mentions of
     renamed/removed classes, methods, arguments, defaults, file paths, CLI
     subcommands, and RPCs drift out of date. Find and fix these.
  2. Maintain the auto-cross-linking (the autolink Sphinx extension).
  3. Check that every multi-line python docstring opens with a one-line summary
     followed by a blank line, and fix the ones that don't.
  4. Check that each class in the python class reference explains how the class
     is created in typical use (constructor, factory, or what returns an
     instance).

This is a LARGE task. Split it among parallel subagents and aggregate the
results, the same way as the other review commands (ch-review-pybind11,
ch-review-stoppable). Do NOT git commit (per CLAUDE.md) -- leave all changes
for the user to review. Best-effort throughout: a wrong "fix" to the docs is
worse than a stale sentence, so verify before you edit.

What "the docs" are (all in the `pirate/` sub-repo):
  - class/method docstrings, which render on the pages under
    `pirate/docs/source/classes/` (sources: `pirate_frb/*.py`, the pybind11
    string literals in `src_pybind11/*.cpp`, and the per-class injector
    modules, which both apply the method injections and re-export the class --
    `pirate_frb/core/*.py` and `pirate_frb/rpc/*.py`);
  - CLI help/description/epilog text in `pirate_frb/__main__.py` (rendered on
    the `cli/*` pages);
  - `notes/*.md` at the repo root (rendered as the `notes/*` pages);
  - per-field comments in `configs/**/*.yml` and `grpc/*.proto`;
  - the hand-written pages `docs/source/*.md`.

## Part 1 -- correctness / stale-text review (the large part)

The failure mode is always the same: the code changed and the prose describing
it did not. So a reviewer must read BOTH the doc text AND the code it describes,
and flag every mismatch. Look for:
  - classes / methods / functions that were renamed or removed but are still
    named in prose;
  - CLI arguments, defaults, flags, or subcommands that no longer match the
    `parse_*()` definitions in `pirate_frb/__main__.py`, or behavior that
    changed;
  - file paths, config filenames, RPC / proto message names, and directory
    layouts that no longer exist (cross-check the autolink report's
    `missing-config-page` and `unknown-cli` skips -- those are machine-found
    stale references, a useful starting seed);
  - example code / commands that would no longer run as written;
  - descriptions of behavior, invariants, or data layouts that the code has
    since changed;
  - broken cross-references (Sphinx build warnings flag these -- see Part 2).

Split the work among subagents by area, for example:
  - one per group of class docstrings vs their implementation;
  - one for the CLI help-text vs the argparse definitions and actual behavior;
  - one (or a few) for `notes/*.md` vs the subsystems they describe;
  - one for config / proto field comments vs the code that parses them.

Give each subagent its exact file list and absolute repo paths, and have it
return structured findings: for each, the file:line, the stale claim, the
current truth (with a code reference), and a suggested fix. As the orchestrator,
aggregate the findings and VERIFY each against the code before acting -- kill
anything you cannot substantiate. Apply the clear-cut fixes to the source; list
anything ambiguous or judgment-dependent in your summary for the user to decide.

## Part 2 -- cross-linking maintenance

The cross-linking is done by a deterministic Sphinx extension
(`pirate/docs/source/_ext/autolink.py`) that turns mentions of documented
things into hyperlinks at build time; your job here is the judgment layer.

How the system works:
  - `pirate/docs/source/_ext/autolink.py`: derives a keyword registry each
    build from the Sphinx python domain (the autoclass pages under
    `pirate/docs/source/classes/`) plus the generated `configs/*`, `cli/*`,
    `grpc/*`, and `notes/*` page docnames, then rewrites each page's doctree to
    add links. The registry is auto-derived, so it never goes stale on its own
    -- a new autoclass page or config file becomes linkable with no action.
  - `pirate/docs/source/autolink_overrides.yml`: the curated layer you edit --
    `aliases` (phrase -> target, e.g. RPC method names -> a `.proto` page),
    `deny` (suppress a false-positive keyword globally or on one page), `policy`.
  - Per-page policy: on `notes/*` pages the extension only creates Sphinx-only
    links (classes, cli). A REAL-FILE mention (a `configs/*.yml`, `grpc/*.proto`,
    or sibling `notes/*.md` PATH) is left for a HANDWRITTEN markdown link in the
    notes source -- which also works on GitHub -- and reported as a
    `handwrite-in-source` candidate.
  - `pirate/docs/build/autolink_report.json`: written every build. `linked` =
    every link made (page, keyword, target). `skipped` = candidates it did NOT
    link, each with a `reason`.

Steps:

1. Build the docs (also validates that they compile; Sphinx warnings about
   broken xrefs / orphan pages are correctness signals for Part 1). conf.py /
   the extension may have changed, so build clean. Run as TWO invocations
   (never `make docs-clean docs` -- with -j the clean races the build, and a
   single invocation captures the file list before the clean):
       make -C pirate docs-clean
       make -C pirate -j 32 docs
   The build prints an `autolink: N links created, M skipped ...` line.

2. Read `pirate/docs/build/autolink_report.json`.

3. Triage `skipped` by reason:
   - `handwrite-in-source` (a real-file mention on a notes page with no
     handwritten link yet): add a markdown link to the notes SOURCE
     (`pirate/notes/<file>.md`, the tracked source -- NOT the generated
     `pirate/docs/source/notes/` copy). Use
     `[`configs/foo.yml`](../configs/foo.yml)`,
     `[`grpc/foo.proto`](../grpc/foo.proto)`, or `[notes/foo.md](foo.md)` for a
     sibling note. Preserve existing links; link the first clear prose mention
     (the extension stops nagging once the page links that target once). Never
     add a link inside a fenced code block. Keep notes ASCII-only (CLAUDE.md).
   - `missing-config-page` / `unknown-cli` (a `configs/...yml` path or
     `pirate_frb <word>` that names something nonexistent): almost always STALE
     TEXT -- fold this into the Part 1 fixes (correct the source so the mention
     is right, regardless of linking).
   - `unknown-class` (a CamelCase name with no autoclass page): the wishlist.

     ELIGIBILITY RULE -- only add an autoclass page for a class that is EITHER:
       (a) mentioned in the sphinx docs (any `notes/*.md`, `docs/source/*.md`,
           a rendered docstring, CLI help text, or a `configs/**/*.yml` /
           `grpc/*.proto` comment), OR
       (b) used in one of the `pirate_frb/run_*.py` scripts.
     A class that meets neither test does NOT get a page, no matter how central
     it looks in the C++ or how often it appears in internal code -- the class
     reference documents the classes a reader of the docs can actually encounter,
     not the whole binding surface. Conversely, a class meeting either test is a
     candidate even if the autolink report never flagged it (the report only sees
     CamelCase names that happen to appear in prose), so also sweep the run_*.py
     scripts directly rather than working only from the report.

     Then EXCLUDE a candidate that hits any of these, even if it passed (a)/(b):
       1. NO CLASS DOCSTRING. `autoclass` on a class with no docstring (and whose
          members have none either -- pybind11's auto-generated signature lines do
          NOT count) renders as a bare list of signatures with no prose. Give the
          class a docstring first, then add the page; don't ship an empty page.
       2. TANGENTIAL MENTION ONLY. The name appears only as an illustrative
          example of a convention rather than as a thing the text is about --
          e.g. the lists of "classes that use option 1 / option 2" in
          `notes/docstrings.md`, or a name cited in `notes/cpp.md` only to show
          a locking or teardown idiom. Being cited as an example of how we write
          code is not the same as the docs documenting that class.
       3. CLI HELP-TEXT ONLY. The only mentions are bare names inside `cli/*`
          help text listing what a flag runs (e.g. the kernel classes named in
          `pirate_frb test` / `time` / `show kernels` flag descriptions). Those
          name a test target, not a documented interface.
     Exclusions 2 and 3 are about the ONLY mentions. A class that is also
     described substantively somewhere -- a notes section, a config/proto comment,
     another class's docstring -- stays eligible.

     For a class that passes the rule and deserves docs, PROPOSE a new autoclass
     stub page: create `pirate/docs/source/classes/<Name>.md` containing
       # <Name>
       ```{eval-rst}
       .. autoclass:: <dotted.path>
          :members:
       ```
     and add `classes/<Name>` to the toctree in
     `pirate/docs/source/python_class_reference.md`. Confirm the dotted path is
     a real documented object (grep the package / pybind sources) before adding
     it -- and check it resolves to the CLASS, not to a same-named module: a
     package like `pirate_frb.rpc` that does not re-export the class will make
     `pirate_frb.rpc.<Name>` resolve to the module, and the page then renders as
     "alias of <module ...>" with an absolute filesystem path. Verify each new
     page in `pirate/docs/build/html/classes/<Name>.html` after the rebuild.
     Present these as proposals in your summary; create the stubs but call
     them out so the user can accept or drop them.
   - `denied`: expected (a curated suppression). Ignore unless a deny entry is
     now wrong.

4. Scan `linked` for problems:
   - False positives (a keyword linked where it shouldn't be, e.g. an English
     word colliding with a subcommand name): add a `deny` entry (scope it to the
     page if the collision is local).
   - Link spam (the same keyword linked many times on one page): note it; if it
     becomes a nuisance, the `policy.plain_text_matches` setting is the knob
     (currently `every`; `first_per_section` is the intended alternative, not
     yet enforced in code -- extending the extension is a bigger change, flag it
     rather than doing it silently).
   - Targets that moved / vanished.

5. Spot-check a few RENDERED pages in `pirate/docs/build/html/` (grep for
   expected `href=`): a class page (e.g. `classes/XEngineMetadata.html` -> its
   config link), one `cli/*` page (links render INSIDE the help `<pre>`), and
   `notes/grouper_interface.html`. Confirm no obviously wrong or ugly links.

6. If you changed anything (Part 1 source fixes, aliases, deny entries, stub
   pages, handwritten notes links), rebuild (step 1) and re-check the report to
   confirm the change did what you intended and introduced no new noise.

## Part 3 -- docstring summary lines

Every multi-line python docstring must open with a ONE-LINE summary, followed by
a blank line, then the body (PEP 257). Find every violation and fix it.

SCOPE: this rule ONLY. We are deliberately not enforcing the rest of PEP 257 --
do not "fix" closing-quote placement (the `"""` of a multi-line docstring sharing
its last text line), indicative-vs-imperative mood, or missing module docstrings.
Leave those alone unless the user asks.

Detect with an `ast` scan rather than by eye -- `ast.get_docstring(node,
clean=False)` over every Module / ClassDef / FunctionDef / AsyncFunctionDef in
`pirate_frb/**/*.py`. A docstring is multi-line if it has non-blank content after
its first non-blank line; it VIOLATES if the line immediately after that first
non-blank line is itself non-blank. Two traps, both of which produce a bogus list
if you get them wrong:

  - EXCLUDE generated files: `pirate_frb/rpc/grpc/*_pb2_grpc.py` are generated
    protobuf stubs, not ours to edit. Also skip `__pycache__`.
  - A docstring whose text starts on the line AFTER the opening `"""` is NOT a
    violation -- that is a permitted style variant. Find the first non-blank line
    and judge from there, or you will report roughly twice the real count.

Fixing: use your judgement per docstring, do not mechanically reflow.

  - If the summary is a single sentence that merely WRAPPED onto line 2, pull the
    remainder down below a blank line.
  - If the docstring opens with a PARAGRAPH (or with something that is not a
    summary at all -- a bare section heading like "Arguments", or prose like
    "Consider a situation where..."), it usually makes more sense to WRITE A NEW
    initial sentence saying what the thing is, and demote the original opening
    into the body -- rather than promoting the paragraph's first sentence.
  - Do not lose content: the body should keep everything the original said.

Note these docstrings are mostly NOT rendered by Sphinx (autosummary is not
enabled, and `autoclass :members:` renders the whole docstring), so the payoff is
in `help()`, editor tooltips, and LLM context -- not in the built docs. Expect the
autolink count to be unchanged. Verify with the same ast scan (it should report
zero), plus `compileall` and an import of every touched module.

## Part 4 -- how is this class created?

SCOPE: this part applies ONLY to classes that have an autoclass page, i.e. the
ones listed in the toctree in `docs/source/python_class_reference.md`. Take that
file as the definitive list. Every other class in the tree is out of scope here,
however tempting -- the internal helpers (RunServerHelper, SparseTile,
PfVarianceConvolver, the `*Injections` modules, the test rigs) are each constructed
at one call site and do not need this. Note this scope is NARROWER than Part 3, which
applies to every python docstring in the package.

For each class in that list, the docstring should explain how a caller gets an
instance in TYPICAL real-world use. Depending on the class, one or more of these
is appropriate:

  - constructor syntax;
  - factory function(s);
  - example code;
  - naming the function(s) ELSEWHERE that return instances, when that is the
    real-world mechanism. The model here is FileSubscriber: "Constructed via
    FrbSearchClient.subscribe_files()".

Watch for the classes that are never constructed from python at all -- their
instances only come out of some other call. They are easy to spot: their
`__init__` is an inherited `wrapper_descriptor` (no `py::init(...)` in the
binding), e.g. AssembledFrame, AssembledFrameSet, GpuDedisperserOutputs. These
are exactly the ones most likely to say nothing about creation, since there is no
constructor to describe.

Also note that a pybind11 class does NOT get its constructor args rendered in the
autoclass heading -- `inspect.signature` cannot read a pybind `__init__`, so the
page shows a bare `class Foo`. (Classes whose injector module defines a python
`__init__`, e.g. BumpAllocator / SlabAllocator / FrbGrouper, DO show args.) So for
a pybind11 class, do not assume the reader can see the signature: if the
constructor is the answer, spell it out in the docstring.

WHEN TO EDIT vs ASK: if the fix is clear-cut -- the mechanism is unambiguous and
you only need to state it -- just edit the docstring. If it involves a judgement
call (which of several mechanisms is the "typical" one, whether a class deserves
a worked example, how much detail is warranted), do NOT edit: describe the
proposed change in the chat at the end of the review and let the user decide.

Style for the "obtained from" pointers: just LIST the functions, with links. Do
not describe what each one does -- that clutters the docstring, and the reader
can click through. Write them fully qualified (`Class.method()`), which is the
form the autolink extension turns into a link; a bare `method()` will not link.
Verify each referenced member actually exists and is documented before writing
it, so the reference is not dangling. Note that a reference to a member of the
SAME class renders as plain text, not a link (self-links are suppressed by
design) -- still write it qualified, for the reader.

## Final report

Summarize: the stale-text / correctness issues you found and fixed (with the
code references that justify them), anything ambiguous left for the user to
decide, how many links exist now, the cross-linking changes (aliases, denies,
handwritten notes links), and any proposed new class stub pages to accept or
reject. Confirm explicitly that all docstring summary-line (Part 3) violations
have been fixed, and give the count. List the Part 4 class-creation docstrings
you edited, and separately the judgement-call ones you are proposing rather than
having applied. Remind the user nothing was committed.
