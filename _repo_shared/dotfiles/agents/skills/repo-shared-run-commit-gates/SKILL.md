---
name: repo-shared-run-commit-gates
description: >-
  Run shared and focused development checks, or final full-suite landing gates,
  against an exact committed change with observable logs and safe cleanup.
---

# Run Gates on One Commit

Use this procedure for one exact commit. Follow DEVELOPMENT_SHARED.md's Testing
policy for scope, result reuse, and isolated failures. This skill does not
select or walk a commit stack.

## Choose the gate stage

- **Development / pre-review:** run the repo-shared tests and focused checks
  selected from the changed code, callers, and shared dependencies. Include
  applicable formatting, lint, type, platform, and end-to-end checks. Do not
  run the full suite or unrelated utilities' tests during each iteration.
- **Landing:** after the change and review fixes are settled, run the normal
  full suite once before landing. Keep default GUI and integration gating; opt
  into additional suites only when relevant or explicitly requested.

Record the selected stage, commands, and scope rationale. Retain applicable
passing results; after narrow amendments rerun affected checks, not the whole
suite solely because the commit hash changed.

## Identify the exact candidate

1. Read the repository instructions and discover its authoritative format,
   lint, type-check, shared, focused, and full-suite commands. Development
   scope must cover the change; landing still requires the normal full run.
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

Run shared and focused checks, including applicable formatting, lint, and type
checks, in the clean implementation worktree. Run independent checks
concurrently when the host can keep each result observable.

If a check is non-green after applying the isolated-failure policy below, do
not start the landing full suite. Fix every reported formatting, lint, and type
error in the implementation worktree, commit or amend the complete fix into its
owning commit, run the repository's required committed-change audit, and repeat
all affected checks against the new full commit ID. Continue only when every
required check is green. A formatter that merely changed files has not passed
until those changes are committed and the check-form command succeeds.

## Create exact isolated state

For the landing full run, create the isolated state below. Scoped checks do not
require a new full-suite gate worktree.

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

At the landing stage, run the repository's normal full-suite command from the
gate worktree. Use the host's observable long-running-process facility and
write complete stdout and stderr logs beneath
`<main-checkout>/tmp/<temporary-branch>/`; retain an observation handle and a
cancellation handle. Do not rely on an in-memory transcript or a blocking
invocation that prevents supervision.

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

## Handle an isolated failure

Do not restart the full suite for a single failed test. After the run finishes,
rerun only that test on the same candidate with equivalent settings and
conditions. Apply DEVELOPMENT_SHARED.md's "Isolated test failures" policy.

A passing rerun requires causal analysis, not automatic acceptance. Inspect
changed paths and transitive effects, fixtures, dependencies, environment,
timing, and differences between the original run and rerun. If all other
required checks completed successfully and no plausible introduced regression
remains, flag and document the flake and mark the gate green. Preserve the
original command's non-zero exit status and the rerun evidence. Do not require
another full run merely to obtain a zero exit status.

If the failure persists or a plausible regression remains, keep the gate
non-green and root cause it. Fix and retest the affected scope; repeat the full
suite only when the cause or fix invalidates broader coverage.

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

Return one result for the chosen stage and exact candidate, identifying any
reused results. Development is green when shared and focused checks are green.
Landing is green when required scoped checks and the completed full run are
green, including a documented isolated non-regression flake that qualifies
under the policy above. Otherwise report failure or a blocked gate with the
evidence needed to continue diagnosis.
