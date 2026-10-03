# Local installation and runtime validation

Validated with Codex CLI **0.153.4** on macOS. This is a routing smoke test, not a quality or quota-savings benchmark. See Issue #1.

## Installation layout

| Repository source | Personal destination |
|---|---|
| `agents/*.toml` | `$CODEX_HOME/agents/*.toml` (default `~/.codex/agents/`) |
| `profiles/*.config.toml` | `$CODEX_HOME/omnicodex-<profile>.config.toml` |
| `skills/omnicodex/SKILL.md` | `~/.agents/skills/omnicodex/SKILL.md` |
| Token-offload runtime scripts and Gemini provider package | `$CODEX_HOME/omnicodex/scripts/` |
| `integrations/efficiency.json` | `$CODEX_HOME/omnicodex/integrations/efficiency.json` |
| `schemas/evidence-pack.schema.json` | `$CODEX_HOME/omnicodex/schemas/evidence-pack.schema.json` |

Run `python3 scripts/install.py`. Before writing, the installer backs up the existing `config.toml` and any destination files to a private, timestamped directory. It refuses conflicting destinations instead of overwriting them unless a reviewed update explicitly uses `--replace-existing`. It records hashes and whether each destination already existed. The seven agent definitions use the supported standalone schema (`name`, `description`, `developer_instructions`, `model`, `model_reasoning_effort`). The routing skill needs YAML `name` and `description` frontmatter to be discoverable.

Keep the existing `config.toml` unchanged. The namespaced profile avoids replacing an existing `balanced` profile. Select it for a new CLI session:

```sh
codex --strict-config -p omnicodex-balanced
```

The profile invokes the installed routing skill. Its primary model is `gpt-5.6-sol` / `medium`, with `gpt-5.6-terra` / `medium` as the fallback worker. Native named roles select their own explicit model and effort. Astra is reserved for exceptional escalation in Balanced.

Profiles do not reconfigure already-running sessions. Desktop model selections can override file defaults. This validation establishes CLI behavior; it does not establish that Desktop automatically selects this named profile.

Official Codex precedence is CLI flags, trusted project `.codex/config.toml`, selected profile, user `config.toml`, managed/system configuration, then built-in defaults. Use `python3 scripts/install.py --inspect-profile omnicodex-balanced --cwd "$PWD"` to report the user/profile/project model layers. CLI `-m` and `-c` remain higher priority and cannot be inferred by that static check.

Auto is intentionally not installed as a fifth static profile. It is the dynamic policy in the routing skill: classify each phase, select a native role, verify runtime metadata when exposed, and de-escalate after the phase. It cannot mutate the model of an already-running parent thread.

## Controlled runtime test

Start a persisted, read-only run with the selected profile. Ask it to create exactly two children using native `agent_type`, `fork_turns="none"`, and no explicit model/reasoning spawn arguments:

- `luna-researcher`: extract IDs and a currency from a small JSON fixture.
- `terra-implementer`: independently compute its count, signed sum, and largest item.

Wait for completion. Compare the child relationship and stored model/effort in the local runtime state with each rollout's `turn_context.payload.model` and `turn_context.payload.effort`. Also inspect the actual spawn arguments. A requested setting or an agent's self-report is not runtime proof.

The complete 0.153.4 test observed:

| Role | Actual runtime model | Actual effort | Result |
|---|---|---|---|
| Economy primary | `gpt-5.6-terra` | `medium` | Completed |
| Balanced primary | `gpt-5.6-sol` | `medium` | Completed |
| Quality primary | `gpt-5.6-sol` | `high` | Completed |
| Max primary | `gpt-6-astra` | `high` | Completed |
| `luna-researcher` | `gpt-5.6-luna` | `low` | Completed |
| `terra-explorer` | `gpt-5.6-terra` | `low` | Completed |
| `terra-implementer` | `gpt-5.6-terra` | `medium` | Completed |
| `sol-planner` | `gpt-5.6-sol` | `medium` | Completed |
| `sol-reviewer` | `gpt-5.6-sol` | `medium` | Completed |
| `sol-debugger` | `gpt-5.6-sol` | `high` | Completed |
| `astra-expert` | `gpt-6-astra` | `high` | Completed |

The full role test created exactly seven child threads through native `agent_type`. Spawn calls did not include model or reasoning overrides. Persisted thread metadata and every `turn_context` matched the selected role file, including the minimal explicit Astra escalation probe. Native role loading worked; no explicit-routing fallback was needed. Six sentinel tasks matched exactly. The planner returned the numeric fixture sequence instead of the requested fixed planning sentinel, but its runtime model/effort and completion were verified; this is a task-output mismatch rather than a routing mismatch.

An Auto probe used a Balanced parent, explicitly disclosed that it could not mutate that parent, classified a narrow read-only task, and selected `luna-researcher`. The child ran as Luna/Low and returned the expected result. No `omnicodex-auto.config.toml` was created.

Runtime state and rollout formats are internal and may change. The installed app-server can generate its own protocol schema. In this version, `app-server` rejects `--profile`; validate the named profile through `codex exec --strict-config -p omnicodex-balanced` instead. The app-server `skills/list` endpoint can independently confirm skill discovery.

## Checks and rollback

```sh
python3.12 -m unittest discover -s tests -v
git diff --check
```

CI validates declarative assets and checks whitespace against the changed commit range. No production application, build pipeline, network service, browser UI, or production deployment is added. Paid runtime smoke tests remain local and explicit. CI success alone does not prove model routing.

For rollback, remove only files introduced by this installation whose current hashes still match the install manifest. Restore backed-up files only if they were actually replaced. Preserve subsequent user edits and unrelated configuration. Since this procedure leaves the base `config.toml` unchanged, restoring it is unnecessary unless it was separately changed.

Official references: [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) and [configuration samples](https://developers.openai.com/codex/config-sample).

## Gemini Direct worker validation

Windows offline refactor validation on 2026-10-03 passed 244 unit tests, including
65 direct-provider/worker/mocked-live tests, 23 installer/setup tests, 114
routing/profile tests, and 42 retained scope/legacy-adapter tests. `compileall`,
manifest/example-pack validation, and `git diff --check` passed. Independent
review accepted the implementation after fixing privacy, parser, telemetry,
deadline-reader, and HTTP connection-lifecycle regressions. No real Gemini call
was made: this executor had no configured key. The project-specified
`npx @Codex-flow/cli@latest security scan` could not run because npm rejects that
package name and returned 404; the security regression suite and independent
review provide the available local evidence.

Credential and instruction scans are heuristic, so explicit scope approval,
correct classification, and premium source verification remain required. The
HTTP response reader refreshes the remaining deadline before each socket read;
OS DNS and connection/TLS setup retain platform blocking behavior and may exceed
an exact whole-operation deadline.

The worker calls Gemini Direct from a deterministic immutable capture. It does
not replace the root provider or write credentials/provider configuration to
disk. First verify offline prerequisites:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$worker = Join-Path $codexHome 'omnicodex\scripts\free_context_worker.py'
python $worker doctor
```

The report must show `native_status: "READY"` and
`free_context_offload: "READY"` or `"NOT CONFIGURED"`, along with
`gemini_direct`, the configured model, `key_configured`, and
`connectivity_verified: false`. READY means the local environment is configured;
it does not prove a network request or account access.

For a controlled Windows acceptance, set `GEMINI_API_KEY` in the current shell.
Optionally set `OMNICODEX_GEMINI_MODEL`; it defaults to `gemini-2.5-flash-lite`.
Then run the repository validation script, which sends a small EvidencePack case
and a roughly 45k-token synthetic case:

```powershell
python scripts/validate_gemini.py
```

It reports estimates separately from actual provider usage, which appears only
when Gemini returns usage metadata. The command may incur API billing; a model
name does not guarantee that the account has a free tier. The test uses only its
synthetic approved workspace and never reads unapproved files.

On probe failure, `provider_diagnostics` reports the HTTP status and recognized
API status/reason codes, or a fixed transport category such as `tls_error` or
`dns_error`. It never includes raw response messages, headers, error metadata,
exception text, or the key. Unknown diagnostic codes are omitted. Configuration
READY still does not mean connectivity has been verified.

For manual investigation, create a disposable workspace and request outside it:

```powershell
$case = Join-Path ([IO.Path]::GetTempPath()) ('omnicodex-live-' + [guid]::NewGuid())
$workspace = Join-Path $case 'workspace'
$artifacts = Join-Path $case 'artifacts'
New-Item -ItemType Directory -Path $workspace | Out-Null
1..5000 | ForEach-Object { "synthetic public evidence line $_" } |
  Set-Content -Encoding utf8 (Join-Path $workspace 'evidence.txt')
$request = @{
  schema_version = 1; task_kind = 'long_doc_digest';
  objective = 'Summarize the synthetic numbered evidence and cite exact lines.';
  approved_paths = @('evidence.txt'); data_classification = 'public';
  external_offload_approved = $true;
  metrics = @{ schema_version = 1; task_kind = 'long_doc_digest';
    estimated_chars = 160000; file_count = 1; diff_lines = 0;
    log_bytes = 0; search_hits = 1; data_classification = 'public';
    external_offload_approved = $true; independent_units = 1 }
} | ConvertTo-Json -Depth 4
$requestPath = Join-Path $case 'request.json'
[IO.File]::WriteAllText($requestPath, $request, [Text.UTF8Encoding]::new($false))
$before = (Get-FileHash (Join-Path $workspace 'evidence.txt')).Hash
$config = Join-Path $codexHome 'config.toml'
$configBefore = if (Test-Path $config) { (Get-FileHash $config).Hash } else { $null }
python $worker dry-run --workspace $workspace --request $requestPath --profile balanced
python $worker run --workspace $workspace --request $requestPath --profile balanced --artifacts $artifacts
$after = (Get-FileHash (Join-Path $workspace 'evidence.txt')).Hash
if ($before -ne $after) { throw 'workspace changed' }
$configAfter = if (Test-Path $config) { (Get-FileHash $config).Hash } else { $null }
if ($configBefore -ne $configAfter) { throw 'global Codex config changed' }
python (Join-Path $codexHome 'omnicodex\scripts\efficiency.py') validate-pack `
  --pack (Join-Path $artifacts 'evidence-pack.json')
Get-Content (Join-Path $artifacts 'receipt.json')
```

Accept the live test only if the dry run selected `free_context_worker`, the run
created a locally valid pack, source hashes match, evidence ranges resolve, and
the receipt reports one accepted Gemini Direct request. Confirm the pack is
compact and contains no full source. Confirm the receipt's combined
pack-plus-citations estimate retains at least a 20% estimated reduction from the
captured raw estimate. Record
requested and served provider/model only when direct provider metadata provides
them. Never print the environment key. The worker only captures the explicitly
approved scope, so the validation must not rely on access to any other workspace
file.
