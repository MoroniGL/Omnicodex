# Persistent OmniCodex defaults (experimental)

Install once, choose once, start subsequent local Codex chats without manually
mentioning OmniCodex. This implements **saved defaults and startup guidance**,
not a replacement harness or a native model dropdown. Optional Gemini Direct
context offload remains a separate bounded path controlled by the routing skill.

## Behavior

- A new persistent installation uses **Auto** and preserves the current parent
  model. Auto is a policy, not a fifth fixed model recommendation.
- Choosing Economy, Balanced, Quality or Max uses the installed profile's model
  and reasoning recommendation; no new model IDs are hardcoded by this tool.
- An explicit model/effort pin is retained across later profile selections unless
  the user chooses `--recommended`.
- Updates without a profile keep the existing choice, including a disabled state.
- Temporary session instructions or an explicit `codex --profile ...` do not
  overwrite the saved preference. The native `/model` menu is NOT wired to this
  preference store; editing model defaults externally is reported as a conflict.
- Disabling removes Omni's managed startup block and restores the previously
  captured model defaults, provided those managed values were not edited outside
  the tool. User changes outside the owned block/model keys are preserved.

## Installation / update

Python 3.11+; no new dependency, login, API call or model download. Review first:

```powershell
python .\scripts\setup.py
```

This command is a preview. To install assets, persist startup guidance, and
configure the same-session UserPromptSubmit hook:

```powershell
python .\scripts\setup.py --apply
```

Codex may require one explicit trust review for the local hook. Restart clients
that cache `CODEX_HOME`, guidance, or hook configuration.

An explicit initial choice can be made with `--profile balanced`. Updating changed
assets still requires `--replace-existing` after reviewing conflicts. The old
`scripts/install.py` remains an **asset-only** installer with unchanged behavior;
users of that entry point have not opted into global preferences.

This is local configuration for the **same CODEX_HOME**. It does not activate
Omni in the ChatGPT website, another account, another OS user or another machine.
The CLI, IDE and desktop client must actually load that home and the relevant
startup instructions. Restart already-running clients after installation or a
persistent change when they cache config/guidance. Do not claim runtime coverage
for an interface that has not been tested.

## Remember or change a profile

While in the checkout:

```powershell
python .\scripts\defaults.py set balanced          # preview
python .\scripts\defaults.py set balanced --apply  # persist
python .\scripts\defaults.py set quality --apply
python .\scripts\defaults.py set auto --recommended --apply
python .\scripts\defaults.py status
python .\scripts\defaults.py disable --apply
python .\scripts\defaults.py enable --apply
```

For a personal model selection, supply **both** `--model` and `--effort`. Values
are syntax-checked only, not validated against account access or server behavior.
Selecting another profile retains that pin. `--recommended` explicitly restores
the profile recommendation. A recommended native model is refused when the user
config selects a non-OpenAI provider; credentials/providers are not changed.

The standalone preference tool is also installed under
`$CODEX_HOME/omnicodex/defaults.py` (normally `~/.codex/omnicodex/defaults.py`), so
preferences remain editable from another working directory. Use `--codex-home`
for an isolated test; never run a validation against your real home by accident.

Persistent settings are defaults for **future sessions**. They do not change a
running parent model or existing workers. Use the client's supported model
selection for the next turn, or restart when needed. A natural-language request
for a permanent preference still requires a successful preferences-tool call
with normal approval; a model saying it saved the profile is not evidence.

## Implementation

1. `preferences.json` records enabled state, policy, optional model pin, the
   managed block and narrowly owned model keys.
2. A short marked block is prefixed to the active global guidance file. Existing
   non-empty `AGENTS.override.md` is respected; otherwise `AGENTS.md` is used.
   Other guidance is not replaced. A later override shadowing that file is
   reported, not silently edited.
3. For a fixed profile/pin, only the user-level root `model` and
   `model_reasoning_effort` values are edited. All other parsed TOML values must
   remain equal. Unusual multiline model assignments are refused rather than
   guessed. No legacy `profile = ...` key or `[profiles.*]` table is generated.
4. Writes require `--apply`, take an exclusive local lock, keep private backups
   and a journal, use per-file atomic replacement and compare snapshots before
   writing. On an ordinary exception the tool attempts conditional rollback.
5. Status distinguishes configured files from actual execution:
   `runtime_verified` and model availability remain unverified.

No permissions, trust settings, network policy, provider keys, model catalogs,
or worker definitions are modified. The integrated setup adds only OmniCodex's
UserPromptSubmit hook and preserves unrelated hooks. Jev and Laya remain
separately opt-in. Gemini Direct remains optional and is used only after the
scope/privacy gate accepts external offload; Auto never turns it into quota
fallback. The startup text adds a small amount of context; no billing savings or
unconditional instruction compliance is claimed.

## Recovery and limits

The asset-installation phase remains the existing non-transactional installer.
Its success followed by a preference failure is reported as two separate phases;
do not present it as fully installed and activated. This increment does not fix
asset-batch rollback.

Preference backups live under `CODEX_HOME/omnicodex/preferences-backups/`. They
may contain sensitive pre-existing user config: keep them local, never attach
or commit them without review. Journal target paths and before/after hashes aid
recovery. A hard process termination may leave a lock and partial state. Do not
delete the lock or restore whole backups blindly: compare each target with the
journal, preserve intervening user edits, and review recovery explicitly.

Known symlinks and Windows reparse points are refused. The checks and snapshot
comparisons are not a filesystem security sandbox or a guarantee against races.
Per-file atomic replacement is not atomic visibility across multiple files.
POSIX permissions are restrictive; Windows security also depends on inherited
NTFS ACLs. No administrator elevation is requested.

## Validation checklist (Windows)

First test in temporary homes, with unrelated user settings and guidance. Confirm
Auto, a saved fixed profile, a manual pin, restart persistence and disable/restore.
Then, after explicit approval for real installation, open two new local Codex
sessions without mentioning OmniCodex. Verify loaded guidance and observed model
metadata where available; a self-report alone does not prove the served model.
Test UI-specific config caching and explicit session overrides separately.

Unit tests use synthetic assets, no paid models or real global settings. Native
model selection remains Codex-owned; Gemini Direct has a separate explicit live
validator and is not called by CI.

## Primary references checked 2026-10-02

- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/config-advanced
- https://developers.openai.com/codex/config-reference

The advanced configuration documentation states that Codex 0.134.0+ uses separate
profile files and no longer supports the top-level default `profile` selector.
Global guidance is read when constructing a session's instruction chain. These
facts determine this implementation; they do not certify a particular installed
client build.
