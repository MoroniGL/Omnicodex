# Roadmap

## v0.1 — Foundation
- [x] Define cost-aware routing policy.
- [x] Define escalation and de-escalation semantics.
- [x] Define initial agent roles.
- [x] Define Economy, Balanced, Quality, Max and Auto profiles.
- [x] Separate control plane from execution plane.
- [ ] Validate current Codex plugin/custom-agent schema.
- [ ] Implement installable agent definitions.
- [ ] Add routing skill and profile selection.
- [ ] Add installer and uninstall path.
- [ ] Add configuration validation.
- [ ] Add example project integration.

## Context & Token Efficiency — first increment
- [x] Document optional providers, native fallback, and evidence safety contracts.
- [x] Add Context Mode and codebase-memory-mcp skill-guided policy adapters.
- [x] Add offline diagnostics and advisory plans from supplied capability inventories.
- [x] Add compact handoff instructions and on-demand skill reference.
- [x] Add offline tests for opt-in, freshness/session checks, fallback, and input validation.
- [x] Define a benchmark protocol without claiming measured savings.
- [ ] Verify live MCP tool access in both parent and child agents on supported clients.
- [ ] Verify raw-output retrieval, exit codes, permissions, and failure handling live.
- [ ] Measure acceptance quality, latency, tokens, setup overhead, and allowance impact.
- [ ] Add opt-in, version-aware installer with backups and collision handling.
- [ ] Evaluate RTK command-specific integration; avoid stacked compression.
- [ ] Implement opt-in persistent project memory with invalidation and retention policy.

## OmniClaude + Jev — experimental
- [x] Add a Claude Code plugin skeleton with focused Haiku/Sonnet/Opus workers.
- [x] Add an opt-in TypeSafe Jev REST helper and shared routing policy.
- [ ] Validate the plugin with a real local Claude Code runtime.
- [ ] Benchmark OmniClaude against native Claude Code and opusplan.
- [ ] Validate Jev route/retry/review/completion decisions on real coding tasks.
- [ ] Measure whether Jev reduces expensive-model calls without increasing rework.
- [ ] Decide whether Jev should remain advisory or gain a narrowly scoped hook/MCP adapter.

## v0.2 — Observability
- Route decision log.
- Profile decision log.
- Usage-oriented task accounting where supported.
- Escalation/de-escalation metrics.
- Runtime-backed routing diagnostics (offline advisory mode is now available).

## v0.3 — Adaptive routing
- Auto profile classifier.
- Project-specific routing profiles.
- Risk-aware review policies.
- Temporary per-task profile overrides.
- Configurable budget targets.
- Benchmark suite for quality vs. usage.

## Non-goal
OmniCodex will not silently depend on undocumented model-switching behavior.
