# OmniClaude architecture

Status: experimental; source-level implementation only until validated in a real
Claude Code runtime.

Claude Code already provides the primitives OmniClaude needs: plugins, subagents,
skills, tool restrictions, and isolated context windows. OmniClaude therefore
uses native mechanisms rather than wrapping Claude in another orchestration server.

## Control plane

The parent conversation remains the control plane. Unlike Codex named profiles,
a Claude Code plugin cannot silently mutate the model of an already-running parent.
Launch-model recommendations are policy only:

- Economy candidate: benchmark Haiku versus Sonnet before selecting a default.
- Balanced candidate: Sonnet parent.
- Quality and Max candidate: Opus parent.

## Execution plane

The initial plugin intentionally exposes only four focused agents: Haiku research,
Sonnet implementation, Opus review, and Opus difficult debugging. Keeping the set
small reduces always-loaded agent descriptions and coordination overhead.

## Jev

Jev is an optional decision layer, not another worker. When explicitly enabled it
can score a bounded route, retry, review, or completion decision. The LLM parent
remains responsible for evidence, permissions, and final acceptance.

## Validation plan

1. `claude plugin validate --strict`.
2. Start with `--plugin-dir`; confirm skill and agents are discovered.
3. Run a read-only Balanced task with one Haiku child and one Sonnet child.
4. Confirm actual model metadata if exposed.
5. Compare native Claude Code, native `opusplan`, and OmniClaude on the same tasks.
6. Only then benchmark Jev on/off and measure false routing/review/completion decisions.
