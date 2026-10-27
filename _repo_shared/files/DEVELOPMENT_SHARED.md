# Development Guide -- Shared Conventions

Shared / cross-repo development conventions.

**Repo-level conventions in the per-repo `DEVELOPMENT.md` take precedence when
they conflict with anything here.**

Some sections will not apply in every repo (Python conventions in a Rust repo,
markdown style in a repo without prose markdown). Skip sections that do not
apply.

## File conventions

### Shebangs

- Executable Python scripts use `#!/usr/bin/env -S uv run --script` with PEP
  723 inline dependency declarations. uv resolves the deps on each run; nothing
  is installed globally.
- Module-only files (imported, not executed) have no shebang.
- Shell scripts use `#!/bin/sh` or `#!/bin/bash` as appropriate.

### ASCII only

Source files, comments, commit messages, docs, PR bodies, and any other
persistent or externally-consumed content is ASCII only. The only carve-out is
test fixtures simulating non-ASCII input that the code under test must handle.

Common slips to watch for and the ASCII replacements:

- Em / en dashes (`--` instead).
- Curly quotes (straight `'` and `"`).
- Ellipsis (`...` instead).
- Unicode arrows (`->` instead).
- Unicode bullets (`-` or `*` instead).

### Comments

Comments augment the code -- they don't repeat what the code is already doing.
Use them to provide context, explain the why, document non-obvious requirements
or side effects, or flag invariants the type system can't enforce.

- Don't number steps in comments (`# 1. Parse state`), even for a canonical
  pipeline: the named operation is its own label, and adding / removing steps
  requires renumbering.
- Don't reference user-reported bugs ("Regression guard for the user-reported
  bug where ..."). Describe what the code does and the constraint it enforces;
  bug history belongs in the commit message.
- Don't talk about deleted, replaced, or formerly-existing code. Comments
  document the *current* code -- the version a future reader is looking at.
  Phrases like "the wrapper is gone", "this used to live in helpers.py",
  "replaced the per-call-site try / except" make sense to whoever wrote the
  diff but are noise (or actively misleading) to anyone reading the file later.
  If a comment names a symbol or behavior, that thing must exist now. Migration
  history belongs in the commit message that did the migration.

## Python conventions

- PEP 723 inline deps via `uv` -- no global `pip install`. Every script
  declares its own dep set in the script preamble and uv resolves them per run.
- Strive to be consistent in form and layout with other Python code in the
  repo.
- Line wrap at 79 chars.
- ruff and mypy compliant. Repos enforce this differently -- see the per-repo
  Testing section for how.
- Unused function / method / lambda parameters are flagged (ruff's `ARG`
  rules). Remove a dead parameter. For one that must stay (a callback
  signature, an interface override), mark it unused at the signature: prefix it
  with `_`, or absorb it in `**_kwargs` when callers pass it by keyword. Never
  `del` it in the body to appease the linter; that hides the unused-ness from
  the signature. A pytest fixture needed only for its side effect must keep its
  name, so request it with `@pytest.mark.usefixtures("name")` and drop the
  parameter, or suppress the single line with `# noqa: ARG001`.
- Strongly typed. Don't use `Any` for a value this code inspects or accesses --
  model it with a `TypedDict`, dataclass, or pydantic model (a bare
  `Dict[str, Any]` standing in for structured data is the usual offender).
  `Any` is acceptable only for an opaque handle: a blob received from one place
  and passed to another, never inspected in between.
- Don't route structured data through an untyped `dict` -- especially not one
  built up key-by-key and splatted as `**kwargs` into a typed constructor. mypy
  validates field names and value types when you assign them on a dataclass /
  `TypedDict` / model, but not when you stuff them into a bare dict, so shape
  errors slip to runtime and surface only where a test happens to exercise that
  path. Construct the typed object directly (or parse into a `TypedDict`)
  instead.
- Don't overload `str` / `int` for a closed set of values. When a return (or
  field, or parameter) is one of a fixed set of tokens -- a status, kind,
  outcome, or discriminant -- model it as an `Enum`, not a bare `str` whose
  magic values get hard-coded at every call site. Reach for `StrEnum` /
  `IntEnum` when the value must also serialize as its plain string / int (e.g.
  written to JSON and round-tripped), so the on-disk form is unchanged while
  the set stays closed, type-checked, and self-documenting.
- Import the module under test; don't load it with `importlib`. `mypy` types a
  module built via `SourceFileLoader` / `module_from_spec` as a bare
  `ModuleType`, so every attribute access on it resolves to `Any` and the
  test's uses go unchecked. Prefer a plain `import`; if the target isn't
  normally importable (e.g. an extension-less entry-point script), make it
  importable -- e.g. a `.py` alias symlink on the `mypy` / `sys.path` search
  path -- rather than loading it dynamically.
- All tools have well-defined return / exit values. A tool that surfaces
  success vs. failure to a wrapper script must do so via the exit code, not
  just stdout / stderr.
- Catch only specific expected exceptions. Avoid bare `except:` /
  `except Exception:`; when a broad catch is genuinely necessary, include a
  comment explaining why.
- Default to f-strings for dynamic strings and messages, not concatenation.
- Tests use `pytest` by default. If a different framework is more appropriate
  for a particular tool, justify the choice in the commit message.
- Mocks use `autospec=True` so argument verification happens.

## Docker conventions

- Docker Compose files (`compose.yml`, `compose.yaml`, `docker-compose.yml`)
  are linted with [dclint] via `npx dclint .` from the repo root. dclint
  enforces key ordering within services, requires explicit image tags, flags
  missing resource limits, and similar best-practice rules.
- A repo with compose files should pin the convention at the top of each file
  with a `# Keep linted: npx dclint .` header so the tool is discoverable for
  the next reader.
- When dclint flags a rule that is genuinely wrong for a given service,
  suppress it inline with `# dclint disable-line <rule-name>` rather than
  disabling the rule globally. Common case: tracking `latest` for an image
  needs `# dclint disable-line service-image-require-explicit-tag`.
- Resolve dclint warnings by fixing the file, not by widening the ignore list.
  Out-of-order keys, missing limits, and unset `restart` policies are real
  issues, not lint noise.

## Testing

Tools and test harnesses that launch Node set `NODE_DISABLE_COMPILE_CACHE=1` so
disposable worktrees do not accumulate compilation caches in the system
temporary directory. Keep pytest's numbered temporary directories so concurrent
runs stay apart; tune retention with its normal `tmp_path_retention_count` and
`tmp_path_retention_policy` settings.

- Add tests for new functionality. A change that adds a feature without a test
  is incomplete.
- During development, run the repo-shared tests and focused tests for the
  changed behavior, its callers, and shared dependencies. Include relevant
  end-to-end and platform checks, but do not run unrelated suites merely
  because they exist in the same repository. Respect GUI and integration opt-in
  flags; background runs must not display unrequested pop-ups.
- Green shared and focused checks are sufficient for development and
  independent review. Run the repository's full suite once before landing,
  after the change and review fixes are settled. Use its normal defaults;
  enable additional gated suites only when relevant or explicitly requested.
- Reuse passing results while the tested content, commands, and conditions
  remain applicable. After a narrow fix or a base change, rerun affected
  checks. A new commit hash alone does not require another full run; repeat the
  full suite only when changes or conditions invalidate its coverage.

### Isolated test failures

Let a full run finish and preserve its original results. If only one test
fails, rerun that test on the same candidate with equivalent test settings and
conditions. Do not restart the full suite or repeatedly retry to obtain a pass.

A passing rerun alone does not prove harmless flakiness. Analyze the original
failure and rerun, tracing changed code, callers, fixtures, dependencies, and
environment or timing effects. An unchanged test is not sufficient evidence
that the change could not have caused its failure.

If all other required checks completed successfully and the analysis finds no
plausible regression introduced by the change, flag the test as flaky and
consider the gates green without another full run. Report the test ID, original
failure, rerun command and result, and the evidence supporting that decision;
retain the original non-zero exit status in the test record.

If a plausible regression remains, keep the gates non-green and root cause the
failure. Fix the issue and rerun affected checks; broaden testing when the
cause or fix warrants it. A test that fails again does not qualify for the
passing-rerun exception.

## Markdown style

GitHub-Flavored Markdown (GFM). Tables, task lists (`- [ ]`), fenced code
blocks, and strikethrough are all fine.

### Tooling

Two complementary tools enforce markdown style:

- **`mdformat`** is the canonical formatter. Owns every mechanical formatting
  decision: line wrap (79 chars), ordered-list numbering, bullet / emphasis /
  strong markers, blank-line spacing, table alignment. Run via `uvx` with the
  GFM and frontmatter plugins:

  ```bash
  uvx --with mdformat-gfm \
      --with mdformat-frontmatter mdformat --wrap=79 --number <path>
  ```

- **`markdownlint`** (typically `markdownlint-cli2`) covers content rules
  `mdformat` can't see: required fence languages (MD040), broken anchor links
  (MD051), reference-link consistency (MD052 / MD053), missing alt text
  (MD045), duplicate headings (MD024), and similar. Config lives in
  `.markdownlint.json` at the repo root.

The two tools agree on every mechanical rule by design. If they ever disagree,
the formatter wins (it's mechanical) and `.markdownlint.json` gets adjusted to
match.

If the repo has a test suite, add tests that gate both: mdformat compliance
(running `mdformat --check` against the repo's markdown produces no diff) and
markdownlint compliance (no warnings). Without a gating test, both tools are
advisory and drift back in.

### Conventions

- Inline links by default. Use reference-style only when the same URL repeats,
  or when an inline link would force a line well past the wrap limit and can't
  reasonably be reflowed.
- Fence-tag conventions: `text` for plain output, `console` for shell sessions
  with prompts, `bash` / `python` / etc. for actual code. (MD040 requires
  *some* tag; this is which tag.)

### Source-layout gotchas

These aren't markdownlint rules but bite during reflow:

- Reference-style link definitions go at the bottom of the file, not
  interleaved with the list items they're referenced from. Otherwise mdformat
  splits the surrounding list into multiple sub-lists with mismatched bullet
  markers.
- Avoid lines starting with `>` followed by a non-space character (e.g. `>=10`)
  -- a markdown parser treats those as blockquotes, and source reflow can land
  them at line starts.
- Don't put `#<digit>` (issue references like `#1234`) at the start of a
  reflowed line -- they'd be interpreted as malformed ATX headings.

### Prefer lists over tables

In developer-facing markdown, prefer bulleted lists over markdown tables.
Tables are unreadable in plain text: columns wrap on narrow terminals, cells
run together, and headers blend into the body. We read these files in `vim` /
`less` / `git diff` more than in a rendered viewer, so source readability
matters more than rendered prettiness.

User-facing docs that are read primarily in HTML or on GitHub are exempt --
tabular layout works well for configuration / attribute reference sections in
those.

## Mixing user and developer content

When a doc contains both user-facing and developer-facing content, put user
content first. Users don't care about the developer content and shouldn't have
to wade through it; developers will read the whole thing regardless.

## Keep implementation details at the implementation

Implementation details belong in exactly one place: the implementation. A code
comment describes what the code right next to it does. A function's docstring
or summary describes how that function works and the contract it offers.
Documentation written for *consumers* of that function -- its callers, the
module-level overview, user-facing docs -- describes *what* it does and how to
use it, never *how* it does it internally.

Do not restate an implementation's behavior at the sites that consume it. When
you add an abstraction -- a platform layer, a helper, a wrapper -- the
per-platform or per-branch behavior lives in that layer's own body and
docstring. It does not get copied into every caller's comments, the global
module comment, and the user-facing docs. Smearing one detail across N
consumers guarantees it rots: the implementation changes in one place, nobody
audits the dozen paraphrases scattered across callers and docs, and they
silently decay into lies.

The test: if a comment or a doc paragraph describes behavior that lives in
*other* code, it is at the wrong altitude. Push it down to that code, or
replace it with the contract the consumer can rely on instead of the mechanism
the callee uses to deliver it.

## Commit messages

- Use `- component: Summary of change.` format. Match what's already in
  `git log`; the existing repo style is the source of truth.
- Keep the subject short and on one line. Wrap the body at about 72 columns:
  `git log` indents it four spaces, so a wider body overruns 80 columns. Never
  wrap a trailer; each stays on one line however long.

**Explain the why, not the what.** The diff already shows what changed. The
commit message should give a future reader the context they can't derive from
the diff: the motivating problem, the constraint or invariant the change
satisfies, and any non-obvious tradeoffs or alternatives considered. Aim for a
one-line subject plus one to three short paragraphs. Past three paragraphs and
you're almost certainly over-explaining.

Specifically, do NOT include:

- Lists of the files or call sites touched, under any label (`Touched:`,
  `Files changed:`, ...). If the scope is "every site of pattern X", say so
  once.
- Test inputs, fixture values, or the bad-shape cases a regression test
  exercises; the test is the source of truth.
- Sub-decisions obvious from the code, or restatements of an earlier paragraph.
- Symbols, tests, or files the same diff removes or replaces. A reader who
  greps for them finds nothing; describe the new artifact on its own terms.
- Pointers to ephemeral scratch -- `tmp/` files, review threads, "the plan".
  They do not survive in `git log`; if a constraint matters, restate it.
- Transient, machine-local, or private handles -- API keys, hostnames, local
  paths, private tracker or chat URLs. A commit message is a permanent record,
  world-readable on a public repo, and a stranger must be able to follow it
  years from now. Issue references against this repo's tracker (`Fixes #1234`),
  public upstream bug links, and authorship trailers stay.

[dclint]: https://github.com/zavoloklom/docker-compose-linter
