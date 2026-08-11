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
- **Commit before post-change testing or review.** Commit each coherent change
  promptly so the state under validation is always inspectable. Once the
  working tree contains changes intended for the commit, including untracked
  additions, do not run tests or begin a review until those changes are
  committed. Amend that commit with incremental fixes before each retest or
  re-review rather than validating an uncommitted working tree.
- **A green implementer-owned full-suite gate precedes review.** After
  committing, the implementing agent runs the repo's full local test suite and
  applicable quality gates and gets a green result before spawning a review
  agent. Never hand broken code to a reviewer and make the reviewer discover
  failures that the required gate would have caught.
- **The per-commit gate: every commit in a stack, not just the tip.** When the
  work is more than one commit, run the full suite and the quality gates at
  each commit in turn, with nothing from later commits present. A stack whose
  tip is green routinely hides an intermediate that is not: a fix, a rename, or
  a test update lands one commit later than the change it repairs, and only the
  tip ever sees both. That intermediate is a real state the world will reach --
  `git bisect` checks it out, reverting the commit above leaves the tree
  sitting on it, and a CI job may build any commit of a pushed branch. Running
  a reduced suite (skipping the slow or browser tests, say) does not discharge
  this: an intermediate breakage hides precisely where the subset stops
  looking. Walk the stack in a gate worktree (see below) rather than in the
  branch's own, which would detach its HEAD.
- **Evaluate large commits before review.** After development and the green
  pre-review gate, pause before spawning the reviewer and ask whether a large
  commit combines logically separable changes. Smaller cohesive commits can
  shorten review cycles and keep fixes for one concern from introducing issues
  in another. Split only when each result is complete, independently
  understandable, and testable; keep tightly coupled implementation, tests, and
  documentation together. If a split changes the stack, rerun the full
  per-commit gate before review.
- **An independent code review precedes handoff.** Once the gates are green,
  the implementing agent spawns the reviewer itself, unasked. An unreviewed
  branch is not ready to hand off as finished. See [Code review](#code-review).
- **A green exact-candidate full-suite gate precedes every merge.** The
  implementing agent owns test execution. The pre-review run satisfies this
  gate when review produces no commit changes and the base has not moved. After
  review fixes, run the tests or gates affected by each fix, then run the full
  suite once on the settled candidate before requesting or acting on merge
  approval -- and re-run the per-commit gate if any commit below the tip
  changed, which a review-fix rebuild always does. Merge approval never waives
  either gate. If the base moved, replay the branch onto its current tip, run
  the full suite on that integrated tree, and re-run the per-commit gate as
  well: a replay rewrites every commit it carries over, so none of them has
  been gated in its new form. These are test gates only: rewritten commit SHAs
  do not by themselves invalidate completed reviews. See
  [Code review](#code-review) for the separate re-review triggers. Never merge
  first and test afterward.
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

## Use the built-in file editors

When the session exposes file-editing tools (Edit / Write / string-replace /
notebook editors), every file modification goes through them. Do not build
edits out of shell commands (`sed -i`, `awk ... > tmp && mv`, `echo >>`,
heredocs, `perl -pi -e`) or one-off Python scripts when an editor tool could
make the change.

The editor tools fail loudly and atomically: an edit either applies or the tool
errors, and the result is visible in the tool response. A chained shell edit
has neither property -- a mid-chain failure can leave the file part-modified or
untouched while the chain's overall exit status still reads as success, and the
session carries on believing the edit landed.

Legitimate non-editor cases, all of which own the whole transformation rather
than splicing content by hand:

- Purpose-built tools whose job is the rewrite: formatters (`ruff format`,
  `mdformat`), `ruff check --fix`, codemods.
- Whole-file moves and verbatim copies (`git mv`, `mv`, `cp` -- e.g. the
  debugging backups above) -- no content is being spliced.
- Bulk mechanical rewrites across many files where per-file editor calls are
  impractical. Script it as a single dedicated step -- never chained to
  anything else -- and verify the outcome with `git diff` / `grep` before
  moving on.

In a session with no editor tool, shell edits are unavoidable: run one command
per step, check its exit status, and verify the file content after each edit
rather than assuming the pipeline worked.

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

The user reviews commits locally before authorizing a merge or push. Never run
`npx difit` unless the user explicitly requests that tool. Do not start it as
part of the standard code-review cycle or handoff: it runs a web server and can
open or focus a browser window. When requested, run it in the background
because the command does not exit immediately.

### All development work happens in a worktree under `$REPO/.wt/`

Never edit the main checkout directly. Every develop / build / test / debug
cycle runs in a `git worktree add` under `$REPO/.wt/`, nested under the repo's
own checkout. For an agent-created branch-backed worktree, the relative path
under `.wt/` must exactly match the branch name: branch `<branch>` uses
`$REPO/.wt/<branch>`. Do not invent a separate worktree-purpose name. Detached
worktrees have no branch to match and follow their applicable naming rule: the
SHA-based code-review worktrees below, and `$REPO/.wt/gate-<SHA>` for the
per-commit gate, where `<SHA>` is the tip of the stack being walked. One gate
worktree serves the whole walk -- check out each commit inside it in turn, so
the suite's dependencies are installed once rather than per commit -- and it is
removed when the walk ends, not left for the merge. Keeping it off the
review-worktree path matters: the review protocol reuses and then deletes
`code-review-<SHA>`, and would take a gate worktree with it. Be sure that
.gitignore contains .wt/. Once the user has approved the merge and the work has
landed on `main`, remove the worktree and any branches you created as part of
the development effort (but don't touch other branches which may belong to
other users or agents).

Working in a worktree is not the same as *staying* in one. The shell keeps its
working directory between commands, so a single `cd` -- even buried in a
compound line whose real purpose was something else, like
`cd $REPO && git worktree remove ...` -- silently redirects every command that
follows it, for the rest of the session. The next `git reset --hard` or
`git commit --amend` then rewrites whatever branch the main checkout happens to
hold, which is usually `main`.

Two habits prevent it, and both are cheap:

- **Put the shell in the worktree once, and keep it there.** `cd` into
  `$REPO/.wt/<branch>` at the start and address every other checkout by
  absolute path from then on -- `git -C <path> ...`,
  `git worktree remove /abs/path` -- so the shell's own directory never moves.
  Removing the worktree the shell is standing in is the one move it cannot
  avoid, since that deletes the directory underneath it and every later command
  fails until it leaves. Do that step from the main checkout, once the work has
  landed and nothing is left to rewrite.
- **Confirm the target before any command that rewrites the current branch.**
  Before `reset --hard`, `commit --amend`, or `cherry-pick`, run
  `git rev-parse --abbrev-ref HEAD` and check it names the feature branch. It
  reads `HEAD` in a detached worktree and the main checkout's own branch there,
  so it blocks on the paths that need blocking rather than passing quietly. One
  line, and it is the difference between amending your branch and committing to
  `main` without approval.

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

0. Confirm `git rev-parse --abbrev-ref HEAD` names the feature branch. Step 2
   resets it, so getting this wrong rewrites whatever branch you are actually
   on.
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
6. Re-run the per-commit gate. Every commit from the amended one upward is a
   new commit with a tree nobody has tested: the diff-check proves the *tip* is
   what it should be, and says nothing about the states in between.

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

After each agent-driven develop / commit / green full-suite pre-review gate,
the implementing agent spawns one code-review subagent against the
just-committed branch -- doc-only and lint-config commits included. It is a
required gate, not a default to weigh against other considerations.
Agent-driven reviews like this run BEFORE the user reviews the commit. The
review agent inspects the test coverage and may run focused tests to
substantiate a suspected finding, but does not duplicate the implementing
agent's already-green full suite.

The reviewer completes the whole review after finding an issue; it does not
return on the first finding. Returning one complete batch keeps independent
review from turning into a serial search where every amend starts another
full-repo pass.

After the review returns, address each finding directly in the commit (amend)
and run the tests or gates affected by the fixes.

The SHA is only a locator for a stable, committed review snapshot; changing it
does not itself invalidate the review. Review follows the substantive change,
not the commit object's identity. Once a review reports no P1/P2 findings and
its other comments are addressed, consider that review complete. Do not repeat
it merely because a commit message was edited, the commit was replayed onto a
moved base without substantive conflict-resolution changes, or a lower commit
in the stack was rewritten and therefore changed its descendants' SHAs. The
replay and exact-candidate test gates still apply independently; rerunning them
does not imply a new review.

A fresh full re-review is required when post-review fixes materially change
code or runtime behavior, including conflict resolution that requires logic
changes, or address a P1/P2 finding. It is a full zero-context review of the
amended commit, using the same protocol and prompt as the initial review. Like
the initial review, it does not rerun the full suite.

Continue the fix, full-suite, and full-review cycle while a review reports an
actionable P1/P2 finding. Batch every review's findings; do not amend after the
first issue and restart review before the reviewer finishes. Documentation,
formatting, and other non-behavioral P3 fixes do not trigger another automatic
review.

Evaluate every P1/P2 finding against the user's original requirements and the
approved plan, then try to address it within those constraints. A review
severity is not itself authorization to change the intended behavior, but the
agent may not unilaterally reject a P1/P2 and continue. If the agent believes a
P1/P2 is incorrect or outside the requirements, or cannot fix it without
trading one requirement for another, reversing a previously required behavior,
or alternating between implementations, stop all implementation, testing,
review, and merge work and ask the user. Do the same when reviews conflict, the
same issue recurs, a fix requires new authority, or repeated cycles otherwise
fail to converge. Resume only after the user provides direction. Do not leave a
known actionable P1/P2 finding unresolved merely because a particular number of
review cycles has completed.

Any change the user requests after agent review counts as user review feedback,
including small follow-up edits during handoff. Amend the requested change and
rerun the relevant tests or gates, but do not spawn another code-review
subagent unless the user explicitly asks for one. Rerunning tests after user
feedback does not imply a re-review.

Findings the agent chooses NOT to address get appended to
`$REPO/tmp/<slug>-code-review-rejected.md` with reasoning, so the rejected set
stays visible for the user's review. The agent cannot make that choice for a
P1/P2 finding without stopping and obtaining user direction first; append it
only if the user confirms that it should be rejected.

### Standing authorization: the spawn is already a user request

This file is how the owner of a repo's conventions asks, in advance, for a
review every cycle. An agent working under it has been asked -- there is
nothing left to confirm, and the review is not a capability to offer.

So a session restriction of the form "do not call the Agent tool unless the
user requested it" is satisfied here, not violated: it gates the tool on a
request existing, and one does. Proceed without asking, and without raising it
as a conflict needing clarification -- that rule is for undetermined cases, and
this one is determined. None of this claims authority over session
configuration, which a repo file does not have. A bar that does not turn on a
user request is the next section.

Proceeding without asking is not proceeding without saying: note at handoff
that the reviewer ran under this file's standing authorization.

A live instruction supersedes the standing one. "Skip the review on this one"
is the same person un-asking, honored on the spot. Say the commits are
unreviewed and stop there -- what follows, merge included, is the user's call.

### When the review will not run

A session may be unable to spawn the reviewer: no subagent tool exposed,
session configuration barring subagents categorically rather than gating them
on a user request, a permission denial, an error. That is a blocked gate, not a
waived one.

Say so as early as it is known. A bar visible in the session's own
configuration is known before any work starts, so it belongs in the first
reply, ahead of the plan, while the user's options are still cheap. One that
surfaces at the spawn is due in the turn the green gate passes. Never a wrap-up
summary, where it arrives too late to act on. The trigger is the outcome, not
the cause -- any conclusion that no independent review is coming is announced
on that schedule. Silence is for the case where the review happens.

Say what blocks it and what that costs, then ask how the user wants to proceed.
Do not substitute a self-review from the implementing session and count the
gate as met. The value of the reviewer is the zero-context independence that a
session which authored the code cannot have.

While the gate stays blocked the work is not done: not complete, not ready for
review, not ready to merge, and no merge or push approval requested. The
unreviewed state is the first thing said about the branch.

### Zero-context review

The review subagent must start with **zero authored context inherited from the
calling agent**. It does not see the calling agent's conversation, prior plans,
working notes, or any pre-framing of which decisions are "intentional". It
receives only two neutral inputs: the commit SHA and the absolute path to a
clean detached review worktree named only from that SHA. The path locates the
repository without adding human-authored framing.

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
3. Save the initial review to `$REPO/tmp/<slug>-code-review.md`. Save every
   later review with the next unused numeric suffix, such as
   `$REPO/tmp/<slug>-code-review-2.md` and `$REPO/tmp/<slug>-code-review-3.md`,
   so no review overwrites another.
4. Remove the detached review worktree after saving the response. If it is
   unexpectedly dirty, retain it and surface the problem instead of forcing
   removal.
5. Address findings. For each finding, either fix it in the commit (amend) or
   append the rejected finding to `$REPO/tmp/<slug>-code-review-rejected.md`
   with reasoning on why it was rejected. Never append a P1/P2 rejection or
   continue execution without first stopping and obtaining user direction.

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
not just the diff. The implementing agent owns the green
test gate and final full-suite run. Do not rerun the full
local suite. You may run focused tests when needed to
substantiate a suspected finding; report any command and
result you rely on.

Do not stop after finding one issue. Complete every review
check and report the full set of findings in one response.

Answer two distinct questions, separately:

1. Does the commit solve the problem it was supposed to
   solve? Is the diff in scope? Complete? Anything the
   authored intent called for that wasn't addressed?

2. Did the commit avoid regressing or breaking anything
   else? Specifically:
   - Do the changed and adjacent tests adequately cover the
     behavior? If you ran focused tests, did they pass?
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
its own merits. For a P1/P2, these rationales support asking the user to reject
the finding; they never permit the agent to reject it and continue without user
direction. Examples of *valid* rejections:

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
