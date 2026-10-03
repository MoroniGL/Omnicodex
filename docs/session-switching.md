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

## Install the experimental hook

Preview:

~~~powershell
python .\scripts\session_setup.py
~~~

Apply:

~~~powershell
python .\scripts\session_setup.py --apply
~~~

The installer writes only:

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

## Windows acceptance plan

Target environment: Codex CLI 0.160.0 on the Windows machine already used to
validate persistent defaults.

1. Run the new offline tests and session_setup.py preview.
2. Apply session_setup.py and review/trust the hook when Codex asks.
3. Start Codex with codex.cmd --no-daemon on this machine.
4. With saved Balanced active, send omni quality.
5. Send omni status and confirm session policy Quality while saved policy stays
   Balanced.
6. Use /model to select the recommended Sol/High when needed.
7. Send another normal prompt and confirm Quality remains effective.
8. Send omni reset and confirm the session returns to saved Balanced.
9. Start a new chat and confirm it starts Balanced, not the temporary Quality
   override.
10. Test omni save quality separately and confirm persistence only after the
    defaults tool succeeds.

Do not use model self-report alone to prove the served parent. Use the TUI footer
and /status where available.

## Current boundaries

- No in-flight parent-model mutation; /model remains the supported control.
- No FreeLLMAPI, Jev, Laya, provider, or quota-fallback activation.
- No automatic provider change.
- No claim that every Codex UI supports the same hook behavior until tested.
- No merge or release until Windows runtime acceptance passes.
