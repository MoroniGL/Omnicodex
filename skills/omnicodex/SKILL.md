# OmniCodex routing skill

Preserve required quality while avoiding expensive-model work that does not require expensive-model capability.

## Workflow
1. Read the active profile.
2. Decompose substantial requests into bounded phases.
3. Keep orchestration and acceptance with the profile control plane.
4. Delegate bounded work to the cheapest capable configured agent.
5. Diagnose failure before escalating.
6. Escalate only for a concrete capability or risk reason.
7. De-escalate after the expensive phase.
8. Verify the original acceptance criteria.

## Workers
- Luna: search, extraction, routine verification.
- Terra: exploration and normal implementation.
- Sol: planning, review, difficult debugging.
- Astra: exceptional unresolved work.

## Profiles
- Economy: Luna/Terra first.
- Balanced: Sol Medium control plane with Luna/Terra bulk execution.
- Quality: Sol High control plane.
- Max: Astra control plane; deterministic work can still be delegated.
- Auto: classify risk and complexity, then select a profile.

Never claim a model switch occurred unless the spawned agent actually uses the requested configuration. Never weaken correctness or acceptance criteria to save usage.
