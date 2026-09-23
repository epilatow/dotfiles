---
name: repo-shared-development-status-report
description: >-
  Format user-requested development status reports for active efforts and
  unmerged commit stacks, including short requests like "Status report?".
---

# Development Status Reports

Use this format only when the user requests a development status report or
explicitly requests periodic development status reports. Do not initiate
reports or choose a reporting cadence without that request. Repeat the effort
block for each active effort. Never use a generic "parallel work" heading. Stop
reporting an effort once it is complete.

A short request such as "Status report?" counts as a request when development
work is active.

```text
Status \u2014 YYYY-MM-DD HH:MM TZ

<effort-summary> \u2014 <worktree-path>

<commit-number>: <latest-hash>: <brief-commit-name> \u2014 <done|WIP>; <N reviews>; [reviewing|review-pending]; [gating|gate-pending]; [updating|updates-pending];
  [amends <commit-number>];

<activity summary>
```

Render each U+2014 escape in the template as an em dash in the report. The
bracketed fields are optional alternatives, not literal brackets. Omit an
inapplicable field and its separator. Timestamp every periodic report with the
local date, time, and time zone. Summarize recent activity and remaining work
after each effort's commit list.

## Efforts and commits

- Give each effort a short, specific name and its current development worktree
  path. List every unmerged commit in stack order, including unchanged and
  completed commits. Stop listing a commit when it merges or is folded into
  another commit.
- Assign numbers starting at 1 when commits first enter an effort. Keep each
  number as a stable identity when its hash changes. Do not renumber surviving
  commits merely because a lower part of the stack merged onto `main`; the
  remaining numbers may start above 1 or have gaps.
- Renumber commits when the stack is restacked or reordered, or when an
  amendment commit disappears after being folded into another commit.
- Show each commit's latest hash and a brief name that identifies it even if
  its number or hash changes.
- Mark an amendment commit with `amends <commit-number>`, referring to the
  commit it will be folded into before landing.

## State fields

- Use `done` when development work on a commit is complete and no further
  development review or gate is needed. Otherwise use `WIP` for outstanding
  reviews, gates, or amendments. A replay verification gate is the exception
  described below.
- Report all completed reviews as one count, `N reviews`. Include prior reviews
  and re-reviews in that count without distinguishing them.
- Use at most one of `reviewing` and `review-pending`, at most one of `gating`
  and `gate-pending`, and at most one of `updating` and `updates-pending`.
  Running work uses the present-participle form; queued or needed work uses the
  pending form. Omit a pair when neither state applies.
- A `WIP` commit with `0 reviews` must include `review-pending` while its first
  review is queued, or `reviewing` while that review runs. A completed
  amendment that needs no independent review is exempt. A pure file rename
  commit is exempt only when the applicable workflow requires no independent
  review; otherwise show its pending or running review.
- Evaluate every flag against the current branch, regardless of the state of
  `main`. A change to `main` alone does not change a commit's flags. After a
  replay, a previously `done` commit remains `done` and may acquire
  `gate-pending` for verification on the replayed branch. Substantial conflicts
  can return it to `WIP` with reviews or updates pending as appropriate.
