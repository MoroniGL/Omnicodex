# Session profile switching (experimental)

OmniCodex can keep a saved profile for future chats and apply a different
routing policy inside one existing Codex conversation. This increment uses the
native Codex UserPromptSubmit hook for policy state only. It does not replace
the Codex TUI, intercept model traffic, or change the running parent model.

## Commands inside a Codex conversation

These are ordinary user messages, not slash commands:

~~~text
omni balanced
omni profile quality
omni use economy
omni auto
omni reset
omni status
omni save max
~~~

Behavior:

- omni PROFILE, omni profile PROFILE, and omni use PROFILE set a temporary
  override for the current Codex session only.
- omni reset removes the temporary override and returns subsequent turns to the
  saved persistent profile.
- omni status reports the effective session policy, the saved policy, the
  active model reported to the hook, and the selected profile's recommended
  parent.
- omni save PROFILE applies the profile to the current session and persistently
  saves it for future chats inside the already trusted UserPromptSubmit hook.
  The exact whole-message control command is the user's explicit authorization.
  Persistence reuses the installed OmniCodex defaults module directly, including
  its normal backup, lock, conflict, and rollback protections. It does not ask the
  agent tool shell to locate or execute Python, because that shell can be sandboxed
  away from the host interpreter even while the trusted hook is running normally.
  Success is reported only after the saved preference is re-read and verified.

The parser recognizes only a whole prompt matching one of these control forms.
A mention inside prose or a code block remains ordinary task content.

## Parent model changes

Codex already provides the native /model selector. OmniCodex does not duplicate
or fake that control.

A profile override becomes effective at a prompt boundary even when the current
parent differs from the profile recommendation. The hook receives the active
model slug and reports whether it matches the recommendation. The current hook
schema does not provide a documented reasoning-effort field, so reasoning
effort remains unverified by the hook.

Example:

~~~text
omni max
~~~

If the current parent is Sol, the Max policy is applied to later turns and the
model is told that Max recommends Astra High. Use /model to select Astra/High
inside the same conversation. Do not start a new chat merely to change the
parent.

## Install the session-control hook

The recommended full setup now includes this hook automatically:

~~~powershell
python .\scripts\setup.py
python .\scripts\setup.py --apply
~~~

For hook-only repair or inspection, `scripts/session_setup.py` remains available
with the same preview-first `--apply` behavior.

The hook phase writes only:

- CODEX_HOME/omnicodex/session_switch.py
- CODEX_HOME/hooks.json, merged with unrelated existing hooks

It does not modify config.toml, AGENTS.md, permissions, providers, worker
definitions, or credentials. Backups are stored under
CODEX_HOME/omnicodex/session-switch-backups/.

Codex requires review and trust for non-managed hooks. Temporary switching does
not become active until the installed UserPromptSubmit hook has been reviewed
and trusted. Do not bypass hook trust merely to make a test pass.

## State and privacy

Session state lives under CODEX_HOME/omnicodex/session-overrides/. The filename
is a SHA-256 of the Codex session_id. State records only the selected profile
and an optional pending persistence request. It does not store the prompt, raw
session ID, transcript, credentials, code, or project files. A failed persistent
save leaves the temporary profile active and the old saved default untouched;
the agent is explicitly told not to retry persistence through its sandbox shell.

The hook performs no network requests and does not read the transcript. When no
temporary override exists and the prompt is not an Omni control message, it
emits no additional context; the saved global policy continues to come from the
already validated persistent AGENTS.md mechanism.

## Turn boundaries and failure behavior

The hook runs on UserPromptSubmit. It cannot rewrite an already running turn.
A profile change therefore applies at the next prompt/turn boundary and then to
subsequent turns in the same session.

This hook is routing UX, not a security boundary. On a hook error it fails open
to the already loaded saved policy and emits a short warning without echoing
prompt or configuration contents. It never changes approvals, sandbox settings,
permissions, providers, or worker definitions.

## Windows acceptance

The maintainer exercised the persistent-default and same-session flows on Codex
CLI 0.160.0 for Windows. The supported acceptance sequence remains: install,
review/trust the hook, use `omni quality`, inspect `omni status`, change the
parent only through `/model`, verify the override survives a normal turn, reset,
and verify a new chat returns to the saved policy. `omni save PROFILE` is
accepted only after the preferences write is re-read and verified.

Do not use model self-report alone to prove the served parent. Use runtime UI or
metadata where available. Other Codex UI surfaces may cache configuration or
differ in hook support and should be validated independently.

## Current boundaries

- No in-flight parent-model mutation; /model remains the supported control.
- Gemini Direct offload is a separate optional context path; the session hook
  only reports local configuration status and never performs provider calls.
- No automatic parent-provider change or quota fallback.
- Jev and Laya remain separately opt-in.
- No claim that every Codex UI supports identical hook behavior until tested.
