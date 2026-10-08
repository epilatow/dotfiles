# Gas-price snapshots

Append a snapshot with:

```bash
gas-prices-breakdown add-snapshot page.html --agent claude --model opus
```

The utility collects inputs, asks an agent to amend them, then validates and
publishes the result. Existing snapshot information is preserved. The default
target is the most recent Thursday; an existing target exits without doing
work. Use `gas-prices-breakdown add-snapshot --help` for available options.

Linkfiles installs the executable. The scheduled command is maintained in the
[crony configuration](../../../config/crony/config.toml).

## Dry runs and comparisons

A dry run saves data and a generated page without publishing. Use a page that
does not already contain the target date:

```bash
gas-prices-breakdown add-snapshot page.html --dry-run \
  --agent claude --model opus --state-dir /tmp/gas-claude
gas-prices-breakdown add-snapshot page.html --dry-run --agent codex \
  --state-dir /tmp/gas-codex --inputs /tmp/gas-claude/runs/RUN/collected.json
```

The utility logs the run directory; replace `RUN` with that run's name. Give
each comparison its own state directory and the same saved inputs. Compare
numeric results separately from citations and explanations.

Retries reuse cached inputs and accepted amendments. Changing the agent or
model does not force another amendment pass; use a fresh state directory for
that. On failure, inspect `failure.json` and `agent.log` in the logged run
directory.

## Custom harnesses

For a CLI without a preset, `--agent-command` (or `GAS_PRICES_AGENT_COMMAND`)
accepts a JSON argv array containing `{prompt}`. It can also use `{workspace}`.
When selecting a model with `--model`, include `{model}` in the custom
arguments. Arguments are passed without a shell.

## Reference

- [Utility](gas-prices-breakdown) and
  [numeric collectors](gas_prices_collectors.py): collection and calculation
  implementation.
- [Agent skill](skills/update-gas-prices/SKILL.md): amendment workflow and
  result requirements.
- [Source guide](skills/update-gas-prices/references/sources.md) and
  [fee-allocation audit](skills/update-gas-prices/references/fee-allocation.md):
  research guidance and accounting scope.
