# Temporary-cache cleanup

The daily `cleanup-var-tmp` Crony job removes unused Node compilation-cache
files and pytest temporary runs from `$TMPDIR`. There is no age threshold; the
daily schedule supplies the cleanup window. Other temporary files and
unrecognized cache layouts are left alone.

Preview eligible entries and check traversal time:

```sh
~/.local/libexec/cleanup-var-tmp/cleanup-var-tmp
```

Pass `--apply` to delete eligible caches. `--tmpdir PATH` selects a different
temporary directory. Requires Python 3.15, uv, lsof, and find. The job is
enabled on macOS through the existing `daily-misc` group.

Files reported in use, live pytest PID locks, uncertain locks, symlinks, and
entries belonging to another user are preserved. Changed candidates are
skipped. Activity checks are snapshots: a process can open a cache after the
check. Cleanup does not terminate any process. Recent repository-local pytest
diagnostics outside `$TMPDIR` are unaffected.

After cleanup, a complete traversal of `$TMPDIR` must finish within 60 seconds.
Exceeding that limit stops the traversal and fails the job, including during a
preview. Files disappearing during traversal are tolerated; other cleanup or
traversal errors fail the job.
