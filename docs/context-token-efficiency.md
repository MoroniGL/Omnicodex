# Context & Token Efficiency Architecture

Status: experimental, live worker implemented. Reviewed 2026-10-03.

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

## FreeLLMAPI token-offload path

FreeLLMAPI is an optional context reader, never the OmniCodex root provider and
never a response to OpenAI quota exhaustion.

```text
premium parent
  -> deterministic search/stat/path narrowing
  -> ContextCostGate
     -> small/ineligible: native parent path
     -> large + approved + nonsensitive
        -> immutable bounded scope capture
        -> private staged copy
        -> one ephemeral read-only Codex exec using FreeLLMAPI
        -> local EvidencePack validation + workspace re-snapshot
        -> compact pack to parent
        -> parent opens exact cited ranges and accepts or rejects
```

The original source bytes are not placed in the prompt. The worker receives the
task kind, concise objective, approved repo-relative names, snapshot, and pack
budgets, then reads the staged files itself. `--ephemeral`, `--sandbox read-only`,
`--output-schema`, JSONL events, `--output-last-message`, and per-invocation
provider overrides isolate the worker without changing global or parent provider
configuration. Web search is disabled and the staged workspace has no Git state.

The local validator rejects unknown fields, wrong task/snapshot, out-of-scope
files, invalid or missing line evidence, oversized packs, and a changed source
snapshot. A failed or stale pack is never promoted to evidence.

## Provider contracts

| Provider | First increment | Required gate | Native fallback |
|---|---|---|---|
| Context Mode | Skill-guided indexing/retrieval of large output | Opt-in, tools visible in the current agent, successful harmless probe, preserved raw evidence | Targeted reads and bounded native output with the same evidence rules |
| codebase-memory-mcp | Skill-guided structural discovery | Opt-in, tools/probe, matching worktree and fresh index | Search and exact source reads |
| RTK | Documented follow-on only | Future command-specific compatibility and exit-code tests | No automatic rewrite |
| Caveman-inspired brevity | Original structured handoff policy | Keep evidence, identifiers and failures intact | Longer report when necessary |
| Desktop Commander | Optional future tool provider | Actual host permissions, not just prompt instructions | Native tools |
| FreeLLMAPI | Direct read-only processing of large approved context | ContextCostGate, explicit externalization approval, privacy scan, immutable scope, valid EvidencePack | Native parent path with transparent reason/status |

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

The installed live-worker diagnostic is also offline:

```sh
python3 "$CODEX_HOME/omnicodex/scripts/free_context_worker.py" doctor
```

It reports whether `codex` and `FREELLMAPI_API_KEY` are locally available. It
does not contact FreeLLMAPI, expose the key, verify a runtime model, or claim a
working gateway. `dry-run` validates a bounded request, captures its approved
scope, runs the gate, and displays a sanitized command without making a network
request. `run` invokes one Codex worker process; it never loops across identical
failures or promotes FreeLLMAPI to orchestrator. FreeLLMAPI may perform its own
provider routing, which is outside OmniCodex's retry control and is recorded only
when reliable runtime telemetry exposes it.

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

## Privacy and credential boundary

FreeLLMAPI can route to third-party free providers. Public workspaces and
explicitly approved private workspaces are eligible. Private workspaces without
approval stay native. Sensitive paths or content fail closed, including `.env`,
credentials/tokens/passwords, private keys, auth files, secret-bearing dumps,
binary files, and unrelated conversation or environment history.

`FREELLMAPI_API_KEY` remains in the process environment. It is never written to
the request, argv, prompt, receipt, or installed configuration. The Codex model
provider receives it, while the worker's shell environment policy explicitly
excludes it from model-initiated commands. Provider output is checked for the
credential before any result is accepted.

## Receipts and failure behavior

Accepted runs write `evidence-pack.json` and `receipt.json` to a fresh private
directory outside the workspace. Receipts separate `estimated_raw_tokens`,
`estimated_evidence_pack_tokens`, and `estimated_premium_context_avoided` from
actual worker input/cached-input/output/reasoning tokens. Served provider/model
and retry/fallback counts remain `null` unless reliable runtime evidence exposes
them. Root usage is recorded separately when available; billing and subscription
allowance are always unverified unless measured elsewhere.

Missing key/Codex produces a transparent native fallback. Unavailable gateway,
timeout, nonzero exit, malformed output, credential leakage, invalid evidence,
or workspace mutation produces a failed receipt and recommends native handling.
There is no destructive retry and no quota-triggered route.

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
