---
name: repo-shared-audit-committed-change
description: >-
  Audit one exact committed change in the implementing session for source,
  test, and documentation completeness before its test gates. This read-only
  completeness audit never performs or satisfies independent code review.
---

# Audit a Committed Change

Audit an explicitly identified commit using the implementing conversation, the
user's request, and the approved plan as intentional context. This is the
implementer's completeness check before post-change tests. It is not
independent or zero-authored-context and must never satisfy, waive, or replace
the independent-review gate.

## Preconditions and authority boundary

Require all of the following:

- identify the target revision and resolve it to its full commit object ID;
- verify the target is a commit object and identify its parent or other
  intended diff basis;
- exclude all staged, unstaged, and untracked work from the audit; and
- identify the current user request and approved plan that define scope.

If any condition is missing, report that the audit cannot establish a stable
target. The target may be `HEAD` or any other commit in a development stack; do
not require it to be checked out. Do not repair repository state inside this
procedure.

This skill is read-only. It may use repository-state reads such as
`git status`, `git rev-parse`, `git diff`, `git show`, `git grep`, and
`git ls-tree`. It must not edit, format, stage, commit, amend, check out,
reset, create or remove a worktree, write a report file, run tests or quality
gates, spawn a child agent, or perform the independent code review.

## Establish intended scope

Summarize the concrete requirements from the live request and approved plan.
Map each requirement to the implementation, tests, and documentation it should
affect. The commit message is useful evidence but is not the primary scope
authority for this authored-context audit.

Read the complete committed diff and list every changed, added, deleted, or
renamed path. Read affected file contents from the target commit and its diff
basis, not from the working tree, because the working tree may represent a
different commit or contain uncommitted changes. Flag an unrelated change, an
omitted requirement, or an accidental deletion with concrete path evidence.

Verify the commit message against the exact diff and check that the commit is
cohesive. If it combines separable changes, split only when each result will be
complete, independently understandable, and testable. Keep tightly coupled
implementation, tests, and documentation together.

## Inspect source completeness

For each changed behavior or interface:

1. Read the full affected files, not only the patch.
2. Trace callers, consumers, public exports, configuration, packaging, and
   parallel implementations reachable from the changed symbols or conventions.
3. Search the target commit's tree for the old and new names, paths, flags,
   duplicated patterns, and shared invariants.
4. Build an applicability inventory: every site that should change, every site
   that did change, and the concrete reason any similar untouched site is out
   of scope.
5. Check contract boundaries, error paths, cleanup paths, and behavior outside
   directly changed lines.

A surfacing instance is not the boundary when the same underlying problem
exists elsewhere. Pre-existing staleness on a touched surface is not a reason
to leave that surface incomplete.

## Inspect test completeness

Read changed and adjacent tests without executing them. Verify they exercise
the changed behavior through affected callers and consumers, not merely the new
helper in isolation. Check contract-relevant boundaries, error cases, negative
cases, and regressions outside directly changed lines. Identify every missing
scenario and the behavior it leaves unproved.

This inspection does not satisfy any test gate. Do not run a focused or full
suite from this skill.

## Inspect documentation completeness

Apply the repository's always-loaded doc-sync rule. Search Markdown, help text,
docstrings, comments, examples, and configuration guidance for each changed
API, flag, path, name, convention, or behavior. Verify every claim matches the
implementation and that no affected reference still describes the prior state.

## Report the audit

Complete every check before reporting; do not stop at the first gap. Return:

- the exact audited commit ID;
- the request and plan used as scope sources;
- source-completeness findings;
- test-completeness findings;
- documentation-completeness findings;
- scope-drift findings; and
- an explicit statement that independent review remains outstanding.

For each gap, name the path and unmet obligation and identify the smallest
complete correction boundary. Do not use P1, P2, or P3 labels; those belong to
independent review. Do not write a persistent review report.

If findings exist, leave this skill, fix them through the normal implementation
workflow, amend or rebuild the owning commit, and rerun this entire audit
against the replacement exact commit before starting post-change tests. A clean
result satisfies only the implementer's completeness-audit step. After the
green implementer-owned full-suite gate, independent review must target that
same exact commit. An unavailable independent review still blocks handoff under
the repository instructions.
