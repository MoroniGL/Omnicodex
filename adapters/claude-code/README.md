# OmniClaude — experimental Claude Code adapter

OmniClaude brings OmniCodex's control-plane/execution-plane idea to Claude Code
using the native plugin and subagent formats.

## Current roles

| Role | Target model | Purpose |
|---|---|---|
| researcher | Haiku | bounded read-only search and extraction |
| implementer | Sonnet | ordinary engineering and implementation |
| reviewer | Opus | consequential independent review |
| debugger | Opus | difficult unresolved debugging |

These are initial policy targets, not benchmark conclusions.

## Local validation

Use a current Claude Code build:

```sh
claude plugin validate ./adapters/claude-code --strict
claude --plugin-dir ./adapters/claude-code
```

Then invoke `/omniclaude:omniclaude` or ask Claude to use the OmniClaude policy.
Validate actual subagent selection and model metadata where the runtime exposes it.

Claude Code loads plugin agent names/descriptions into session context, so this
adapter deliberately starts with a small role set. Add roles only after measuring
quality, context cost, and delegation overhead.

## Jev

The shared Jev integration is opt-in and uses TypeSafe AI's official REST API via
the repository helper `scripts/jev.py`. No key is bundled. A standalone copy of
this plugin does not make Jev calls unless an operator separately supplies a
reviewed helper/tool and explicitly enables it.

Jev returns typed decisions; it does not generate code or replace Claude.
