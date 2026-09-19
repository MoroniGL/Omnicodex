---
name: omnicodex
description: Route bounded Codex work through explicit, verified model and reasoning configurations while preserving acceptance criteria.
---

# OmniCodex routing skill

Preserve required quality while avoiding expensive-model work that does not require expensive-model capability.

## Balanced runtime
Use Balanced with the Sol control plane at `gpt-5.6-sol` / `medium`.

Assign bounded work by the configured role:

- `luna-researcher`: `gpt-5.6-luna` / `low` for research, extraction, and routine verification.
- `terra-explorer`: `gpt-5.6-terra` / `low` for focused repository exploration and implementation mapping.
- `terra-implementer`: `gpt-5.6-terra` / `medium` for bounded implementation.

Use a native custom-role selector when the active runtime exposes one. Select the configured role ID. When the spawned turn exposes `turn_context`, verify that it reports the required full model ID and reasoning effort; otherwise record that the runtime configuration is unverified.

Some V2 APIs do not expose a custom-role selector. In that case, read the selected role's `developer_instructions` from `.codex/agents/<role-id>.toml` in the project or `$CODEX_HOME/agents/<role-id>.toml` (default `~/.codex/agents`), pass those full instructions with an isolated task context, and explicitly pass the role's full `model` and `model_reasoning_effort`. Report that this is a fallback execution, not a native role selection. When `turn_context` is unavailable, disclose the configuration as unverified; never infer or report a model switch from TOML configuration, a prompt, or a worker self-report.

## Workflow
1. Read the active profile and inspect the control turn's `turn_context` when the runtime exposes it; otherwise record that verification is unavailable.
2. Decompose substantial requests into bounded phases with isolated context.
3. Keep orchestration and acceptance with the profile control plane.
4. Delegate each phase to the cheapest capable configured role and validate its `turn_context`.
5. Diagnose failure before escalating.
6. De-escalate after the expensive phase.
7. Verify the original acceptance criteria.

## Workers
- Luna: search, extraction, routine verification.
- Terra: exploration and normal implementation.
- Sol: planning, review, difficult debugging.
- Astra: in Economy, Balanced, and Quality, only a concrete exceptional blocker or a user-controlled escalation, at `gpt-6-astra` / `high`. In Max, Astra is the control plane.

## Profiles
- Economy: Luna/Terra first.
- Balanced: Sol Medium control plane with Luna/Terra bulk execution.
- Quality: Sol High control plane.
- Max: Astra control plane; deterministic work can still be delegated.
- Auto: classify risk and complexity, then select a profile.

Never claim a model switch occurred unless the spawned turn's exposed `turn_context` contains the requested full model ID and reasoning effort. If `turn_context` is unavailable, report the execution as unverified. Never weaken correctness or acceptance criteria to save usage.
