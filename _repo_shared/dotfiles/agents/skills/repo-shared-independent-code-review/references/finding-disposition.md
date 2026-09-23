# Review findings and re-review

Read this after the reviewer returns, before acting on its findings, and again
when deciding whether an amendment needs another review. Complete the whole
review before changing the commit; do not turn findings into a serial search.

## Resolve findings

Address each finding in the commit that owns the change and rerun the tests or
gates affected by the fix. A P1/P2 finding cannot be unilaterally rejected.
Evaluate it against the user's requirements and approved plan, then try to
resolve it within those constraints. If it appears incorrect or out of scope,
or fixing it would trade away a requirement or reverse required behavior, stop
implementation, testing, review, and merge work and ask the user. Do the same
if reviews conflict, an issue recurs, a fix needs new authority, or review
cycles fail to converge. Do not leave a known actionable P1/P2 unresolved
merely because several cycles have completed.

A P1/P2 finding indicates a gap in the preceding analysis. Before fixing the
named case, inspect adjacent paths, other instances, and implied edge cases;
address the complete gap in the same amend. A local P3 finding should also be
fixed; its severity says whether it blocks shipping, not whether the work is
worth doing.

Append any finding deliberately not addressed to
`<main-checkout>/tmp/<slug>-code-review-rejected.md`, with reasoning. For
P1/P2, do so only after the user confirms the rejection. A defensible rejection
can concern a genuinely unrelated surface, a fix that would reintroduce an
earlier regression, or a cosmetic change that would enlarge the diff for
negligible value. Pre-existing staleness on a touched surface, the P3 label, or
calling an in-scope fix "defensive" is not a defensible rejection. If work
genuinely belongs in a separate follow-up, propose its scope to the user rather
than rejecting it on the user's behalf.

## Decide whether to re-review

Decide per fix, not per finding severity, commit, or stack. Re-review the
amended commit when the fix changes behavior enough that the completed review
no longer covers it: a reworked or added code path, a changed caller/user
contract, or a substantial diff. Use a fresh full zero-context review through
this skill; the reviewer does not rerun the implementer's full suite.

Otherwise, amend and rerun the affected tests or gates without another review,
even for a P1/P2. Examples include commit-message, documentation, docstring,
comment, formatting, and lint fixes; added or tightened tests; and trivial
logic corrections a reader can verify from the amend alone. Judge a relaxed or
removed test by the behavior it lets through. A moved-base replay is judged by
its conflict resolution, not by the fact of replay. A changed SHA alone never
triggers re-review, including descendant SHAs after an ancestor amendment. When
a fix is marginal, rely on the completed review and affected test gates rather
than starting another full review cycle.

Batch each review's findings. Continue review cycles only when a round of fixes
includes a substantive change requiring re-review. A review is complete once
every finding is fixed or rejected with the required authority. Gate the
settled candidate under the repository's testing rules before merge.

## Later user feedback

Any change the user requests after agent review, including a small handoff
edit, is user review feedback. Amend it and rerun the relevant tests or gates,
but do not spawn another code-review subagent unless the user explicitly asks.
Rerunning tests after user feedback does not imply re-review.
