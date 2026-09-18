# OmniCodex contributor instructions

## Mission
Build a reliable, cost-aware routing layer for Codex. Preserve output quality while minimizing unnecessary use of expensive models.

## Engineering rules
- Verify supported Codex behavior before depending on it.
- Do not claim automatic model switching unless the runtime actually supports it.
- Prefer documented custom-agent/plugin mechanisms.
- Keep routing policy separate from runtime adapters.
- Make the smallest safe change.
- Do not introduce production dependencies without a clear need.
- Run relevant tests and validation after changes.
- Never weaken correctness, security, tests, or review solely to reduce usage.

## Routing philosophy
Use the cheapest model that can safely complete the current bounded task. Escalate only after identifying a concrete blocker. De-escalate immediately when the expensive phase ends.

## Contribution output
For meaningful changes report:
1. what changed;
2. files changed;
3. validation performed;
4. remaining risks or unsupported assumptions.
