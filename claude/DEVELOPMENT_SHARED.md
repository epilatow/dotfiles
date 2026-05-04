# Development Guide -- Shared Conventions

Shared / cross-repo development conventions.

**Repo-level conventions in the per-repo `DEVELOPMENT.md` take precedence when
they conflict with anything here.**

Some sections will not apply in every repo (Python conventions in a
Rust repo, markdown style in a repo without prose markdown). Skip
sections that do not apply.

## File conventions

### Shebangs

- Executable Python scripts use `#!/usr/bin/env -S uv run --script`
  with PEP 723 inline dependency declarations. uv resolves the deps
  on each run; nothing is installed globally.
- Module-only files (imported, not executed) have no shebang.
- Shell scripts use `#!/bin/sh` or `#!/bin/bash` as appropriate.

### ASCII only

Source files, comments, commit messages, docs, PR bodies, and any
other persistent or externally-consumed content is ASCII only. The
only carve-out is test fixtures simulating non-ASCII input that the
code under test must handle.

Common slips to watch for and the ASCII replacements:

- Em / en dashes (`--` instead).
- Curly quotes (straight `'` and `"`).
- Ellipsis (`...` instead).
- Unicode arrows (`->` instead).
- Unicode bullets (`-` or `*` instead).

### Comments

Comments augment the code -- they don't repeat what the code is
already doing. Use them to provide context, explain the why, document
non-obvious requirements or side effects, or flag invariants the type
system can't enforce.

- Don't number steps in comments (`# 1. Parse state`). Numbering is
  unnecessary and adding / removing steps requires renumbering.
- Don't reference user-reported bugs ("Regression guard for the
  user-reported bug where ..."). Describe what the code does and the
  constraint it enforces; bug history belongs in the commit message.
- Don't talk about deleted, replaced, or formerly-existing code.
  Comments document the *current* code -- the version a future reader
  is looking at. Phrases like "the wrapper is gone", "this used to
  live in helpers.py", "replaced the per-call-site try / except" make
  sense to whoever wrote the diff but are noise (or actively
  misleading) to anyone reading the file later. If a comment names a
  symbol or behavior, that thing must exist now. Migration history
  belongs in the commit message that did the migration.

## Python conventions

- PEP 723 inline deps via `uv` -- no global `pip install`. Every
  script declares its own dep set in the script preamble and uv
  resolves them per run.
- Strive to be consistent in form and layout with other Python code
  in the repo.
- Line wrap at 80 chars.
- ruff and mypy compliant. Repos enforce this differently -- see
  the per-repo Testing section for how.
- Strongly typed. Avoid storing structured data in a `Dict` with
  `Any` values -- use a `TypedDict`, dataclass, or pydantic model
  instead.
- All tools have well-defined return / exit values. A tool that
  surfaces success vs. failure to a wrapper script must do so via
  the exit code, not just stdout / stderr.
- Catch only specific expected exceptions. Avoid bare `except:` /
  `except Exception:`; when a broad catch is genuinely necessary,
  include a comment explaining why.
- Default to f-strings for dynamic strings and messages, not
  concatenation.
- Tests use `pytest` by default. If a different framework is more
  appropriate for a particular tool, justify the choice in the
  commit message.
- Mocks use `autospec=True` so argument verification happens.

## Testing

- Add tests for new functionality. A change that adds a feature
  without a test is incomplete.

## Markdown style

GitHub-Flavored Markdown (GFM). Tables, task lists (`- [ ]`),
fenced code blocks, and strikethrough are all fine.

### Tooling

Two complementary tools enforce markdown style:

- **`mdformat`** is the canonical formatter. Owns every mechanical
  formatting decision: line wrap (78 chars), ordered-list
  numbering, bullet / emphasis / strong markers, blank-line
  spacing, table alignment. Run via `uvx` with the GFM and table
  plugins:

  ```bash
  uvx --with mdformat-gfm --with mdformat-tables \
      mdformat --wrap=78 --number <path>
  ```

- **`markdownlint`** (typically `markdownlint-cli2`) covers content
  rules `mdformat` can't see: required fence languages (MD040),
  broken anchor links (MD051), reference-link consistency (MD052 /
  MD053), missing alt text (MD045), duplicate headings (MD024), and
  similar. Config lives in `.markdownlint.json` at the repo root.
  `~/.markdownlint.json` is a reasonable starting point when adding
  markdownlint to a new repo.

The two tools agree on every mechanical rule by design. If they
ever disagree, the formatter wins (it's mechanical) and
`.markdownlint.json` gets adjusted to match.

If the repo has a test suite, add tests that gate both: mdformat
compliance (running `mdformat --check` against the repo's markdown
produces no diff) and markdownlint compliance (no warnings).
Without a gating test, both tools are advisory and drift back in.

### Conventions

- Inline links by default. Use reference-style only when the same
  URL repeats, or when an inline link would force a line well past
  the wrap limit and can't reasonably be reflowed.
- Fence-tag conventions: `text` for plain output, `console` for
  shell sessions with prompts, `bash` / `python` / etc. for actual
  code. (MD040 requires *some* tag; this is which tag.)

### Source-layout gotchas

These aren't markdownlint rules but bite during reflow:

- Reference-style link definitions go at the bottom of the file,
  not interleaved with the list items they're referenced from.
  Otherwise mdformat splits the surrounding list into multiple
  sub-lists with mismatched bullet markers.
- Avoid lines starting with `>` followed by a non-space character
  (e.g. `>=10`) -- a markdown parser treats those as blockquotes,
  and source reflow can land them at line starts.
- Don't put `#<digit>` (issue references like `#1234`) at the
  start of a reflowed line -- they'd be interpreted as malformed
  ATX headings.

### Prefer lists over tables

In developer-facing markdown, prefer bulleted lists over markdown
tables. Tables are unreadable in plain text: columns wrap on narrow
terminals, cells run together, and headers blend into the body. We
read these files in `vim` / `less` / `git diff` more than in a
rendered viewer, so source readability matters more than rendered
prettiness.

User-facing docs that are read primarily in HTML or on GitHub are
exempt -- tabular layout works well for configuration / attribute
reference sections in those.

## Mixing user and developer content

When a doc contains both user-facing and developer-facing content,
put user content first. Users don't care about the developer
content and shouldn't have to wade through it; developers will
read the whole thing regardless.

## Doc-sync rule

**Documentation is part of the change, not a follow-up.** When code
changes, every doc that describes that code changes in the same
commit. No exceptions, no "I'll do the docs in a follow-up" -- doc
and code commit together so reviewers see both at once.

Before committing a code change, walk through every markdown file
the change could touch and verify it still matches reality.
Specifically:

- `DEVELOPMENT.md` and `DEVELOPMENT_SHARED.md` -- update when
  dev-process tooling changes (new test conventions, new lint
  rules, renamed or removed CLI flags on a tool, new required
  steps in the develop / test / commit cycle).
- `DEVELOPMENT_AGENT.md` and `DEVELOPMENT_SHARED_AGENT.md` --
  update when agent-specific workflow changes (review protocol,
  file markers, new agent-only conventions).
- Per-component / per-tool docs (where a component carries its own
  README or `--help` text) -- update when its CLI surface, options,
  or behavior changes.

Stale docs waste every reader's time -- users follow steps that no
longer work, devs chase behaviors the code stopped doing. **Every
code change is a potential doc change.** Before finalizing the
commit message, grep the repo for any symbol, flag, convention, or
behavior the diff touched and update every doc that mentions it.

## Commit messages

- Use `- component: Summary of change.` format. Match what's already
  in `git log`; the existing repo style is the source of truth.
- Include a `Co-Authored-By:` trailer for AI-assisted commits.

**Explain the why, not the what.** The diff already shows what
changed. The commit message should give a future reader the context
they can't derive from the diff: the motivating problem, the
constraint or invariant the change satisfies, and any non-obvious
tradeoffs or alternatives considered. Aim for a one-line subject
plus one to three short paragraphs. Past three paragraphs and
you're almost certainly over-explaining.

Specifically, do NOT include:

- Lists of every file or call site touched. The diff enumerates
  them; if the scope is "every site of pattern X", say so once.
  This applies to any prefix variant -- `Touched:`,
  `Files changed:`, `Affected:`, `Sites:`, etc. -- which is just
  the same list with a label.
- Test inputs, fixture values, or the specific bad-shape cases a
  regression test exercises. The test code is the source of truth.
- Sub-decisions that are obvious from the code (which field type
  was used, which helper the code now calls, how a loop is
  structured).
- Restatements of points already in an earlier paragraph of the
  same message.
- References to symbols, tests, functions, or files that the same
  diff *removes* or replaces. A subject like "Replaces the
  per-utility `_FooHelper.bar` with a generic base" is a trap:
  future readers grep for the named symbol and find nothing because
  the same commit deleted it. State the new artifact on its own
  terms; the diff already shows the deletion.
- Pointers to ephemeral scratch -- "the followup notes ...", "the
  tmp/<slug>-... scope", "as discussed in the earlier review",
  "the plan put X in Y". `tmp/` files, code-review threads, and
  review inputs are working state that does not survive in
  `git log`. If a constraint matters, restate it inline; if it's
  just a paper trail, drop it.

append @DEVELOPMENT_SHARED_AGENT.md
