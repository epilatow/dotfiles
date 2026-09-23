---
name: repo-shared-rewrite-local-commit-stack
description: >-
  Safely fold, amend, reorder, or replay local feature-branch commits without
  git rebase or merge commits, using a backup branch and verified cherry-picks.
---

# Rewrite a Local Commit Stack

Use this procedure when an existing local feature-branch commit must be
amended, a later local fix must be folded into its owning commit, local commits
must be reordered, or the branch must be replayed onto a moved base.

Repository instructions decide whether rewriting is authorized and which test
and review gates follow it. This skill supplies the task-specific mechanics. It
does not authorize rewriting `main`, another session's branch, or published or
unproved-local commits. For published or uncertain history, stop; proceed only
after explicit user direction defines the rewrite scope.

## Preconditions

Before any history-changing command:

1. Set an explicit absolute working directory for every command.
2. Read the repository instructions and current plan.
3. Record `git status --short`, the full current `HEAD`, the current branch,
   its upstream, and the ordered commits that will be replayed.
4. Confirm the current branch is the intended feature branch and is not `main`
   or the repository's default branch.
5. Check whether the commits were published. With configured remotes, inspect
   the relevant refs and query a remote when tracking refs may be stale; no
   upstream alone proves nothing. With no configured remotes, record that fact
   and inspect available local refs and reflogs for signs of prior publication.
   Proceed if there is no such evidence; do not claim that absent remotes prove
   the commits were never published. Stop for user direction when available
   evidence shows publication or leaves the rewrite scope ambiguous.
6. Account for every tracked and untracked change in the target feature
   worktree. Preserve intended work in a cohesive temporary commit with
   explicitly named paths, or stop. Do not stash, discard, blanket-stage, or
   modify changes in another user or agent's worktree.
7. Identify the exact old tip, target commit or new base, replay order, and
   expected final tree difference before mutating history.
8. Refuse an active rebase, cherry-pick, merge, revert, or bisect; a shallow or
   missing parent; a merge commit in the replay range; or an ambiguous new
   base. Determine whether signing or hooks can prompt before unattended
   reconstruction.

Do not use `git rebase`, `rebase -i`, `--autosquash`, a merge commit, or a
direct cherry-pick onto `main` as a substitute for this procedure.

## Establish a recovery point

Confirm the branch again using the same working directory that will be reset.
Then create a unique local backup branch at the old tip, named
`backup/YYYYMMDD-HHMMSS-<branch-name>`. Resolve and record its full object ID.
Verify the backup points at the old tip before continuing.

The backup is the recovery authority for the rewrite. Do not move, overwrite,
or delete it during the operation.

## Choose one rewrite shape

### Amend a commit and replay its descendants

1. With the worktree clean and the verified backup in place, reset the feature
   branch to the commit that owns the change with
   `git -C "<feature-worktree-path>" reset --hard <target-commit>`.
2. Make the complete scoped edit there and amend that commit. If the change was
   first preserved in a temporary tip commit, apply only that temporary
   commit's intended delta with
   `git cherry-pick --no-commit <temporary-commit>`, then amend it into the
   owner.
3. Read the amended commit in full and verify that no descendant functionality
   leaked into it.
4. Cherry-pick each original descendant from the backup branch in its original
   order, excluding any temporary fix commit already folded. Use the recorded
   full object IDs, not a revision range resolved after reset.

### Reorder or fold existing commits

1. With the worktree clean and the verified backup in place, reset to the
   parent of the first commit whose order or contents will change with
   `git -C "<feature-worktree-path>" reset --hard <first-parent>`.
2. Cherry-pick the desired commits from the backup in their intended order,
   using the recorded full object IDs rather than a revision range.
3. To fold one commit into another, cherry-pick the owning commit, apply the
   folded commit with `git cherry-pick --no-commit <folded-commit>`, and amend
   the owner.
4. Verify each resulting commit remains complete, independently understandable,
   and free of changes owned by its descendants.

### Replay onto a moved base

1. Resolve and record the exact new base commit.
2. With the worktree clean and the verified backup in place, reset the feature
   branch with `git -C "<feature-worktree-path>" reset --hard <new-base>`.
3. Cherry-pick only the recorded full object IDs for the feature branch's
   commits from the backup, oldest first.
4. Resolve conflicts as semantic edits against the new base. Never take one
   side wholesale without checking the full affected file and callers.

## Conflict and interruption recovery

At a cherry-pick conflict, inspect the current status and every conflicted
file, resolve only the intended combined behavior, stage explicit paths, and
continue the cherry-pick. If the correct result is uncertain, abort the current
cherry-pick and stop with the backup intact; do not improvise through the rest
of the stack.

If a cherry-pick becomes empty, stop and account for it. Determine whether the
new base already contains the change, an earlier replay duplicated it, or the
conflict resolution removed it. Do not skip or commit the empty result until
that accounting is explicit.

If a command targets the wrong branch, stop further rewrite mutations and
inspect the affected worktree, branch, `HEAD`, status, reflog, backup name, and
active cherry-pick state using explicit absolute paths. When the exact prior
state is provable and restoring it will not overwrite worktree changes, restore
the affected branch with an explicit command such as
`git -C "<affected-worktree-path>" reset --hard <recorded-prior-commit>`,
verify the restoration, and resume the intended rewrite. If the prior state is
ambiguous or recovery risks data loss, preserve the current state and obtain
user direction. Never delete files or reset to an inferred commit merely to
make the state look clean.

## Prove the result

After the replay:

1. Compare the new tip with the backup tip using `git diff <backup-branch>`.
   For a pure reorder or fold, it must be empty. For an intentional content
   edit, it must show exactly that edit. For a moved-base replay, it must show
   exactly the new base's effect plus reviewed conflict resolutions.
2. Compare the recorded old and new commit sequences. For a moved-base replay,
   run `git range-diff <old-base>..<backup-branch> <new-base>..HEAD`; use the
   analogous unchanged-base range for other rewrites when it clarifies folds or
   reorders. Account explicitly for every old commit and every new commit: a
   matching tip tree alone can hide a dropped, duplicated, or emptied commit.
3. Inspect the rewritten log and every rewritten commit. Confirm commit
   messages, attribution trailers, scope, and parent order.
4. Reconfirm the feature branch name and a clean working tree.
5. Assuming every backup commit had passed its applicable gates, run the gates
   relevant to each changed, amended, or conflict-resolved commit as it is
   reconstructed, before replaying its descendants. Run the relevant gates on
   the completed tip, unless its tree and gate commands match an already-green
   exact candidate. Markdown-only changes need the Markdown/formatting gates;
   changes to repo code or tests need their applicable repo gates. Do not rerun
   gates for unchanged commits merely because their object IDs changed. If a
   failure was not introduced by the commit under test, use a binary chop to
   find the commit that introduced it.
6. Apply the repository's independent-review rules.

Keep the backup branch until the user has accepted the rewritten stack or the
repository's cleanup policy explicitly permits removal. Report the backup name,
old and new tip IDs, comparison result, and gate results at handoff.
