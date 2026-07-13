---
description: Review and tune the pirate Sphinx docs auto-cross-linking (autolink extension)
---

You are maintaining the documentation cross-linking system for the pirate_frb
Sphinx docs (in the `pirate/` sub-repo). The heavy lifting is done by a
deterministic Sphinx extension (`pirate/docs/source/_ext/autolink.py`) that
turns mentions of documented things into hyperlinks at build time; your job is
the judgment layer that keeps it healthy. This is best-effort: a missed link is
a cosmetic miss, not a failure. Do NOT git commit (per CLAUDE.md) -- leave
changes for the user to review.

## How the system works (read this first)

- `pirate/docs/source/_ext/autolink.py`: the extension. At build time it derives
  a keyword registry from the Sphinx python domain (the 11 autoclass pages under
  `pirate/docs/source/classes/`) plus the generated `configs/*`, `cli/*`,
  `grpc/*`, and `notes/*` page docnames, then rewrites each page's doctree to
  add links. The registry is auto-derived, so it never goes stale on its own --
  a new autoclass page or config file becomes linkable with no action here.
- `pirate/docs/source/autolink_overrides.yml`: the curated layer you mainly
  edit -- `aliases` (phrase -> target, e.g. RPC method names -> a `.proto`
  page), `deny` (suppress a false-positive keyword globally or on one page),
  `policy`.
- Per-page policy: on `notes/*` pages the extension only creates Sphinx-only
  links (classes, cli). A mention of a REAL FILE (a `configs/*.yml`,
  `grpc/*.proto`, or sibling `notes/*.md` PATH) is left for a HANDWRITTEN
  markdown link in the notes source -- which also works on GitHub -- and is
  reported as a `handwrite-in-source` candidate.
- `pirate/docs/build/autolink_report.json`: written every build. `linked` =
  every link made (page, keyword, target). `skipped` = candidates it did NOT
  link, each with a `reason`.

## Steps

1. Build the docs. conf.py / the extension may have changed, so build clean.
   Run as TWO invocations (never `make docs-clean docs` -- with -j the clean
   races the build, and a single invocation captures the file list before the
   clean):
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
     `pirate_frb <word>` that names something nonexistent): this is almost
     always STALE TEXT in a docstring / CLI help / note. Fix the source so the
     mention is correct, regardless of linking.
   - `unknown-class` (a CamelCase name with no autoclass page): this is the
     wishlist. If a name is heavily mentioned and deserves docs, PROPOSE a new
     autoclass stub page: create `pirate/docs/source/classes/<Name>.md`
     containing
       # <Name>
       ```{eval-rst}
       .. autoclass:: <dotted.path>
          :members:
       ```
     and add `classes/<Name>` to the toctree in
     `pirate/docs/source/python_class_reference.md`. Confirm the dotted path is
     a real documented object (grep the package / pybind sources) before adding
     it. Present these as proposals in your summary; create the stubs but call
     them out so the user can accept or drop them.
   - `denied`: expected (a curated suppression). Ignore unless a deny entry is
     now wrong.

4. Scan `linked` for problems:
   - False positives (a keyword linked where it shouldn't be, e.g. an English
     word colliding with a subcommand name): add a `deny` entry (scope it to
     the page if the collision is local).
   - Link spam (the same keyword linked many times on one page): note it; if it
     becomes a nuisance, the `policy.plain_text_matches` setting is the knob
     (currently `every`; `first_per_section` is the intended alternative, not
     yet enforced in code -- extending the extension is a bigger change, flag it
     rather than doing it silently).
   - Targets that moved/vanished.

5. Spot-check a few RENDERED pages in `pirate/docs/build/html/` (grep for
   expected `href=`): a class page (e.g. `classes/XEngineMetadata.html` -> its
   config link), one `cli/*` page (links render INSIDE the help `<pre>`), and
   `notes/grouper_interface.html`. Confirm no obviously wrong or ugly links.

6. If you added aliases / deny entries / stub pages / handwritten notes links,
   rebuild (step 1) and re-check the report to confirm the change did what you
   intended and introduced no new noise.

7. Report a concise summary: how many links exist now, what you changed
   (aliases, denies, stale-text fixes, handwritten notes links), and any
   proposed new class stub pages for the user to accept or reject. Remind the
   user nothing was committed.
