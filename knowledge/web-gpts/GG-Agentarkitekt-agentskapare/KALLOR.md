# Källor

**Verifieringsdatum:** 2026-07-28  
**Princip:** Denna fil dokumenterar versionskänslig plattformsinformation. Kontrollera källorna på nytt när en lösning ska implementeras.

## GPTs in ChatGPT

- Organisation: OpenAI
- Titel: GPTs in ChatGPT
- URL: https://help.openai.com/en/articles/8554407-create-a-custom-gpt
- Stödjer: att anpassade GPT:er kombinerar instruktioner, Knowledge och valda capabilities.
- Kommentar: tillgänglighet och delning kan bero på plan och arbetsyta.

## Creating and editing GPTs

- Organisation: OpenAI
- Titel: Creating and editing GPTs
- URL: https://help.openai.com/en/articles/8843948-knowledge-in-gpts
- Stödjer: konfigurering, testning, Knowledge, capabilities, appar, Actions och versionshistorik.

## Configuring actions in GPTs

- Organisation: OpenAI
- Titel: Configuring actions in GPTs
- URL: https://help.openai.com/en/articles/9442513
- Stödjer: externa API:er, autentisering, schema och workspace-begränsningar.
- Arkitekturpåverkan: Actions ska bedömas separat från samtals- och Knowledge-funktioner.

## ChatGPT Workspace Agents

- Organisation: OpenAI
- Titel: ChatGPT Workspace Agents for Enterprise and Business
- URL: https://help.openai.com/en/articles/20001143
- Stödjer: agenter för upprepbara arbetsflöden i Business- och Enterprise-arbetsytor.
- Kommentar: plan, utrullning och workspace-kontroller måste verifieras.

## Workspace Agents API

- Organisation: OpenAI
- Titel: Trigger workspace agent runs
- URL: https://developers.openai.com/workspace-agents/trigger-runs
- Stödjer: att publicerade workspace agents kan triggas från serverbaserade system och automationer.

## Apps och godkännanden

- Organisation: OpenAI
- Titel: Apps in ChatGPT
- URL: https://help.openai.com/en/articles/11487775-connectors-in-chatgpt
- Stödjer: appåtgärder, read kontra action, användargodkännanden och workspace-kontroller.
- Arkitekturpåverkan: risk och godkännande ska definieras per operation.

## Building agents

- Organisation: OpenAI
- Titel: Building agents
- URL: https://developers.openai.com/tracks/building-agents
- Stödjer: skillnaden mellan enkla verktygsanvändande agenter och komplexa samverkande agentsystem.

## Praktisk agentguide

- Organisation: OpenAI
- Titel: A practical guide to building AI agents
- URL: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/
- Stödjer: val av användningsfall, agentlogik, orkestreringsmönster och säker drift.

## Responses API och Agents SDK

- Organisation: OpenAI
- Titel: Agents SDK
- URL: https://developers.openai.com/api/docs/guides/agents
- Stödjer: verktyg, handoffs, guardrails, mänsklig granskning, tillstånd, tracing och jämförelsen mellan Responses API och Agents SDK.
- Arkitekturpåverkan: Responses API passar när applikationen äger loopen; Agents SDK när SDK:n ska hantera agentloop och återkommande orkestrering.

## Orkestrering och handoffs

- Organisation: OpenAI
- Titel: Orchestration and handoffs
- URL: https://developers.openai.com/api/docs/guides/agents/orchestration
- Stödjer: handoffs kontra agents-as-tools och tydligt ägarskap för användarsvaret.

## Guardrails och mänsklig granskning

- Organisation: OpenAI
- Titel: Guardrails and human review
- URL: https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- Stödjer: validering, paus och återupptagning vid mänskligt godkännande.

## Observability och tracing

- Organisation: OpenAI
- Titel: Integrations and observability
- URL: https://developers.openai.com/api/docs/guides/agents/integrations-observability
- Stödjer: strukturerad tracing av modell-, verktygs-, handoff- och guardrail-händelser.

## Agent Builder — avveckling

- Organisation: OpenAI
- Titel: Agent Builder
- URL: https://developers.openai.com/api/docs/guides/agent-builder
- Verifierat: OpenAI anger att Agent Builder avvecklas och planeras stänga 2026-11-30.
- Arkitekturpåverkan: ska inte vara standardval för nya långsiktiga implementationer.

## Migrering från Agent Builder

- Organisation: OpenAI
- Titel: Migrate from Agent Builder
- URL: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder
- Stödjer: export och fortsatt arbete i Workspace Agents eller Agents SDK.
