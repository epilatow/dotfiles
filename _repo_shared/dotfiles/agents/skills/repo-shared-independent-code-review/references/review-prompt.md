# Review Prompt

Send the contents of this `text` block verbatim, replacing only `<SHA>` and
`<REPO>`.

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
- Repo path: <REPO>, a clean review worktree on a temporary
  branch at the exact commit.

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
