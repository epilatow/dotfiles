// This is AI generated code
//
// Custom markdownlint rule: ``@<path>`` file-import references must be
// one per line.
//
// CLAUDE.md and related agent-instruction files use Claude Code's
// ``@<path>`` syntax to import additional files as context. If
// ``mdformat`` reflows two adjacent ``@<path>`` paragraphs onto one
// line, Claude still expands both -- but the source is opaque and the
// intent (one logical include per paragraph) is lost. Any
// loader-specific dialect built on top (e.g. an ``append @<path>``
// prefix that splits line-by-line on ``^append @``) gets actively
// broken by the same reflow.
//
// Vendored at ``_repo_shared/dotfiles/...`` and canonical-symlinked at
// ``.markdownlint-rule-no-squashed-file-references.mjs`` in the
// consumer; registered via ``customRules`` in
// ``.markdownlint-cli2.jsonc`` and explicitly enabled in
// ``.markdownlint.json`` (custom rules are off by default even when
// ``default: true`` is set).
//
// ESM export: markdownlint-cli2 0.18+ loads custom rules via dynamic
// ``import()``, so the rule has to be ``export default`` and the file
// has to be ``.mjs`` (CommonJS ``module.exports`` in a ``.js`` file
// silently fails to load on consumers whose repo has no
// ``package.json`` declaring ``"type": "module"``).

// ``@<path>`` where the path is one or more non-whitespace chars. The
// ``(?:^|\s)`` anchor avoids matching emails (``foo@bar.com``) or
// other intra-word at-signs.
const FILE_REF_RE = /(?:^|\s)(@\S+)/g;

const rule = {
  names: ["no-squashed-file-references"],
  description:
    "Multiple ``@<path>`` file-import references on one line are an " +
    "mdformat reflow artifact -- one per paragraph keeps the source " +
    "and any loader-specific dialect parseable.",
  tags: ["custom", "file-reference"],
  parser: "none",
  function: (params, onError) => {
    params.lines.forEach((line, index) => {
      const matches = [];
      let m;
      while ((m = FILE_REF_RE.exec(line)) !== null) {
        matches.push(m[1]);
      }
      if (matches.length > 1) {
        onError({
          lineNumber: index + 1,
          detail:
            "found " +
            matches.length +
            " ``@<path>`` references on one line (" +
            matches.join(", ") +
            "); put each on its own paragraph with a blank line " +
            "above and below so mdformat doesn't re-squash them.",
        });
      }
    });
  },
};

export default rule;
