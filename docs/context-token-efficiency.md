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

## Gemini Direct token-offload path

Gemini Direct is an optional external EvidencePack generator. It never replaces
the OmniCodex parent and never responds to OpenAI quota exhaustion.

```text
premium parent
  -> deterministic search/stat/path narrowing
  -> immutable bounded scope capture
  -> measured ContextCostGate
     -> small/ineligible: native parent path
     -> large + approved + nonsensitive
        -> immutable approved capture
        -> one direct Gemini HTTPS request
        -> local EvidencePack validation + workspace re-snapshot
        -> compact pack to parent
        -> parent opens exact cited ranges and accepts or rejects
```

Only the deterministic capture is supplied to Gemini, together with the task,
snapshot, and EvidencePack schema. The provider has no workspace, shell, tool,
or Git access. The primary route starts no nested Codex process and requires no
WSL, Ubuntu, Docker, or OS sandbox. `GEMINI_API_KEY` is read from the environment
only; `OMNICODEX_GEMINI_MODEL` selects the model and defaults to
`gemini-3.5-flash-lite`.

Captured text is displayed with one-based line labels reset per file, including
blank lines. Original bytes, hashes, and size metrics remain unchanged. Labels
help locate citations but do not establish that a claim follows from the cited
text: only the premium parent's source verification can establish that.

The local validator rejects unknown fields, wrong task/snapshot, out-of-scope
files, invalid or missing line evidence, oversized packs, and a changed source
snapshot. The final acceptance check counts the UTF-8 bytes in the pack plus the
union of cited source ranges; that compact handoff must be at most 80% of the
captured raw estimate, preserving a minimum 20% estimated reduction. A failed or
stale pack is never promoted to evidence.

## Provider contracts

| Provider | First increment | Required gate | Native fallback |
|---|---|---|---|
| Context Mode | Skill-guided indexing/retrieval of large output | Opt-in, tools visible in the current agent, successful harmless probe, preserved raw evidence | Targeted reads and bounded native output with the same evidence rules |
| codebase-memory-mcp | Skill-guided structural discovery | Opt-in, tools/probe, matching worktree and fresh index | Search and exact source reads |
| RTK | Documented follow-on only | Future command-specific compatibility and exit-code tests | No automatic rewrite |
| Caveman-inspired brevity | Original structured handoff policy | Keep evidence, identifiers and failures intact | Longer report when necessary |
| Desktop Commander | Optional future tool provider | Actual host permissions, not just prompt instructions | Native tools |
| Gemini Direct | Direct generation of a compact pack from an immutable approved capture | ContextCostGate, explicit externalization approval, privacy scan, immutable scope, valid EvidencePack | Native parent path with transparent reason/status |

The Gemini Direct provider is a small standard-library implementation bundled
with OmniCodex. Context Mode and codebase-memory-mcp remain optional upstream
tools; their installation, compatibility, and performance claims are separate.

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

Its JSON reports `native_status: "READY"` and `free_context_offload: "READY"` or
`"NOT CONFIGURED"`, with the safe configured provider/model. It does not contact
Gemini, expose the key, or verify connectivity. `dry-run` validates a bounded
request and captures its approved scope without network access. `run` sends one
direct request and never loops across identical failures or promotes Gemini to
orchestrator.

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

Gemini Direct is a paid API integration and may incur billing. A free model name
does not establish free-tier account eligibility. Public workspaces and explicitly
approved private workspaces are eligible. Private workspaces without
approval stay native. Sensitive paths or content fail closed, including `.env`,
credentials/tokens/passwords, private keys, auth files, secret-bearing dumps,
binary files, and unrelated conversation or environment history.

`GEMINI_API_KEY` remains in the process environment. It is never written to the
request, argv, prompt, receipt, or installed configuration. Provider output is
checked for the credential before any result is accepted.

Path and content screening is a bounded fail-closed safeguard, not a substitute
for correct workspace classification. Operators must not approve a scope whose
sensitivity is uncertain. Detected sensitive names, bytes, links/reparse points,
binary content, or credentials reject the entire candidate scope.

Scope hashes cover only entries accepted after directory-membership checks; the
worker does not read unrelated workspace files to create or verify a capture.
Instruction-blacklist screening is heuristic, not a comprehensive injection
detector. Provider prose remains an untrusted locator until the premium parent
opens and verifies each cited source range.

## Receipts and failure behavior

Accepted runs write `evidence-pack.json` and `receipt.json` to a fresh private
directory outside the workspace. Receipts separate captured raw bytes,
`estimated_raw_tokens`, `estimated_evidence_pack_tokens`, cited verification
evidence, the combined compact handoff, and estimated premium context avoided
from actual worker input/cached-input/output/reasoning tokens. Routing uses the
captured file count, byte count, and line count; request metrics cannot inflate a
small scope into an offload. Served provider/model
and retry/fallback counts remain `null` unless reliable runtime evidence exposes
them. Root usage is recorded separately when available; billing and subscription
allowance are always unverified unless measured elsewhere.

Missing key produces a transparent native fallback. Unavailable Gemini service,
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
6. [OpenAI Codex permission profiles](https://learn.chatgpt.com/docs/permissions):
   current profile syntax, filesystem precedence, platform enforcement, and the
   non-composition rule for the older `--sandbox` settings; checked 2026-10-03.
7. [Gemini generateContent API](https://ai.google.dev/api/generate-content) and
   [structured JSON output](https://ai.google.dev/gemini-api/docs/structured-output):
   the direct provider uses header authentication, a compatible schema projection,
   and response usage/model metadata; checked 2026-10-03. The canonical local
   EvidencePack validator enforces constraints omitted from the API schema subset.
   Array bounds are enforced locally; documented text-part thought/signature
   metadata is discarded before accepting the final JSON pack.
