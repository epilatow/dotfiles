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

When locating this procedure, prefer
`.agents/skills/repo-shared-independent-code-review/SKILL.md` in the current
repository. If it is absent and repository policy does not require the
repository-local entrypoint, use
`~/.agents/skills/repo-shared-independent-code-review/SKILL.md`. When policy
requires the repository-local entrypoint, its absence blocks that review gate.
Discovery by name alone does not establish which copy won a client-specific
precedence decision.

## Select the reviewer

Use the currently active agent's built-in child-agent handler when available.
The reviewer must use the same agent/CLI as its parent by default. If the
active environment has no built-in handler, spawn that same agent's CLI
directly using its documented noninteractive/subagent mode. Do not switch to
another CLI unless the user explicitly asks.

The child must start without inherited parent conversation, summaries, plans,
or review notes. Provide only the frozen review prompt with the full target
commit ID and clean review-worktree path substituted. The child loads
repository instructions from that worktree. Do not add a description of the
change or point it to other worktrees or review artifacts. If the child cannot
be observed and safely ended, report the mandatory gate as blocked.

Require all of the following before spawning:

- the candidate is a commit, not uncommitted work;
- the implementer-owned full suite and quality gates are green on that exact
  commit;
- the candidate and tested commit resolve to the same full commit object ID;
- the source checkout is attached to a branch; and
- the current agent can create and later remove its own temporary branch and
  worktree.

## Isolate the candidate

Resolve the selected revision to its full commit object ID; it may be any
commit in the development stack and need not be `HEAD`. Refuse an abbreviated
ID or a candidate that does not match the full tested commit ID. Use the
attached source branch name in the temporary branch:

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
`<REPO>` with the absolute worktree path. Pass no additional message or
inherited authored context.

Use the active environment's normal child-agent supervision. Do not impose a
fixed-duration timeout; distinguish completion, continued work, abnormal exit,
and a stuck run using the repository's supervision rules. Silence alone is not
a reason to cancel.

The reviewer is read-only with respect to tracked files. It may inspect the
whole tracked repository and run focused tests to substantiate a suspected
finding, but it does not repeat the implementer's full suite.

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
acting on findings or later user feedback. A blocked or incomplete review does
not permit completion, handoff, merge, or push.
