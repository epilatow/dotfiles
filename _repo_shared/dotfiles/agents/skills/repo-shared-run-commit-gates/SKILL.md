---
name: repo-shared-run-commit-gates
description: >-
  Run formatting, lint, type, and full-suite gates against one exact committed
  change in a named temporary branch and worktree, with observable logs and
  safe cleanup.
---

# Run Gates on One Commit

Use this procedure for one exact commit whenever repository policy requires its
quality and full-suite gates. This skill does not select or walk a commit
stack; invoke it separately for each commit that must be gated.

## Identify the exact candidate

1. Read the repository instructions and discover its authoritative format,
   lint, type-check, and full-suite commands. Do not replace a repository gate
   with a convenient subset.
2. From the implementation worktree, record the attached source branch and
   resolve the selected candidate to its full commit object ID. The candidate
   may be `HEAD` or another explicitly selected commit, but do not accept an
   abbreviated ID or uncommitted changes as part of the candidate.
3. Require the implementation worktree to be clean and its `HEAD` to equal the
   selected commit before running prechecks. If an older stack commit needs
   this gate, invoke the skill while reconstructing or otherwise safely
   checking out that exact commit on an attached implementation branch; do not
   detach or move the source branch merely to make the precondition appear
   satisfied.

## Fix cheap quality failures first

Before creating any gate branch or worktree, run every applicable formatting,
lint, and type-check gate in the clean implementation worktree. Run independent
prechecks concurrently when the host can keep each result observable.

If any precheck fails, do not create the gate branch and do not start the full
suite. Fix every reported formatting, lint, and type error in the
implementation worktree, commit or amend the complete fix into its owning
commit, run the repository's required committed-change audit, and repeat all
applicable prechecks against the new full commit ID. Continue only when every
precheck is green. A formatter that merely changed files has not passed until
those changes are committed and the check-form command succeeds.

## Create exact isolated state

Use the local timestamp, source branch name, and the repository's customary
short object-ID length to form this temporary branch:

```text
gates/YYYYMMDD-HHMMSS-<source-branch>-<short-SHA>
```

Its attached worktree must be:

```text
<main-checkout>/.wt/<temporary-branch>
```

Verify the proposed branch with `git check-ref-format --branch`. Refuse an
existing branch, worktree path, symlinked path component, or ownership
ambiguity. Create the new branch at the recorded full object ID with
`git worktree add -b`, then verify that the worktree is clean, its symbolic
branch is the exact temporary branch, and both `HEAD` and the branch ref equal
the exact candidate. Never move the branch during the gate.

## Run and supervise the full suite

Run the repository's complete full-suite command from the gate worktree. Use
the host's observable long-running-process facility and write complete stdout
and stderr logs beneath `<main-checkout>/tmp/<temporary-branch>/`; retain an
observation handle and a cancellation handle. Do not rely on an in-memory
transcript or a blocking invocation that prevents supervision.

Monitor the process and its logs until it exits. As soon as a definite failure
appears in the logs, begin read-only failure analysis from the available output
when not actively working on another task; do not sit idle merely because other
tests are still running. Continue supervising the suite, preserve later
failures, and wait for its final exit status. Early analysis does not authorize
editing the gate worktree or reporting a result before the complete suite
finishes.

Record the exact commit, commands, exit statuses, and log paths. A signal,
timeout, lost process handle, truncated log, or incomplete result is not a
passing gate.

## Clean up safely

Before cleanup, verify the gate worktree is owned by this run, clean, on the
exact temporary branch, and still at the candidate commit. Remove the worktree
from outside it. Then delete the temporary branch itself, but only if it still
points at the candidate. Use an atomic compare-and-delete so a branch that
moved after validation is retained rather than removed, for example:

```text
git -C "<main-checkout>" update-ref -d \
  "refs/heads/<temporary-branch>" "<full-commit-id>"
```

If the worktree is dirty, the branch moved, ownership is unclear, or the
process may still be alive, retain the resources and report their exact state
instead of forcing cleanup. Gate failure does not by itself require retaining a
verified clean worktree; preserve the logs and remove only the resources whose
ownership and state are proven.

Return one result for this exact commit: pass only when every applicable
precheck and the complete full suite succeeded. Otherwise report failure or a
blocked gate with the evidence needed to continue diagnosis.
