# Development Guide -- Shared Agent Conventions

Shared / cross-repo agent development conventions.

The companion [DEVELOPMENT_SHARED.md](DEVELOPMENT_SHARED.md) holds the shared
conventions for both humans and agents -- this file layers agent-specific
behaviors on top.

**Repo-level agent conventions in the per-repo `DEVELOPMENT_AGENT.md` take
precedence when they conflict with anything here.**

Some sections will not apply in every repo (Python conventions in a Rust repo,
markdown style in a repo without prose markdown). Skip sections that do not
apply.

## Working in any repo

- **Plan first.** Before making any changes, present a plan and wait for
  explicit approval. If the task changes mid-work or a new design discussion
  begins, stop making changes and return to planning.
- **Test baseline before changes.** Check for any associated tests (e.g. test
  files in `tests/`) and run them to establish a baseline. Flag any
  pre-existing testing problems before implementing planned changes -- a broken
  baseline affects how post-change tests are interpreted.
- **Re-run after changes.** After modifying any code or utility, run the
  associated tests (or the full suite if it's fast enough) before considering
  the change complete.
- **Look at file contents, not extensions.** Scripts that have
  `uv run --script` in their shebang are Python scripts, not shell scripts,
  regardless of file extension or lack thereof. Always open the file before
  assuming what kind of file it is.
- **Backups when debugging.** When debugging, if you're about to delete or
  significantly modify files, first make per-session timestamped backups
  including full host and path information -- e.g.
  `$REPO/tmp/backups/<host>/<YYYYMMDD-HHMMSS>/<full-path>` -- in case the
  originals need to be restored.
- **Match existing repo style.** Strive to be consistent in code style, form,
  and layout with what's already in the repo. When a recommendation in these
  shared instructions conflicts with the repo's actual practice, call out the
  conflict and follow the repo's convention.

## ASCII output in chat

Persistent content (files, code, comments, commit messages, PR bodies, docs) is
ASCII only -- see `DEVELOPMENT_SHARED.md` for the rule and the
slip-replacements list. Replies in the chat itself are display-only and
ephemeral, so non-ASCII is fine there; the rule only applies to anything
written to disk or sent to GitHub.

## Python installs

Never `pip install` anything -- not system-wide, not per-user
(`pip install --user`), not `pip3` either. Python deps come from PEP 723 inline
blocks resolved by `uv` per-run; if a tool needs a dep, add it to the script's
PEP 723 preamble or run via `uvx <tool>`. The user's system and per-user Python
environments are off-limits.

## Process management

Spawn background processes in a new process group so the whole subtree carries
a single kernel-recorded tag you set yourself. On Linux:
`setsid <tool> ... & SPAWN_PID=$!`. On macOS: `setsid -f <tool> ...`. The pgid
equals the leader PID, so `kill -- -<pgid>` later signals every process in the
group atomically, and a subprocess can't escape the group without explicitly
calling `setpgid()` itself.

Record the PID and pgid at launch time -- capture the background-task tool's
return, save `$!` for shell spawns, note any `--pidfile` path the tool wrote.
That record is what authorizes a later kill.

**Only kill processes whose ancestry traces back to your session, or whose pgid
matches a process group you spawned.** Anything else is off-limits. On a shared
developer machine, a process with a matching name routinely belongs to the
user's browser, editor, another agent session, or an in-flight test the user
started; killing it is unrecoverable from inside the killing session.

That rules out any kill target derived from a resource-sharing query -- name,
command-line substring, port, open file, working directory. The following are
banned no matter how narrowly scoped they look:

- `pkill <anything>`, `pkill -f <anything>`, `killall <anything>`.
- `pgrep <name-pattern> | xargs kill`, `ps ... | grep ... | xargs kill`.
- `lsof -ti <port-or-file> | xargs kill`, `fuser -k <port-or-file>`.
- Any pipeline of shape `<resource-match-query> | <kill>`.

If you lost track of the PID and pgid for something you spawned -- e.g. a
self-detaching tool launched without `setsid` and without capturing its
PID-bearing output -- stop and ask the user rather than fall back to a
resource-match query.

## Doc-sync is non-negotiable

The Doc-sync rule in `DEVELOPMENT_SHARED.md` is mandatory for every
agent-authored commit. **Every code change is a potential doc change.** Before
finalizing the commit message, grep the repo for any symbol, flag, convention,
or behavior the diff touched -- CLI surfaces, helper APIs, naming rules, test
layout, anything -- and update every doc that mentions it. If a doc references
stale state, it's part of the bug, not separate from it.

## Finish the work everywhere it applies

When a change addresses a problem that exists at more than one site -- a
duplicated pattern, a shared invariant, a contract that holds across parallel
modules -- the change addresses **every** site, not just the surfacing
instance. The duplication is a symptom; the fix targets the underlying cause.

Three concrete shapes:

- **Same bug in N places: fix all N, or lift to shared code.** If a defensive
  guard belongs around one call site, it belongs around every parallel call
  site -- or, better, baked into the shared helper they all reach.
- **Same test in N places: extract a generic base.** If you find yourself
  adding the same regression test to one utility's test file, the test belongs
  in shared test infrastructure -- a base class, a fixture in `conftest.py` --
  consumed by every parallel utility rather than copy-pasted across them.
- **Documented invariant violated in code: fix the code, not just the doc.**
  Adding docs that describe the canonical pattern while leaving the code
  divergent -- with a note that "the mechanical refactor stays open as
  remaining scope" -- does not deliver the invariant. Update the code in the
  same commit, or don't add the doc.

Re-tagging deferred work as "remaining scope" / "stays open as followup" /
"tracked separately" is paperwork, not progress. If you genuinely cannot finish
a piece in this commit (a real dependency, an in-flight refactor elsewhere, a
deliberate incremental rollout), call out the specific blocker -- not just a
hand-wave -- and confirm with the user that it's separable before deferring.

Before declaring a change complete, enumerate every site / instance / module
the change should affect and verify all are touched. Anything left as "stays
open" is a flag the change isn't actually done; check whether the deferral is
real or a rationalization.

Past staleness is never a license for new staleness. When a review finding (or
self-review) calls out a stale list, classification, table, or convention
adjacent to your change, do the full work to leave it correct -- including
restoring quality of pre-existing entries the change touches. If genuinely
out-of-blast-radius cleanup is needed elsewhere, surface it as a separate
suggested follow-up; don't use it to excuse skipping the in-scope work.

## SCM

### Never merge to `main` or push without explicit per-action approval

Work happens on a branch in a worktree (see below); committing there is fine.
Two actions need the user's explicit, per-action approval: merging onto `main`
(including a local fast-forward merge) and `git push`. Leave the work on its
branch and ask -- do not drop it onto `main` unprompted, even when the merge
would be a clean fast-forward.

This applies to every commit, including amended ones from code-review feedback.
Approval for one merge or push does not authorize subsequent ones.

### Reviewing commits with `npx difit`

The user reviews commits locally before authorizing a merge or push. When the
user asks to review a commit (or a stack), publish it with `npx difit`.
`npx difit` runs a web server, so the command does not exit immediately -- run
it in the background.

### All development work happens in a worktree under `$REPO/.wt/`

Never edit the main checkout directly. Every develop / build / test / debug
cycle runs in a `git worktree add` at `$REPO/.wt/<purpose>`, nested under the
repo's own checkout. Be sure that .gitignore contains .wt/. Once the user has
approved the merge and the work has landed on `main`, remove the worktree and
any branches you created as part of the development effort (but don't touch
other branches which may belong to other users or agents).

Development scratch -- plans, code-review write-ups, rejected-finding logs, any
`tmp/` working document -- does NOT go inside the worktree. Write it to the
main checkout's `$REPO/tmp/`, never `$REPO/.wt/<branch>/tmp/`. The worktree is
torn down when the work lands, taking anything under it with it; a plan or
review parked inside the worktree is lost on cleanup. The worktree holds only
the code being developed -- the durable paper trail lives in the main
checkout's `tmp/`.

### Stay in scope

Each commit edits only what its own description calls for. Adjacent cleanup
that "would be nice to do anyway" goes into a separate commit, OR is bumped
into a new entry in the relevant tracking doc.

### Stage explicit paths when hand-building a commit

When staging a commit by hand -- an initial commit or an amend -- name each
path with `git add <path>`. Don't reach for `git add -A` (nor `git add .` /
`git add -u`): a blanket add sweeps in whatever else is sitting in the working
tree -- scratch files, editor droppings, a stray `tmp/` artifact, an unrelated
debug edit -- and lands it in the commit unnoticed. Naming paths keeps each
commit to exactly what its description calls for. (Programmatic tooling that
stages a known-clean worktree it fully controls is the exception; this rule is
about an agent hand-building commits.)

### Working with local commits

Changes to existing local (unpushed) commits should generally fold into the
commit that introduced the affected code, not into new or follow-on commits. If
you think a change should be a follow-on, ask first.

When editing a commit mid-stack, be very careful not to leak functionality from
other commits into the commit you're editing. After amending, double-check the
commit to verify you didn't make this mistake. Mechanisms that help:

- If commits are orthogonal, reorder so the one being edited is at the top of
  the stack (using the backup-branch + cherry-pick technique below).
- If commits overlap, check out the commit that needs fixing, amend it with
  changes, then cherry-pick the other commits on top using the backup-branch
  technique below.
- If commits overlap, you can also make changes in new temporary commits that
  get moved around in the stack and folded into a lower commit (both operations
  done via the backup-branch + cherry-pick technique below).

### Never use `git rebase`

Not `rebase -i`, not `--autosquash`, not non-interactive `rebase <upstream>` or
`--onto`, and not any `GIT_SEQUENCE_EDITOR` automation. Reasons:

- The "review the todo in the editor" safety property doesn't hold for an agent
  invocation.
- Mid-rebase conflict resolution is a place silent loss happens.
- Empty commits are dropped by default without warning.
- The diff-vs-backup-branch safety check loses its teeth: intended
  conflict-resolution drift can no longer be distinguished from accidental hunk
  loss.

For folds, reorders, and mid-stack edits, use the backup-branch + cherry-pick +
amend technique below. To update a feature branch onto a moved base (the case
`git rebase main` would normally cover), use that same technique -- see its
moved-base variant below. Never resolve a moved base with a merge commit (see
below).

### Never use merge commits

Keep history linear -- never create a merge commit. The place this tempts an
agent is updating a feature branch onto a moved base: do not merge the new base
into the branch. Rebase it with the backup-branch + cherry-pick technique below
instead.

The other place it tempts an agent is landing a branch on `main` after `main`
has advanced past the branch's base. Do not create a merge commit, and do not
cherry-pick the branch's commits onto `main` directly. Instead rebase the
branch onto the new `main` tip (same technique), then fast-forward merge the
whole branch onto `main`. Rebasing happens on the branch; `main` only ever
advances by fast-forward.

### Backup-branch + cherry-pick technique

For mid-stack edits, folds, and reorders:

1. Create a local backup branch at the current branch's HEAD, named
   `backup/YYYYMMDD-HHMMSS-<descriptive-name>`.
2. Reset to the commit that needs to be updated.
3. Make the edits and amend the commit.
4. Cherry-pick the remaining commits from the backup branch back onto the
   current branch.
5. Run `git diff <backup-branch>` to verify the replay didn't silently drop or
   duplicate anything. For pure reorders or folds (no content change), the diff
   should be empty. For edits that change file content, the diff should show
   exactly the intended edit and nothing else.

The same technique applies to reordering commits in a stack: reset to the
appropriate ancestor, then cherry-pick commits back in the desired order. The
diff-check still applies (for pure reorders, the diff should be empty).

It also rebases a branch onto a moved base: reset to the new base commit (not
an ancestor of the branch), then cherry-pick the branch's own commits back on
top, resolving conflicts as they arise. Here the diff-check against the old
branch HEAD is *not* expected to be empty -- it should show exactly what the
new base introduces plus any conflict resolutions you made, and nothing else.
Anything more means a commit was dropped, duplicated, or mis-resolved.

To fold a later commit into an earlier one specifically, use the same
backup-branch + reset + cherry-pick technique. Do **not** use
`git commit --fixup` + `git rebase -i --autosquash` -- the "review the todo in
the editor" safety only holds for a human at the terminal, not for an agent
invocation, and a stale `--fixup=<sha>` can silently land in the wrong commit
or be dropped.

### Renames

When renaming and updating renamed files in git, do it in two commits. The
first commit contains only renames (so git history tracking works across the
rename). The second commit contains the actual file updates.

## Commit-message hygiene

`DEVELOPMENT_SHARED.md`'s "Commit messages" section is the canonical rule list.
A few patterns recur in agent-authored messages despite being on the do-NOT
list, so flagging them again here:

- **No `Touched:` / `Files changed:` / `Affected:` lists.** The diff enumerates
  every file; restating that as a labelled list duplicates it and rots whenever
  an amend changes the file set.
- **No references to symbols the same diff removes.** A subject like "Replaces
  the per-utility `_FooHelper.bar` with a generic base" is a trap: future
  readers grep for the named symbol and find nothing because the same commit
  deleted it. State the new artifact on its own terms.
- **No commit-history references.** "The followup notes ...", "the
  tmp/<slug>-... scope", "as discussed in the earlier review" all point at
  ephemeral agent-facing scratch. None of that survives in `git log`. If a
  constraint matters, restate it inline.
- **No plan references.** Sentences like "Two divergences from the plan's
  classification", "as the plan calls for", "the plan put X in Y" are dangling
  pointers -- plan files live in `tmp/` (gitignored), so a future reader of
  `git log` has no document to compare against. State what the commit does on
  its own terms; if a non-obvious choice matters, explain the choice itself,
  not what an unwritten alternative would have been.

Numbered step comments in code (`# 1. Parse input`, `# 2. Validate`, ...) are
forbidden by `DEVELOPMENT_SHARED.md`'s "Comments" subsection. Adding or
removing a step forces renumbering, and the function name plus code structure
already convey ordering. This applies even when describing a canonical pipeline
of steps -- the named operation is its own label.

## Comment-message hygiene

A code comment is read by someone looking at the *current* version of the file.
It must describe what is there now -- not what was there before, what was
deleted, what got renamed, or what got lifted into a helper. The canonical rule
lives in `DEVELOPMENT_SHARED.md`'s "Comments" subsection; the agent-specific
failure mode is repeating the commit-message rationale inside the source.

Concretely, never write comments like:

- `# The legacy _FooBar shim is gone -- now uses helpers.foo.`
- `# Wrappers have all been deleted; the dispatcher derives this directly.`
- `# This used to live in module_x.py; lifted to shared.py in the cleanup.`
- `# Replaced the per-call-site try / except with the shared guard.`
- `# Per the plan, this lives in helpers_runtime instead of helpers_lifecycle.`

The diff and commit message capture migrations. The comment captures the
*current* code only -- describe what the function does now and the constraint
it enforces. If the comment cannot be written without referencing something
that no longer exists, the comment isn't earning its keep; delete it.

The same applies to docstrings ("formerly known as `_FooBar`", "ported from the
legacy framework"), CHANGELOG-style banners at the top of files, and
`# TODO: remove once X` markers that name something already removed. If a
comment's content reads like a footnote on the diff, it belongs in the commit
message, not the file.

Example lists in this file (the bullets above, the "do NOT include" list under
Commit-message hygiene in `DEVELOPMENT_SHARED.md`) are illustrative, not
exhaustive. They're samples of patterns to recognise, not authoritative
enumerations -- when a similar-but-not-included entry shows up, the list
doesn't need to be extended for the rule to apply.

## Code review

After each agent-driven develop / test / commit cycle, the default is to spawn
a code-review subagent against the just-committed branch -- doc-only and
lint-config commits included. Agent-driven reviews like this run BEFORE the
user reviews the commit; if the user reviews and lands their own feedback, an
additional agent-driven re-review is not the default -- only run one if the
user explicitly asks for it.

After the review returns, address each finding directly in the commit (amend).
Findings the agent chooses NOT to address get appended to
`$REPO/tmp/<slug>-code-review-rejected.md` with reasoning, so the rejected set
stays visible for the user's review.

### Zero-context review

The review subagent must start with **zero authored context inherited from the
calling agent**. It does not see the calling agent's conversation, prior plans,
working notes, or any pre-framing of which decisions are "intentional". It
receives only two neutral inputs: the commit SHA and the absolute path to a
clean detached review worktree named only from that SHA. The path locates the
repository without adding human-authored framing. It then evaluates the commit
on its own.

This matters because pre-framing decisions as "intentional" is exactly how
regressions slip past review. The calling agent's job is to surface the SHA
neutrally; the review agent's job is to evaluate independently.

### Protocol

1. Create a clean detached review worktree at `$REPO/.wt/code-review-<SHA>`,
   where `<SHA>` is the full commit SHA. Reuse an existing path only when it is
   clean, detached, and at that exact commit. Never put a human-authored
   purpose or branch name in the review worktree path.
2. Spawn the review subagent with the prompt below, substituting `<SHA>` and
   `<REPO>` with the commit SHA and detached review-worktree path. Hand the
   agent nothing else -- no extra framing, no "we already decided X", no hints
   about which findings would be welcome.
3. Save the review to `$REPO/tmp/<slug>-code-review.md` (or
   `$REPO/tmp/<slug>-code-review-N.md` for amend cycles).
4. Remove the detached review worktree after saving the response. If it is
   unexpectedly dirty, retain it and surface the problem instead of forcing
   removal.
5. Address findings. For each finding, either fix it in the commit (amend) or
   append the rejected finding to `$REPO/tmp/<slug>-code-review-rejected.md`
   with reasoning on why it was rejected.

### The review prompt (verbatim)

Use exactly this prompt. Do not edit it to add context, reassurance, or
guidance about which decisions are intentional.

```text
You are reviewing a single commit on this repo. You have
zero context from any prior conversation -- evaluate the
commit on its own merits using only the inputs below and
the repo state.

Inputs:
- Authored intent: the commit message itself is the only
  authored statement of what this commit was supposed to
  do. Read it as the source of truth, but be aware it
  was written by the implementing agent after the fact
  and may rationalize choices that don't match the
  underlying problem.
- Commit SHA: <SHA>.
- Repo path: <REPO>, a clean detached review worktree
  named only from the commit SHA.

Use the supplied repo path as the working directory. Do not
search other repositories or the filesystem for the commit.
Prior reviews, plans, rejected-finding logs, reflogs, and
superseded versions of this commit are deliberately excluded
context. Do not inspect them. Review only the specified commit,
its parent, and the broader tracked repository state needed to
evaluate that commit.

You are free to read any file in the repo you need to
understand the broader context. A code review against the
diff alone misses regressions that only surface when the
change is read against its callers, consumers, and
surrounding invariants. Read the full affected file(s),
not just the diff. Run the local test suite as part of
the review.

Answer two distinct questions, separately:

1. Does the commit solve the problem it was supposed to
   solve? Is the diff in scope? Complete? Anything the
   authored intent called for that wasn't addressed?

2. Did the commit avoid regressing or breaking anything
   else? Specifically:
   - Local test suite green?
   - Any changes that go beyond the authored intent?
   - Any deleted or modified content the intent didn't
     call for?
   - Any docstrings or comments touched that are no
     longer accurate post-change?
   - Commit message: does it accurately describe what
     the diff does? Any rationalizations, omissions, or
     claims that don't match the actual change?
   - Doc-sync: did the diff touch anything with a doc
     footprint -- CLI surfaces, helper APIs, naming
     rules, test layout, conventions, behaviors -- that
     should have triggered a doc update but didn't? Read
     `DEVELOPMENT_SHARED.md` "Doc-sync rule" for the
     policy, then grep `*.md` for the changed symbols /
     conventions and flag any stale references.
   - For code diffs, evaluate the broader logic the
     changed code participates in. Read the affected
     file(s) in full plus any callers / consumers
     reachable from the changed symbols. Test-suite
     green is necessary but not sufficient.

Tag findings P1 (blocks) / P2 (must-fix-before-shipping)
/ P3 (nice-to-have).
```

### Valid vs. invalid rejection rationales

A code-review finding can be appended to
`$REPO/tmp/<slug>-code-review-rejected.md` only when the reasoning holds up on
its own merits. Examples of *valid* rejections:

- The finding is genuinely out of the diff's blast radius (a different file the
  diff didn't touch, behavior the change doesn't affect).
- The finding's "fix" would re-introduce a regression that an earlier commit
  already resolved.
- The finding is genuinely cosmetic and the fix would meaningfully enlarge the
  diff for negligible value (e.g. reflowing untouched surrounding lines just to
  follow a style guideline the existing code already violates).

The following rationales are NEVER valid for rejecting a finding -- they are
rationalizations for shipping a half-job:

- "The existing X is already incomplete / stale / broken, so fixing only the
  new piece would be inconsistent and a thorough sweep is out of scope." Past
  staleness is never a license for new staleness. If the change touched the
  stale surface (added entries to a list, modified a classification, edited a
  section), do the full work to leave it correct, including the pre-existing
  gaps the diff exposed.
- "It's only nice-to-have / P3, so it's optional." The P-tag indicates
  ship-blocking severity, not whether to do the work. P3 findings local to the
  diff still get fixed.
- "Adding it would be defensive against an unrelated future regression." If the
  surface is in the diff's blast radius, the agent owns making it correct now,
  not punting it to a hypothetical future agent.
- "Doing it thoroughly is out of scope." If the work is in the diff's blast
  radius, scope expanded the moment the diff touched the surface. Either do the
  full work or be specific about *which sub-task* is genuinely separable and
  offer a follow-up.

If a finding genuinely belongs in a separate follow-up commit (not just a
rejection), surface that as an explicit suggestion to the user with the
proposed scope, rather than self-rejecting. The user decides whether to fold it
in or defer.
