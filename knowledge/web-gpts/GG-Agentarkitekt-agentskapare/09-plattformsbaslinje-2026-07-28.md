# Plattformsbaslinje 2026-07-28

## Varning

Denna information är versionskänslig. Verifiera aktuell officiell dokumentation före varje skarp lösning.

## Anpassade GPT:er

OpenAI beskriver GPT:er som versioner av ChatGPT för särskilda ändamål. De kan kombinera instruktioner, Knowledge och valda capabilities. Appar och Actions kan ansluta externa data eller operationer beroende på plan och arbetsyta.

Lämpligt för:
- avgränsat samtals- och kunskapsstöd;
- dokumentanalys;
- prototyper;
- interna specialister utan komplex egen runtime.

## GPT Actions

Actions kopplar en GPT till externa API:er via schema och autentisering. Bedöm alltid:
- operationer;
- data;
- autentisering;
- workspace-regler;
- externa effekter;
- godkännanden;
- loggning.

## ChatGPT Workspace Agents

OpenAI dokumenterar Workspace Agents för Business och Enterprise som agenter för upprepbara arbetsflöden, anslutna appar och schemalagda eller externa triggers. Tillgänglighet och kontroller beror på arbetsyta, utrullning och administratör.

Lämpligt när:
- verksamheten vill bygga och förvalta återkommande arbetsflöden i ChatGPT;
- appar, workspace-styrning och delning är centrala;
- lösningen inte behöver helt egen applikationsruntime.

## Responses API

Lämpligt när utvecklaren vill äga modellloop, verktygsrouting, branching, state och applikationslogik direkt.

## Agents SDK

OpenAI beskriver Agents SDK för avgränsade konversations- eller transaktionsflöden med definierade verktyg och återkommande orkestrering. SDK:n stöder bland annat:
- agentloop;
- handoffs;
- agents-as-tools;
- guardrails;
- mänskliga godkännanden;
- tillstånd;
- tracing.

## Multiagent

Använd fleragentmönster när specialistägarskap eller parallell delegering ger tydlig nytta. Kontrollera funktioners mognadsstatus och modellkrav innan aktivering.

## MCP, appar och anslutningar

De kan ge verktyg och kontext, men kräver:
- tillitsmodell;
- datagräns;
- verktygsgranskning;
- autentisering;
- workspace-kontroller;
- godkännanderegler.

## Agent Builder

Den officiella dokumentationen anger att Agent Builder avvecklas och planeras stänga 2026-11-30.

Konsekvens:
- välj det inte som standard för nya långsiktiga lösningar;
- befintliga flöden bör ha en migrationsplan;
- utvärdera Workspace Agents eller Agents SDK;
- exporterad kod eller workflow måste testas, eftersom migrering inte garanterar identiskt beteende.

## Arkitekturregel

Välj plattform efter:
- användargränssnitt;
- runtime-ägarskap;
- systemintegration;
- behörighet;
- state;
- observability;
- deployment;
- kostnad;
- förvaltning.

Undvik att välja plattform enbart för att den är nyast eller mest agentisk.
