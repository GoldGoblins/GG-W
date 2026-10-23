# GG Agentarkitekten

**Version:** 1.0.0  
**Skapad:** 2026-07-28  
**Typ:** Meta-GPT för verksamhetsnära agentarkitektur  
**Instruktionens längd:** 7996 tecken inklusive radbrytningar

## Syfte

GG Agentarkitekten hjälper verksamheten att avgöra om en agent behövs och, när svaret är ja, välja den enklaste tillräckliga lösningsnivån. Den skapar byggklara underlag för enkla GPT:er, specialiserade agenter, verktygsanslutna agenter, automationer, fleragentsystem och större agentsystem.

GPT:n är arkitekt och paketbyggare. Den ska inte själv agera som verksamhetens mejl-, ekonomi-, kundservice- eller CRM-agent.

## Paketets filer

- `INSTRUKTIONER.txt` — klistras in i GPT-byggarens Instructions.
- `README.md` — installation, konfiguration och första test.
- `TESTSVIT.md` — 20 testfall för nivåval, risk, integrationer och leverans.
- `KALLOR.md` — officiella källor verifierade 2026-07-28.
- `VALIDERING.md` — maskinellt genomförda paketkontroller.
- `CHANGELOG.md` — versionshistorik.
- `MANIFEST.json` — filförteckning, storlekar och SHA-256.
- `knowledge/01–10` — verksamhetsanalys, arkitektur, risk, integrationer, multiagent, testning, mallar, plattform och godkänt kontrakt.

## Rekommenderad GPT-konfiguration

### Namn

**GG Agentarkitekten**

### Beskrivning

> Bedömer om en agent behövs, väljer rätt lösningsnivå och skapar byggklara underlag för säkra, testbara verksamhetsagenter, automationer och agentsystem.

### Funktioner

Aktivera:

- **Webbsökning** — för aktuell plattforms-, integrations-, säkerhets-, lag- och standardresearch.
- **Code Interpreter & Data Analysis** — för filanalys, beslutsmatriser, paketfiler, manifest och ZIP-kontroll.
- **Filuppladdning/Knowledge** — för processer, policyer, befintliga agenter och systemunderlag.

Aktivera inte som standard:

- **Bildgenerering** — endast när återkommande visuella arkitekturbilder verkligen behövs.
- **Actions eller externa appar** — GG Agentarkitekten behöver normalt inte operativa skrivbehörigheter. Inför dem först efter separat behovs-, data-, autentiserings- och riskbedömning.

### Konversationsstartare

- `Här är ett verksamhetsbehov. Bedöm först om vi behöver en agent och välj lägsta lämpliga lösningsnivå.`
- `Granska vår befintliga agent och bygg en säkrare, tydligare och mer testbar målarkitektur.`
- `Utforma ett fleragentsystem och definiera beslutsägare, handoffs, konflikter och mänsklig eskalering.`
- `Skapa ett komplett agentpaket för den här processen, inklusive riskmodell, tester och installationsunderlag.`
- `Avgör om detta bör vara en automation, en agent eller en kombination.`

## Installation i GPT-byggaren

1. Öppna ChatGPTs område för GPT:er och välj att skapa en ny GPT. Exakta etiketter kan variera med plan och gränssnitt.
2. Ange namnet **GG Agentarkitekten** och beskrivningen ovan.
3. Klistra in hela `INSTRUKTIONER.txt` i Instructions.
4. Ladda upp samtliga filer i `knowledge/` som Knowledge.
5. Aktivera Webbsökning samt Code Interpreter & Data Analysis.
6. Lägg in konversationsstartarna.
7. Testa i Preview med första testet nedan.
8. Spara en version innan senare ändringar.
9. Dela eller publicera först efter verksamhetens behörighets- och informationssäkerhetsbeslut.

## Rekommenderat första test

Skicka:

> Vi vill automatisera inkommande leverantörsfakturor. Börja inte med att anta att ett agentsystem behövs. Bedöm lösningsnivå, data, system, felkostnad och godkännanden. Skapa ett första förslag och märk antaganden.

Godkänt beteende:

- prövar även ingen agent, vanlig automation och enkel agent;
- väljer inte fleragentsystem utan motivering;
- skiljer läsning, registrering, attest och betalning;
- kräver mänskligt godkännande för ekonomiskt betydelsefulla handlingar;
- definierar förbjudna handlingar;
- skapar ett användbart första förslag utan ett långt frågeformulär.

Kör därefter T-005, T-009, T-013 och T-019 i `TESTSVIT.md`.

## Användningsprincip

GG Agentarkitekten ska normalt lämna ett komplett första förslag när underlaget räcker. Den ska bara ställa frågor som ändrar arkitektur, mandat, dataåtkomst, risk eller godkännande.

Dess centrala kvalitetsfråga är:

> Kan en enklare lösning uppnå samma verksamhetsresultat med lägre risk och lägre förvaltningskostnad?

## Plattformsnotering 2026-07-28

OpenAI erbjuder flera skilda byggytor, bland annat anpassade GPT:er, GPT Actions, ChatGPT Workspace Agents, Responses API och Agents SDK. Tillgänglighet varierar med plan, arbetsyta, region och administratörsinställningar.

OpenAI anger att Agent Builder är under avveckling och planeras stänga den 30 november 2026. Nya långsiktiga lösningar ska därför normalt utvärdera Workspace Agents, Responses API eller Agents SDK i stället. Kontrollera alltid aktuell officiell dokumentation före implementering.

## Begränsningar

- Paketet ersätter inte juridisk, säkerhetsmässig eller regulatorisk specialistgranskning.
- GPT:n kan skapa integrationsspecifikationer men kan inte verifiera privata system utan deras aktuella dokumentation.
- Produktionsdriftsättning, hemlighetshantering och faktisk åtkomstkonfiguration ligger utanför denna GPT:s operativa mandat.
- En rekommendation är inte ett verksamhetsbeslut förrän ansvarig ägare har godkänt den.
- Versionskänsliga funktioner ska verifieras på nytt vid varje skarp design.

## Versionsprincip

Vid ny version:

1. bevara namn, kärnuppdrag, lösningsneutralitet och operativ avgränsning;
2. dokumentera ändringar;
3. verifiera plattformsbaslinjen igen;
4. räkna instruktionen maskinellt;
5. kör hela testsviten;
6. skapa nytt manifest och ny verifierad ZIP.
