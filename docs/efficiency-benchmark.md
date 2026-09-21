# Efficiency benchmark protocol

Status: protocol only; no measured savings published.

Compare the same task, starting commit/worktree, model/profile, reasoning effort,
acceptance tests, and permissions. Record client and provider versions, exact model
metadata, index state, and cache conditions. Count initial indexing/setup separately
from warm repeat sessions, but include both in total workflow cost. Use isolated
worktrees so earlier fixes do not leak into later conditions.

## Conditions

1. Native tools, no optional providers.
2. Compact handoffs only.
3. Compact handoffs + codebase-memory-mcp for structural tasks.
4. Compact handoffs + Context Mode for large outputs.
5. Combined graph and output paths, without stacking compressors on one output.

Alternate order and repeat each applicable condition at least three times. Include
small edits, unfamiliar repository exploration, long failing test logs, and a
cross-module bug. Report failures and worse outcomes, not just successful samples.
Use an independent review of the same tests/source for consequential changes.

## Per-run record

Record locally: task ID, commit/worktree fingerprint, condition, actual model and
reasoning if visible, tool versions, cold/warm state, elapsed time, tool calls,
retries, input/cached-input/output/reasoning tokens when exposed, raw/visible output
bytes, acceptance results, and unresolved issues. Use `null` for unavailable data.
Character counts are not token counts. Provider estimates are not billing records.
Redact source content, usernames, paths, tokens, and customer data before sharing.

## Release gates

- All mandatory tests and source checks still pass; no failures hidden in summaries.
- No lost exit statuses, failed tests, timeout states, or raw evidence references.
- Missing provider, rejected permission, stale graph, child MCP absence, and hook
  failure degrade transparently without bypassing restrictions or changing models.
- Report effect size and variation, plus setup/index overhead and failures.
- Do not multiply different projects' reduction percentages. Their denominators,
  tasks and overlapping layers differ.
- Do not translate API-token estimates into subscription allowance without direct
  allowance measurements from a comparable workload.

Offline policy tests are a prerequisite, not a replacement for live Codex/Claude
integration tests or these performance measurements.
