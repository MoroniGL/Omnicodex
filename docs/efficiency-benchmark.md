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


## FreeLLMAPI token-offload condition

Add a separate condition after deterministic narrowing:

6. Read-only FreeLLMAPI context worker returns a validated EvidencePack; the
   premium parent receives the pack and opens only exact evidence needed for
   decisions.
7. Optional graph/index adapters plus the FreeLLMAPI worker, without stacking
   multiple lossy compressors on the same evidence.

For these conditions, record measured captured bytes and their token estimate,
EvidencePack size, the union of exact cited ranges, the combined compact handoff,
actual worker provider/model when visible, worker usage, root input/cached-input,
and task acceptance. Estimated premium context avoided is not a billing record
and must not be translated directly into subscription allowance.

Run native and offload conditions from identical clean snapshots. Hash the
complete synthetic workspace before and after each run, retain the compact pack
and receipt, and independently reopen every cited range used for acceptance. A
run is not a token-offload success when pack plus cited ranges is at least as
large as the measured raw scope, even if the pack alone is small.
Report missing telemetry as `null`; do not copy a worker's prose claim about its
model/provider into runtime evidence. Record failed-run rows for unavailable,
timeout, invalid-pack, and stale-workspace behavior instead of omitting failures.
