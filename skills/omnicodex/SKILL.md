---
name: omnicodex
description: Coordinate bounded Codex work with explicit model roles, quality-preserving routing, optional context tools, compact evidence handoffs, and runtime capability checks.
---

# OmniCodex routing

Preserve required quality. Optimize unnecessary work, not correctness.

## Runtime and role selection

Read the active profile and project instructions. Discover the agents and tools
actually exposed in this runtime. A template or binary on PATH is not proof that
a role or MCP server can be called.

Use the native custom-role selector when exposed and select the configured role ID.
Check local per-turn metadata such as `turn_context` when available. Report the
source of the evidence: requested configuration, a local execution record, or a
provider response are different things. Local records are not independent proof
of the model actually served by a provider. Missing metadata means unverified,
not automatically broken.

When no native role selector exists, use an explicit model/effort delegation
fallback ONLY if the current tool schema supports it. Read the applicable role
instructions from project `.codex/agents/` or `$CODEX_HOME/agents/` and pass the
bounded task and required constraints. Preserve permissions and report fallback
execution rather than native role selection. Never invent arguments, bypass
approvals, or use an independent CLI call while claiming it was a child agent.

## Workflow

1. Decompose substantial requests into bounded phases. Keep tiny tasks local
   when delegation would add more overhead than useful work.
2. Keep planning, acceptance, and dependency tracking with the active orchestrator.
3. Delegate to the least expensive capable configured worker. Supply relevant
   paths, constraints, acceptance criteria, and existing evidence, not full history.
4. For structural discovery or large output, consult
   [optional efficiency adapters](references/efficiency.md) only when needed.
   Use approved, available providers or native targeted tools. For bounded routing,
   retry, review, or completion decisions, consult [Jev](references/jev.md) only when
   the operator explicitly enables it and the state can be safely externalized.
5. Diagnose failures before escalation. Escalate for a concrete capability barrier
   or material risk, not merely elapsed time. Do not repeat identical failed work.
6. Return to cheaper execution after the difficult phase; this changes workers,
   not the model of an already-running parent.
7. Verify original acceptance criteria using actual results and relevant source.
   Summaries, graph absence, and model confidence are not proof of correctness.
8. Return a compact report with status, changes, validation, evidence, risks, and
   next step. Include failures and unknowns even above a soft length target.

## Workers

- `luna-researcher`: `gpt-5.6-luna` / `low`; bounded search and extraction.
- `terra-explorer`: `gpt-5.6-terra` / `low`; focused code mapping.
- `terra-implementer`: `gpt-5.6-terra` / `medium`; bounded implementation.
- `sol-planner`, `sol-reviewer`: `gpt-5.6-sol` / `medium`; consequential decisions.
- `sol-debugger`: `gpt-5.6-sol` / `high`; difficult debugging.
- `astra-expert`: `gpt-6-astra` / `high`; exceptional unresolved work or an explicitly
  authorized escalation. Do not consume Astra merely to check its availability.

These are configured targets, not a universal availability guarantee. Verify
actual installation support before using a route.

## Profiles

Economy targets Terra Medium orchestration and favors Luna/Terra execution.
Balanced targets Sol Medium with Luna/Terra workers. Quality targets Sol High.
Max targets Astra High orchestration while still delegating bounded work when safe.
The profile name Max does not imply the reasoning string `max`.

Auto is a dynamic skill policy, not a fifth static profile. Classify each phase by
ambiguity, reversibility, blast radius, security/data-integrity risk, and verification
cost. Prefer Luna for narrow repeatable work, Terra for normal engineering, Sol for
consequential decisions, and Astra only for exceptional unresolved or critical-risk
work. Reassess at phase boundaries. Auto cannot change the running parent model;
use supported child roles, or request a new explicit profile when the parent must change.

Never weaken permissions, tests, security, or acceptance criteria to save usage.
Never claim a model switch solely from TOML, a prompt, or a worker self-report.
