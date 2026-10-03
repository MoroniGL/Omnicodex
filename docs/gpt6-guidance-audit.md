# GPT-6 guidance audit for OmniCodex

Reviewed 2026-10-03 against OpenAI guidance published through 2026-10-02.

## Adopted now

- Progressive disclosure: keep the root skill and its description short; load
  routing and token-offload references only when relevant.
- Context efficiency with evidence: narrow unnecessary context while preserving
  source references needed for acceptance.
- Clear completion and decision boundaries instead of rigid, always-on recipes.
- Parallel work only for independent units; serialize ordered work and shared
  mutable resources.
- Usage-oriented observability: distinguish root/worker usage and estimates from
  verified billing.

Primary sources:
- https://openai.com/pt-BR/index/practical-guide-building-gpt-6/
- https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra
- https://developers.openai.com/api/docs/guides/responses-multi-agent
- https://developers.openai.com/api/docs/guides/agents-api/observability

## Evaluate before changing defaults

GPT-6.1 Sol, released 2026-09-29, is a candidate for Balanced/Quality orchestration.
GPT-6 Luna is a candidate for bounded routine OpenAI work. Do not replace the
Windows-validated profile targets until representative benchmarks and actual Codex
runtime/account availability confirm the migration.

Sources:
- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/changelog

GPT-6 API reasoning configuration updates can preserve a cached prefix, but the
local Codex product currently remains authoritative for the actual model/reasoning
selection in a running thread. OmniCodex policy must not claim a runtime switch it
cannot verify.

Sources:
- https://developers.openai.com/api/docs/guides/reasoning
- https://developers.openai.com/api/docs/guides/prompt-caching

## Deferred

Agents API cloud execution, mid-turn steering, and async tool calling may help a
future hosted mode. They are not required for the first local FreeLLMAPI context
worker. Jev, quota fallback, and OmniClaude are not OmniCodex completion
dependencies.

## Packaging direction

Current OpenAI plugin architecture can package skills, MCP configuration, and
lifecycle hooks. After local behavior is stable, package OmniCodex as a plugin
while preserving hook trust review and local script availability.

Sources:
- https://developers.openai.com/plugins/concepts/plugins
- https://developers.openai.com/plugins/build/plugins
