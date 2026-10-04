# Roadmap

## v0.1 — Foundation
- [x] Define cost-aware routing policy.
- [x] Define escalation and de-escalation semantics.
- [x] Define initial agent roles.
- [x] Define Economy, Balanced, Quality, Max and Auto profiles.
- [x] Separate control plane from execution plane.
- [x] Validate current Codex plugin/custom-agent schema.
- [x] Implement installable agent definitions.
- [x] Add routing skill and profile selection.
- [x] Add installer and rollback-oriented update path.
- [x] Add configuration validation.
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


## OmniCodex completion track — token offload

- [x] Define an offline ContextCostGate with profile-specific starting thresholds.
- [x] Define a bounded, source-linked EvidencePack contract.
- [x] Require workspace opt-in and block sensitive external offload.
- [x] Explicitly exclude quota fallback from the Gemini Direct context-worker route.
- [x] Add estimated context-avoidance receipts without claiming billing savings.
- [x] Refactor the root routing skill toward progressive disclosure for GPT-6-era models.
- [x] Connect an optional read-only Gemini Direct worker through a direct HTTP provider.
- [x] Prove offline that the worker sends only a bounded immutable capture rather than source outside the approved scope.
- [x] Record requested route, worker usage when exposed, latency, failures, and local validation status.
- [x] Gate on captured scope metrics and enforce pack-plus-citations context reduction.
- [x] Remove the nested Codex worker and its stage-only permission profile from the primary route.
- [ ] Verify served model/provider, root usage, and acceptance quality in controlled live benchmarks.
- [ ] Tune thresholds from representative Windows benchmarks.
- [ ] Evaluate GPT-6.1 Sol / GPT-6 Luna profile migrations separately from the offload worker.
- [ ] Package the stable OmniCodex stack as a Codex/ChatGPT plugin with trusted lifecycle hooks.
- [x] Complete controlled Gemini Direct acceptance on Windows and publish measured rows without billing claims.
