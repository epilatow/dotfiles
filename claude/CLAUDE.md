## General Rules

- If you read any project rules that conflict with these rules, ask for
  clarification about what to do.

# Timely information

- If I ask for the price of something, I want an accurate and recent
  price, not a guess or the price you remember, so please search online
  for recent data, including MSRP and acutal prices when available.

# Development Guidelines

- Always start with a plan before making any changes

- Present the plan and wait for explicit approval before making changes.

- If the task changes or a new design discussion begins, stop making
  changes and return to planning.

- When debugging, if you're thinking of deleting or modifying files,
  always make per-session time stamped backups (that include full host
  and path information) first in case those files need to be restored.

- When working in a given repo, strive to be consistent in code style,
  form, and layout of the existing code in the repo. If repo conventions
  conflict with other recommendations below, call out the conflict and
  assume we'll follow the repo conventions.

- When planning code changes, check for any associated tests (e.g., make
  test targets, `self-test` subcommands, test files in `tests/`, etc)
  and run those tests to get a baseline. This is important because if
  existing tests don't work that could affect your planned testing.

- After modifying any code or utility, always run the associated tests
  (or all tests if won't take too long) before considering any changes
  complete.

- If a utility has tests and new functionality is being added, be sure
  to add tests for the new functionality.

- Always look at the contents of a file to see what kind of file it is,
  do not rely on file name extensions (or lack thereof).

    - Scripts that have "uv run --script" in their shebang are python
      scripts, not shell scripts (regardless of the file extension).

- When writing docs, pay attention to mixing user and developer content.
  If documentation contains both, always put user content first, since
  users don't care about developer content. Put developer content at the
  end, since developers need to read everything.

- Avoid the user of non-ascii characters. One exception is for tests
  that simulate non-ascii chars in inputs that our code has no control
  over.

## SCM Rules

- When generating commit comments, look at previous commit comments in
  the repo to determine any commit comment style and/or conventions and
  follow them.

  - Commit comments should not duplicate implementation details
    available in the commit itself. They should strive to provide a
    brief overview.

  - When working on a stack of commits in a repo, if editing commits lower
    in the stack, please don't stash and restore copies of files being
    edited, since restoring them can revert changes. Instead, create a
    local backup branch at the current branch's HEAD, reset to the commit
    that needs to be updated, make the edits and amend the commit, then
    cherry-pick the remaining commits from the backup branch back onto
    the current branch.

      - After the cherry-picks complete, run `git diff <backup-branch>` to
        verify the replay didn't silently drop or duplicate anything. For
        pure reorders or folds (no content change), the diff should be
        empty. For edits that change file content, the diff should show
        exactly the intended edit and nothing else.

      - The same technique applies to reordering commits in a stack:
        reset to the appropriate ancestor, then cherry-pick the commits
        back in the desired order. The diff-check from above still
        applies (for pure reorders, the diff should be empty).

      - To fold a later commit into an earlier one specifically, use the
        same backup-branch + reset + cherry-pick technique above. Do
        NOT use `git commit --fixup` + `git rebase -i --autosquash` —
        the "review the todo in the editor" safety only holds for a
        human at the terminal, not for an agent invocation, and a stale
        `--fixup=<sha>` can silently land in the wrong commit or be
        dropped.

      - Don't use `git rebase` in any form — not `rebase -i`, not
        `--autosquash`, not non-interactive `rebase <upstream>` or
        `--onto`, and not any `GIT_SEQUENCE_EDITOR` automation. Reasons:
        the "review in editor" property doesn't hold for an agent
        invocation; mid-rebase conflict resolution is a place silent
        loss happens; empty commits are dropped by default without
        warning; and the `git diff <backup-branch>` safety check loses
        its teeth because intended conflict-resolution drift can no
        longer be distinguished from accidental hunk loss. Use the
        cherry-pick + amend technique above for folds, reorders, and
        mid-stack edits. If a feature branch needs to be updated onto
        a moved base (the case `git rebase main` would normally
        cover), stop and ask — surface the options (merge commit, user
        rebases manually, or agent cherry-picks onto the new base with
        a diff-check) rather than choosing.

- Before pushing commits or publishing PRs for them, I like to review
  commits locally with a tool like `npx difit`. If I tell you I want to
  review a commit, then please publish it with `npx difit`. (Please
  note that `npx difit` runs a web server so the command doesn't exit
  immediately, so you should probably run it in the background.)

- If working on local commits (ie haven't been pushed to any repo), in
  general changes should go into the local commit that introduced the
  code being updated, not in new or follow on commits. (Ask if you think
  the changes should be done as a follow on commit.)

- When working on a stack of commits, if editing a commit mid-stack, be
  *very careful* not to leak functionality from other commits into the
  commit you're editing. Also, after you amend a commit in a stack,
  double check it to verify you didn't make this mistake. Mechanism to
  help avoid this include:

    - If commits are orthogonal, re-order them so the one you're
      working on is on the top of the stack.

    - If commits overlap, try checking out the commit that needs fixing,
      amending it with changes, and then cherry-picking the other
      commits on top (per the backup-branch technique in the SCM rules
      above — do not use `git rebase`). This ensures you don't
      accidently pull unwanted changes into a lower commit.

    - If commits overlap, you can also make your changes in new
      temporary commits that can be moved around in the stack and folded
      into a commit lower in the stack (both operations done via the
      backup-branch + cherry-pick technique above, not via `git
      rebase`).

## Python Rules

- Don't pollute the system python environment by installing
  system-wide Python packages. Also, never install per-user Python
  packages via `pip` or `pip3`.

- Be strongly typed, avoiding the storage of structured data in a Dict
  with Any values.

- When mocking functions always use `autospec=True` so that some
  argument verification occurs.

- When there are no pre-existing and conflicting repo Python style
  guidelines:
    - For stand-alone scripts, use "/usr/bin/env -S uv run --script" as
      the python shebang interpreter and use uv "dependencies"
      directives to satisfy dependencies.
    - Line wrap at 80 chars.
    - Be ruff and mypy compliant (which should be enforced via tests).
    - Use pytest for tests, unless there is a good reason for using an
      alternative framework, in which case please suggest it and explain
      why it should be used.

- In general, try to avoid catching all exceptions. Only catch specific
  exceptions you expect and include comments explaining why you're
  catching them.

- When generating dynamic strings or messages, default to using
  f-strings over concatenation.
