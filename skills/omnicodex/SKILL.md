---
name: omnicodex
description: Coordinate bounded coding work with quality-preserving model routing, optional context tools, compact evidence handoffs, and explicit capability checks.
---

# OmniCodex routing

Preserve required quality. Optimize unnecessary work, not correctness.

## Workflow
1. Read the active profile and project instructions. Check which agents and tools
   are actually exposed. A template or binary on PATH is not runtime evidence.
2. Decompose substantial requests into bounded phases. Do not create a subagent
   for every shell command; keep tiny tasks local when delegation adds overhead.
3. Keep planning, acceptance, and dependency tracking with the active orchestrator.
4. Delegate to the least expensive capable configured worker. Supply relevant
   paths, constraints, acceptance criteria, and existing evidence, not the full history.
5. For structural discovery or large output, consult
   [optional efficiency adapters](references/efficiency.md). Use only approved,
   available tools; otherwise keep native tools. Load this reference only as needed.
6. Diagnose failures before escalation. Return to cheaper execution after the
   difficult phase. Do not repeatedly retry identical failed work.
7. Verify the original acceptance criteria using actual results and relevant source.
   Summaries, graph absence, and model confidence are not proof of correctness.
8. Return a compact report: status, changes, validation, evidence, risks, next step.
   Include failures and unverified work even if the report exceeds its soft target.

## Workers
- `luna-researcher`: bounded search, extraction, routine verification.
- `terra-explorer`: map relevant code and dependencies.
- `terra-implementer`: bounded implementation and ordinary fixes.
- `sol-planner`, `sol-reviewer`, `sol-debugger`: consequential decisions and review.
- `astra-expert`: exceptional unresolved work, subject to the active profile.

## Profiles
Economy favors Luna/Terra. Balanced targets Sol Medium orchestration with
Luna/Terra execution. Quality targets Sol High. Max targets Astra orchestration
while still allowing sensible delegation. Auto selects a policy based on task risk;
it does not, by itself, change the running model.

Never claim a model switch without runtime metadata. If unsupported or unknown,
request the required supported launch/delegation mechanism instead of pretending.
Never weaken permissions, tests, security, or acceptance criteria to save usage.
