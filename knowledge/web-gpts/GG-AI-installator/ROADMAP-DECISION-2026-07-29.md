# Roadmapbeslut — CP5 och CP6 före CP4

- **Besluts-ID:** `GG-ROADMAP-2026-07-29-CP5-CP6-CP4-v1.0`
- **Datum:** 2026-07-29
- **Beslutsägare:** användaren
- **Status:** aktivt användarbeslut
- **Utgångspunkt:** CP1, CP2 och CP3 verifierade som klara

## Beslut

Den fortsatta ordningen ändras från numerisk CP4 → CP5 → CP6 till:

1. CP5A: AI-kapacitetsinventering;
2. CP5B: lokal runtime och modell;
3. CP5C: GG Code Gate och Debug Runner;
4. CP6A: agentkärna i syntetisk sandbox;
5. CP6B: lokal multiagent-orchestrator;
6. CP4: agentassisterad lokal WordPress/WooCommerce-klon;
7. CP6C: agent kopplad till lokal WordPress;
8. gradvis automation.

## Skäl

- användaren vill ha lokal AI och agentverktyg innan WordPress-klonen;
- kod ska kunna felsökas och provköras innan terminal- eller WordPress-körning;
- agenten ska kunna hjälpa till med CP4:s lokala script, sanering, containerdefinitioner och tester;
- produktionstillgång ska fortfarande vara användarstyrd och separat godkänd.

## Code Gate-krav

Före agentens första skrivande koduppgift ska det finnas en fungerande lokal kodgrind som:

- syntax- och statiskt analyserar;
- kör fixtures och negativa testfall;
- exekverar i disponibel rootless sandbox utan nätverk;
- skapar reproducerbar rapport;
- stoppar osäker eller ofullständigt testad kod.

Kodgrinden minskar risk men ger ingen absolut garanti i en annan målmiljö.

## Web-GPT-beslut

GG AI istallatör, GG Idékompassen, GG Metaarkitekten och GG Webmaster kan använda samma versionsmärkta kunskapskärna och strukturerade handoffs.

De ska inte beskrivas som autonomt sammankopplade enbart för att de är separata GPT:er. Verklig samordning byggs som lokal eller API-baserad orchestrator med explicit verktygs- och behörighetsmodell.

## WordPress/one.com

Användaren har uppgett att WordPress/WooCommerce finns på one.com och hanteras där.

Detta är användaruppgift, inte tekniskt inventerad status.

Agenten får inte självständigt:

- logga in;
- hämta backup;
- läsa credentials;
- använda kunddata;
- aktivera Code Snippets;
- deploya.

Användaren styr produktionstillgång och godkänner varje röd plan.

## Påverkan på historik

`SYSTEMSTATUS-CP3` och CP3-kunskapsfilen ändras inte. Deras tidigare “nästa steg CP4.1” var korrekt vid checkpointtiden. Detta beslut supersederar endast framtida roadmap.

## Genomförandestatus — verifierad 2026-08-07

Det ursprungliga roadmapbeslutet är fortsatt aktivt och har nu genomförts till och med CP6A:

- CP5A: verifierad klar;
- CP5B: verifierad klar i 4096-scope;
- CP5C: verifierad och publicerad som `PASS_PUBLISHED`;
- CP6A: build `PASS`;
- CP6A independent candidate audit: `PASS`;
- CP6A lokal promotion: `PASS`, fast-forward only;
- aktuell lokal `main`: `1144492f17df1c749f734175c6a1e4742ff95a41`;
- push/publicering: inte genomförd;
- CP6B scope discovery: `PASS_READ_ONLY`;
- CP6B contract inventory: `PASS_READ_ONLY`;
- CP6B build: inte påbörjad;
- CP4 och CP6C: inte påbörjade.

Historisk publicerad CP5C-commit:

`9cee2ad703cd516fc16746d8ad571ac30e6c0d3f`

Aktuell lokal `main` efter CP6A-promotion:

`1144492f17df1c749f734175c6a1e4742ff95a41`

Nästa steg är en separat namngiven CP6B-byggplan.

## Kompletterande användarbeslut — GG-team

För CP6A–CP6B gäller:

1. GG Idékompassen 2.0 är obligatorisk första mål- och nyttokontroll.
2. GG Metaarkitekten omvandlar godkänd riktning till systemarkitektur.
3. GG Agentarkitekten ansvarar för agentroller, verktyg, minne och handoffs.
4. GG AI istallatör ansvarar för Fedora, runtime, sandbox och Code Gate.
5. GG Webmaster ansvarar för WordPress, WooCommerce och PHP.
6. GG Reviewer ska vara oberoende av kodskaparen.
7. Roller delar versionsmärkt kunskap och strukturerade handoffs.
8. Ingen roll får utöka sina egna rättigheter.
9. Verklig autonom samordning kräver en uttryckligen byggd lokal eller API-baserad orchestrator.
