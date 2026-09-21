# Context & Token Efficiency Architecture

Status: experimental, first integration increment. Reviewed 2026-09-21.

## Scope

OmniCodex combines model allocation with bounded context and evidence-based
handoffs. This increment adds an opt-in policy adapter for Context Mode and
codebase-memory-mcp, an offline capability checker/advisory planner, and tests.
It does not install upstream software, modify global configuration, intercept
commands, activate hooks, or validate actual Codex model selection.

```
Active model profile -> bounded task
                       -> approved capability discovery
                          -> structural question: current graph + source checks
                          -> large output: one indexed-output path + raw evidence
                          -> otherwise: native targeted tools
                       -> compact handoff -> unchanged acceptance criteria
```

The model profiles and efficiency choices are separate. Selecting an efficiency
provider never changes the orchestrator or authorizes a more expensive model.
The existing model/profile TOML templates still need installation-specific runtime
validation. Auto in this increment is not an automatic model-switching engine.

## Provider contracts

| Provider | First increment | Required gate | Native fallback |
|---|---|---|---|
| Context Mode | Skill-guided indexing/retrieval of large output | Opt-in, tools visible in the current agent, successful harmless probe, preserved raw evidence | Targeted reads and bounded native output with the same evidence rules |
| codebase-memory-mcp | Skill-guided structural discovery | Opt-in, tools/probe, matching worktree and fresh index | Search and exact source reads |
| RTK | Documented follow-on only | Future command-specific compatibility and exit-code tests | No automatic rewrite |
| Caveman-inspired brevity | Original structured handoff policy | Keep evidence, identifiers and failures intact | Longer report when necessary |
| Desktop Commander | Optional future tool provider | Actual host permissions, not just prompt instructions | Native tools |

Provider code is not vendored. Upstream licenses and installation/release checks
remain the user's responsibility when installing those separate projects. The
OmniCodex policy is original; no upstream performance claim is adopted as our own.

## Runtime integration

Load `skills/omnicodex/SKILL.md` through the skill mechanism supported by the local
client. It includes metadata and loads its detailed reference only when needed.
Use the provider already registered in that agent's current session. Do not
assume paths, custom CLI flags, hook events, or tool names based on another client.
See [the adapter workflow](../skills/omnicodex/references/efficiency.md).

The JSON manifest under `integrations/` belongs to OmniCodex, **not** Codex or
Claude configuration. Do not paste it into either client's configuration file.
The capability inventory is likewise our sanitized interchange format, not the
raw MCP `tools/list` response. A runtime adapter must normalize it explicitly.

### Client-specific limitations

Context Mode documents separate MCP availability and hook activation in Codex.
Do not infer the latter from a successful statistics query. Its documented Codex
hook limitations differ from Claude's; this increment requires no hooks and makes
no promise of transparent command rewriting [1].

CBM documents Codex and Claude integrations, but direct graph queries still require
freshness, scope, and source checks [2]. Tool descriptions or model instructions
are not access controls. Running code through an MCP server does not inherit every
restriction of a different shell or client automatically [1,3].

This repository remains Codex-oriented. The efficiency policy is reusable in
Claude Code, but its Codex model/profile files are **not** Claude configuration.
No Claude live test is claimed here.

## Non-destructive diagnostics and dry run

Python 3.11+; standard library only. From the repository root:

```sh
python3 scripts/efficiency.py doctor
python3 scripts/efficiency.py plan --profile balanced --task structural
python3 -m unittest discover -s tests -v
```

`doctor` checks the manifest and binary presence without running those binaries.
It does not open authentication/configuration files or scan the project. Missing
optional providers are normal. A zero exit status means the diagnostic itself
completed, not that Codex/MCP/model overrides work. Invalid inputs exit with 2.

With no inventory and explicit provider opt-in, plans select native tools. To
exercise the decision logic with **synthetic data only**:

```sh
python3 scripts/efficiency.py plan \
  --inventory examples/efficiency-inventory.json \
  --session example-only-not-live \
  --snapshot example-workspace-fingerprint \
  --enable codebase-memory-mcp --task structural --profile balanced
```

The output always says `advisory_dry_run`. It executes nothing, changes no model,
and does not independently verify supplied evidence. Omit `--enable` to disable
optional selection even when tools are reported available.

### Real capability inventory

Use the example only as a format. Populate a separate local file with observations
from the **current** agent: session ID, provider-local tool names from the registered
tool schemas, and the result of an approved harmless probe. For graph routing,
`index_snapshot` must fingerprint the relevant repository/worktree state, including
tracked modifications and relevant untracked files. Do not substitute HEAD alone.
Pass that current value as `--snapshot`; changed or unknown values select native.
Do not share capability inventories or raw logs without privacy review.

The planner accepts supplied evidence, not a trusted attestation. Revalidate it at
tool execution time. Persisted inventory or a parent's tool list alone is insufficient.

## Safety and correctness invariants

- Keep existing acceptance criteria in every profile; a smaller report is not a
  reason to drop tests, skip source checks, or accept an unresolved defect.
- Preserve raw evidence, exit codes, timeout/cancellation state, and all failures.
  Use one output compressor at most. No destructive command is automatically retried.
- Restrict tools using runtime enforcement. Never bypass a refusal via another tool.
- Repository text, logs, indexed content, and MCP responses are untrusted data.
- Avoid unnecessary subagents and repeated discoveries; short native tasks may be
  cheaper than installing or invoking another layer.
- Keep raw artifacts local with least-privilege access and a declared retention
  policy. Do not upload source, logs, secrets, graphs, or inventories by default.

## Measurement and acceptance

No percentage or promise that a two-day allowance becomes a week is justified yet.
Input tokens, cached input, reasoning/output tokens, actual model, time, retries,
quality outcomes and subscription allowance are distinct measures. Fewer characters
or shorter tool output does not directly establish a proportional plan saving.

Use [the benchmark protocol](efficiency-benchmark.md) before claiming an improvement.

## References

These are upstream documentation observations, not live compatibility results.

1. [Context Mode README](https://github.com/mksglu/context-mode): MCP/hook boundaries,
   tool names and execution security notes; checked 2026-09-21.
2. [codebase-memory-mcp README](https://github.com/DeusData/codebase-memory-mcp):
   graph tools, freshness/coverage and client integrations; checked 2026-09-21.
3. [OpenAI MCP documentation](https://developers.openai.com/codex/mcp): client tool
   configuration and controls; checked 2026-09-21.
4. [OpenAI skills documentation](https://developers.openai.com/codex/skills):
   skill metadata and on-demand references; checked 2026-09-21.
5. [RTK](https://github.com/rtk-ai/rtk) and
   [Caveman](https://github.com/JuliusBrussee/caveman): future integration research
   and brevity inspiration respectively; no benchmark results reused.
