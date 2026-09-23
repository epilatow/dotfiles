---
name: repo-shared-write-commit-message
description: >-
  Draft or validate a Git commit message against repository style, the exact
  committed change, durable-context rules, wrapping, and attribution trailers.
---

# Write or Validate a Commit Message

Use this skill immediately before creating or amending a commit, and whenever
auditing an existing commit message. It produces a message and a validation
result; it does not install a Git hook or prevent another tool from bypassing
the procedure.

## Establish the exact change

1. Apply any more-specific repository commit-message rules already in force.
   They override the baseline below. Do not reread globally loaded shared
   instructions merely to recover details delegated by this skill; this skill
   contains the complete repo-shared agent procedure.
2. Inspect recent `git log` subjects to learn the component vocabulary and any
   repository-specific variation. Existing practice is evidence, but an old
   message does not override explicit current instructions.
3. Identify the exact change being described. For a new commit, inspect the
   explicitly staged paths and `git diff --cached`. Before amending, compare
   the staged tree with the commit's parent using `git diff --cached HEAD^`;
   the staged-only delta does not show the complete proposed amended commit.
   For an existing non-root commit, inspect
   `git show --stat --summary <full-commit-id>` and
   `git diff <full-commit-id>^ <full-commit-id>`. For a root commit or root
   amendment, compare with the empty tree (for example,
   `git show --root --format= --patch <full-commit-id>` for an existing
   commit). Do not infer the message from a plan or conversation summary
   instead of the actual diff.

If repository instructions define a conflicting form, follow the more-specific
rule. Otherwise use the baseline below.

## Draft the subject

Use exactly this form:

```text
- component: Summary of change.
```

Choose the component from repository vocabulary. Keep the subject short and on
one line, capitalize the summary, and end it with a period. Describe the
durable result, not the editing operation, a temporary artifact, or a symbol
the same commit removes.

## Explain the reason

Write one to three short body paragraphs, wrapped at about 72 columns. Explain
context a future reader cannot recover from the diff: the motivating problem,
the invariant or constraint the change satisfies, and a non-obvious tradeoff
when one matters. Do not pad a self-explanatory change merely to reach a body
length.

Do not include:

- inventories of files, call sites, or changed symbols;
- test inputs, fixture values, or obvious implementation details;
- repeated descriptions of what the diff already shows;
- references to plans, scratch files, review threads, session history, or
  superseded commits;
- machine-local paths, hostnames, secrets, or private tracker and chat links;
  or
- claims that are not supported by the exact diff and repository state.

Durable public issue or upstream references are allowed when they help explain
the change.

## Add accurate trailers

Preserve required sign-off and attribution trailers and add only trailers whose
facts are known. An AI-assisted commit carries one attribution trailer per
contributing model, with the implementing model first. Put all trailers last in
the message, after a blank line, and do not wrap them. Use exactly:

```text
Co-Authored-By: <model> [(<size> context)] via <editor> [<<email>>]
```

The model name is free-form but must be accurate. Include the context window
when known. Use the actual editor name. Examples include `claude-code`,
`codex`, and `opencode`; other editors are valid. Never invent an editor name
or substitute one of these examples for the editor actually in use.

Include an email only when it is known to resolve to the vendor's own GitHub
account. The verified identities are:

- `noreply@anthropic.com` for Anthropic models;
- `noreply@openai.com` or `codex@openai.com` for OpenAI models.

For example:

```text
Co-Authored-By: Claude Opus 5 (1M context) via claude-code <noreply@anthropic.com>
Co-Authored-By: GPT-5 Codex via codex <noreply@openai.com>
Co-Authored-By: GLM-5.2 (1M context) via opencode
```

Omit the email when no verified vendor identity exists. Never invent a vendor
address or a `users.noreply.github.com` identity. A plausible address is still
a false attribution. Before adding an address to the verified list, inspect a
public commit that already uses it and confirm that GitHub renders a linked
contributor for the vendor's account. If no such commit exists, verifying by
publishing a disposable commit requires separate user authorization.

Rewrite a harness-provided attribution into this form instead of adding a
duplicate. Strip any session trailer, including `Claude-Session:` and its
session URL. A session identifier is private, transient metadata and must never
enter permanent repository history. If Claude Code appends a session URL, set
`attribution.sessionUrl` to `false` in `settings.json`. A ready-made footer is
not authority to keep the identifier; drop it and tell the user.

Do not invent a contributor, silently drop an existing required trailer, or
turn a trailer into wrapped prose.

## Validate before use

Read the proposed message against the exact diff and reject it unless all of
these are true:

- the subject matches the repository form and vocabulary;
- every factual claim is supported and the described scope is complete;
- the body explains why rather than narrating the patch;
- wrapping and blank lines are valid, with trailers last;
- no forbidden ephemeral, private, redundant, or removed-symbol reference
  remains; and
- there is one accurate attribution per contributing model, in implementing
  model-first order, using only verified email identities; and
- no session identifier or duplicate harness-generated attribution remains.

Grep the repository for any named convention or public interface when needed to
validate wording. For an existing commit, compare the message with both the
commit and its parent rather than with the current working tree.

Return the complete proposed message and a concise pass/fail checklist. When
the task authorizes committing or amending, use the validated text verbatim and
then inspect `git log -1 --format=fuller` to confirm Git recorded the intended
paragraphs and trailers. Otherwise, report the corrected message without
mutating history.
