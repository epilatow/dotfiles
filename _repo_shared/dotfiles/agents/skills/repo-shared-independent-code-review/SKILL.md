---
name: repo-shared-independent-code-review
description: >-
  Run a zero-authored-context review of a committed change after its green
  pre-review test gate, using the active agent and an isolated worktree.
---

# Independent Code Review

Run the repository's independent review gate without passing the implementing
conversation, plans, prior reviews, or explanations of intended decisions to
the reviewer. Repository instructions decide when this gate is mandatory and
whether spawning is authorized; this skill supplies the task-specific
procedure.

## Select the reviewer

Use the currently active agent's built-in child-agent handler when available.
The reviewer must use the same agent/CLI as its parent by default. If the
active environment has no built-in handler, spawn that same agent's CLI
directly using its documented noninteractive/subagent mode. Do not switch to
another CLI unless the user explicitly asks.

Require all of the following before spawning:

- the candidate is a commit, not uncommitted work;
- the implementer-owned shared and focused checks are green on that exact
  commit;
- the candidate and tested commit resolve to the same full commit object ID;
- the source checkout is attached to a branch; and
- the current agent can create and later remove its own temporary branch and
  worktree.

## Isolate the candidate

Resolve the selected revision to its full commit object ID; it may be any
commit in the development stack and need not be `HEAD`. Refuse an abbreviated
ID or a candidate that does not match the commit validated by the shared and
focused checks. Use the attached source branch name in the temporary branch:

```text
code-review/YYYYMMDD-HHMMSS-<source-branch>-<short-SHA>
```

The attached worktree directory mirrors the temporary branch name:

```text
<main-checkout>/.wt/code-review/YYYYMMDD-HHMMSS-<source-branch>-<short-SHA>
```

Verify the branch name with `git check-ref-format --branch`. Refuse an existing
branch or path, symlinked path component, or ownership ambiguity. Create an
attached worktree at the exact commit with
`git worktree add -b <temporary-branch> <worktree-path> <full-object-id>`.
Before spawning, verify the worktree is clean, its symbolic branch is the exact
temporary branch, and its `HEAD` and branch ref both equal the target commit.

The reviewer may receive its system prompt, tool schemas, environment metadata,
and repository instructions loaded from the review worktree. It must not
receive parent conversation turns or summaries, parent-loaded skills, the
parent worktree's state, plans, earlier reviews, rejected findings, or any
purpose label beyond the mechanically derived source-branch component.

## Run and supervise the reviewer

Read the [frozen review prompt](references/review-prompt.md). Send the fenced
`text` block exactly, replacing only `<SHA>` with the full object ID and
`<REPO>` with the absolute worktree path, and send nothing else. Supervise the
reviewer under "Supervising a subagent" in `DEVELOPMENT_SHARED_AGENT.md`.

The reviewer is read-only with respect to tracked files. It may inspect the
whole tracked repository and run focused tests.

## Capture and cleanup

Save the complete response under the main checkout's `tmp/` as
`<slug>-code-review.md`. Never overwrite an existing report; choose the next
unused numeric suffix, such as `<slug>-code-review-2.md`. A partial response,
abnormal exit, or cancelled run is not a completed review.

After the complete response is saved, verify the worktree remains clean,
attached to the exact temporary branch, and at the reviewed commit. Remove it
from outside the worktree with `git worktree remove <worktree-path>`. Then
delete the temporary branch only if it still points to the reviewed commit,
using an atomic compare-and-delete such as:

```text
git update-ref -d refs/heads/<temporary-branch> <full-object-id>
```

If the child fails or ownership is unclear, preserve the worktree and branch
for inspection. Do not force cleanup or adopt resources that this run did not
create.

After the reviewer returns, read and follow
[finding disposition and re-review](references/finding-disposition.md) before
acting on findings or later user feedback.
