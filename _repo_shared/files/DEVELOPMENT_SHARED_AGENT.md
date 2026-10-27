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
- **Audit every committed change before its post-change tests.** Identify the
  exact commit, not staged, unstaged, or untracked work. While authored context
  remains available, follow the repository-local
  `.agents/skills/repo-shared-audit-committed-change/SKILL.md`. Fix findings in
  the owning commit and rerun the audit before testing. This implementer-owned
  audit does not replace independent review.
- **A green implementer-owned gate precedes review.** After the
  authored-context audit, run repo-shared and focused checks relevant to the
  committed change, following [Testing](DEVELOPMENT_SHARED.md#testing). Use the
  repository-local `.agents/skills/repo-shared-run-commit-gates/SKILL.md` for
  that exact commit. Do not give a reviewer a commit with red applicable gates.
- **Gate each new commit, not just the tip.** Run shared and focused checks on
  every new commit in a stack with no later commits present. For a rewrite,
  follow the rewrite skill.
- **An independent code review precedes handoff.** Once the gates are green,
  the implementing agent spawns the reviewer itself, unasked. An unreviewed
  branch is not ready to hand off as finished. See [Code review](#code-review).
- **A green landing gate precedes every merge.** Run the full suite on the
  settled candidate before landing, following
  [Testing](DEVELOPMENT_SHARED.md#testing), and record which commits the
  evidence covers. Merge approval waives no gate. Never merge first and test
  afterward.
- **Status reports follow the skill.** When the user asks for a development
  status report (short requests like "Status?" or "Status update?" count when
  development work is active), follow the repository-local
  `.agents/skills/repo-shared-development-status-report/SKILL.md` for format
  and state fields. Do not initiate reports or set a cadence without a request.
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

## Library and module usage

Use only public/exported interfaces that the library or module supports for
consumer use. Do not call or rely on internal interfaces or implementation
details. An interface being accessible does not mean it is public or supported.

Exceptions are rare and must be explicitly confirmed with the user before using
an internal interface. Explain why the exception is necessary and why supported
public interfaces cannot meet the requirement. For each approved exception, add
a code comment at the point of use identifying the internal interface and
explaining why relying on it is necessary.

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

## One command per invocation

Run one command per invocation and read its result before issuing the next.
`&&`, `||`, `;`, and newlines each make several; a `|` pipeline is one. The
exceptions are things that break when split: a `cd` and the command that needs
it, or a capture like `setsid <tool> ... & SPAWN_PID=$!`.

Batching is not dangerous because chains fail. It is dangerous because they
succeed: a destructive command sent alongside four routine ones has already run
by the time its block of output is read, and the line that should have stopped
you is indistinguishable from the expected ones.

## Run commands to completion

Never pipe a command through a filter to watch or trim it -- `tail`, `head`,
`grep`, `tee`, anything of shape `<command> | <filter>`. The pipeline's exit
status is the filter's, not the command's, so a failed run reports 0, and
`head` closes the pipe once it has its lines, so the command is cut short as
well as misreported -- a truncated test suite reads as a green one. Run the
command on its own and read its exit code. When the output is too long,
redirect it to a file under `$REPO/tmp/` or the session's scratch directory and
read that file; `tail` on a file the command has finished writing is fine, as
is a tool's own limit flag (`git log -20`) in place of a filter.

## Other agents share this repo and machine

Assume other agents, and the user, are working in this repo and on this machine
at the same time. Their branches, worktrees, scratch files, and processes look
like leftovers from inside your session, and are not. Never delete or rewrite a
branch, worktree, or untracked file you did not create (see
[Delete from a list, never from a pattern]), and never kill a process that is
not yours (see [Process management](#process-management)). When something that
looks abandoned is in your way, ask.

## Delete from a list, never from a pattern

Never delete by glob, pattern, or sweep -- `rm -rf .wt/*`, `find tmp -delete`,
`git clean -fdx`, `git stash clear`, any pipeline of shape
`<pattern-query> | <delete>`. Each takes whatever is there when it runs,
including what another agent put there since you last looked. Build the list of
targets first (`ls`, `git branch --list`, `git worktree list`), read it, and
delete exactly those entries by name.

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

## Update relevant docs

A change that affects what a doc tells its reader updates that doc in the same
commit. Docs are part of the change, not a follow-up.

A change has documentation impact when it:

- makes an existing doc claim false -- a renamed or removed command, flag,
  knob, path, or required step; or
- adds a command, flag, knob, convention, or required step that a doc's reader
  needs and cannot get from `--help` or an error message.

An implementation detail is not documentation impact. Code changing is not a
reason to add doc text. Document each fact once, in the doc whose reader needs
it, and link to it elsewhere rather than restating it (see
[Keep implementation details at the implementation](DEVELOPMENT_SHARED.md#keep-implementation-details-at-the-implementation)).
`DEVELOPMENT_SHARED.md` and `DEVELOPMENT_SHARED_AGENT.md` hold cross-repo
conventions, not the behavior of one repo's tools. Deleting doc text the change
made obsolete is part of the update.

To find the impact, grep the docs for each name the diff removes or whose
meaning or behavior it changes, and fix what is now wrong.

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
committed-change audit) calls out a stale list, classification, table, or
convention adjacent to your change, do the full work to leave it correct --
including restoring quality of pre-existing entries the change touches. If
genuinely out-of-blast-radius cleanup is needed elsewhere, surface it as a
separate suggested follow-up; don't use it to excuse skipping the in-scope
work.

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
`$REPO/.wt/<branch>`. Do not invent a separate worktree-purpose name. The
skills' temporary gate and code-review branches follow the same rule. Be sure
that .gitignore contains .wt/. Once the user has approved the merge and the
work has landed on `main`, remove the worktree and any branches you created as
part of the development effort.

**Set the working directory at the start of every command or block of
commands** -- `cd <abs-path> && <command>`, or `git -C <abs-path>` per command.
Never assume it: a block that sets nothing inherits a directory you did not
choose, and `reset --hard` in the wrong one rewrites the wrong branch.

- **Confirm the target before any command that rewrites a branch.** Before
  `reset --hard`, `commit --amend`, or `cherry-pick`, run
  `git -C <path> rev-parse --abbrev-ref HEAD` against the same `<path>` the
  next command will use, as its own invocation, and read it.
- **Remove a worktree from outside it**, or the directory disappears from under
  the command doing the removing.

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

### Local commit-stack rewrites

Fold changes into the local, unpushed commit that introduced the affected code;
ask before using a follow-on commit. Never use `git rebase`, create a merge
commit, or cherry-pick feature commits directly onto `main`.

Before changing history, verify the exact feature worktree and branch; never
rewrite `main` or another session's branch. Prove the commits are local or
obtain user direction. Read and follow the exact repository-local
`.agents/skills/repo-shared-rewrite-local-commit-stack/SKILL.md` for the
backup, replay, recovery, and verification procedure. If it is missing or its
preconditions fail, stop before changing history. A moved-base replay may
fast-forward to `main` only after separate merge authorization.

### Renames

When renaming and updating renamed files in git, do it in two commits. The
first commit contains only renames (so git history tracking works across the
rename). The second commit contains the actual file updates.

## Commit-message hygiene

Before creating or amending a commit, read and follow the exact
repository-local `.agents/skills/repo-shared-write-commit-message/SKILL.md` and
validate the message against the change. Apply more-specific repository rules.
If the skill is missing, stop before committing or amending.

## Comment-message hygiene

`DEVELOPMENT_SHARED.md`'s "Comments" subsection is the canonical rule: a
comment describes the current code, never what was there before. The
agent-specific failure mode is repeating the commit-message rationale inside
the source.

Concretely, never write comments like:

- `# The legacy _FooBar shim is gone -- now uses helpers.foo.`
- `# Wrappers have all been deleted; the dispatcher derives this directly.`
- `# This used to live in module_x.py; lifted to shared.py in the cleanup.`
- `# Replaced the per-call-site try / except with the shared guard.`
- `# Per the plan, this lives in helpers_runtime instead of helpers_lifecycle.`

The same applies to docstrings ("formerly known as `_FooBar`", "ported from the
legacy framework"), CHANGELOG-style banners at the top of files, and
`# TODO: remove once X` markers that name something already removed. If a
comment's content reads like a footnote on the diff, it belongs in the commit
message, not the file; if it cannot be written without naming something that no
longer exists, delete it.

Example lists in these guides, including the "do NOT include" list under
"Commit messages" in `DEVELOPMENT_SHARED.md`, are illustrative, not exhaustive:
a similar pattern that is not listed still falls under the rule.

## Supervising a subagent

This covers every subagent you spawn -- a reviewer, a research or
implementation job, another model driven through its own CLI -- whether or not
anyone is watching the parent.

- **Hold a way to watch it and a way to end it.** Record a cancellation handle,
  or the PID and process group of an external process, at spawn time. A
  subagent that cannot be both watched and stopped does not get started; report
  its gate as blocked. A `running` status is not completion.
- **No timeouts; check at least every five minutes.** How long a subagent takes
  is not predictable, so a deadline ends healthy work. Never spawn it through a
  call that blocks the parent: a blocked parent has no turn in which to check.
  A wedged one never signals completion, so drive the check from a scheduled
  wake-up or a watchdog holding the handle, never from an intention to check
  back.
- **Silence is not a hang.** Stuck means evidence from the subagent itself --
  output that stopped growing, a transcript on the same tool call, an idle
  process -- holding across more than one check. Where a subagent reports
  progress, mention a stall before acting on it. If nothing at all can be
  observed across several checks, ask the user instead of ending it or waiting
  silently.
- **End only a stuck subagent, through its recorded handle.** Whether it died
  or you ended it, leave its worktree for inspection and promptly report the
  gate it held as blocked; see
  [When the review will not run](#when-the-review-will-not-run).
- **A noninteractive parent does not launch a child that can stop for
  interaction** unless the parent will answer it. Otherwise, before unattended
  work begins, configure every expected action to resolve to `allow` or `deny`,
  with no more authority than the task needs; a prompt cannot answer a runtime
  permission request. If neither can be guaranteed, report the gate as blocked
  instead.

## Code review

After its audit and a green pre-review gate, every agent-authored commit gets
one independent review of that exact commit, doc-only and lint-config commits
included, before user review and handoff. Complete the review before acting on
its findings. Before deciding how to handle a finding, whether an amendment
needs re-review, or how to handle later user feedback, read the skill's
`references/finding-disposition.md`.

### Standing authorization

This repository's requirement for an independent review is the owner's standing
request to spawn a reviewer; do not ask again merely because a tool requires a
user request. It does not override a categorical session bar. Note at handoff
that the review ran under this standing authorization.

A live request to skip review overrides it. Say the commits are unreviewed and
stop; further work, including merge, is the user's call.

### When the review will not run

A categorical session bar, permission denial, invocation error, or inability to
observe and stop the child blocks the review gate; it does not waive it. Report
a known bar in the first reply, before planning. If it arises later, report it
in the turn the green pre-review gate passes, not at handoff. Explain the
consequence and ask the user how to proceed.

Do not substitute the implementing session's committed-change audit. While
blocked, the work is unreviewed and not ready for completion, handoff, merge,
or push. Lead with that status when reporting the branch.

### Skill-owned review procedure

Before implementation begins on work requiring this gate, read and follow the
exact repository-local
`.agents/skills/repo-shared-independent-code-review/SKILL.md`. Discovery by
name alone does not prove the repository copy was loaded. The skill owns
isolation, same-agent reviewer selection, report capture, cleanup, and
post-review finding disposition; supervision follows
[Supervising a subagent](#supervising-a-subagent). If the exact skill is
missing or a safe child cannot run, apply
[When the review will not run](#when-the-review-will-not-run).

[delete from a list, never from a pattern]: #delete-from-a-list-never-from-a-pattern
