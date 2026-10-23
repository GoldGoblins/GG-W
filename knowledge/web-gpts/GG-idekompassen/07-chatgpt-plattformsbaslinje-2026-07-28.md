# ChatGPT-plattformsbaslinje — 2026-07-28

## Syfte

Den här filen beskriver den verifierade plattformsbas som Idékompassen 2.0 byggdes för. Informationen är versionskänslig och ska kontrolleras på nytt när funktioner, gränser eller installation påverkar ett framtida beslut.

## Anpassade GPT:er

OpenAI beskriver GPT:er som versioner av ChatGPT som konfigurerats för ett särskilt ändamål. En GPT kan kombinera:

- instruktioner;
- Knowledge;
- valda capabilities;
- i vissa fall appar eller Actions;
- delning och versionshantering beroende på plan och arbetsyta.

Källa:
https://help.openai.com/en/articles/8554407-create-a-custom-gpt

## Instructions och Knowledge

- Instructions styr beteende, arbetsflöde och beslut.
- Knowledge ger källmaterial som GPT:n kan hämta från.
- Kritiska regler ska därför finnas i Instructions, inte enbart i Knowledge.

Vid verifieringen angav OpenAI upp till 20 Knowledge-filer och upp till 512 MB per fil. Filtyper kan bero på modell och aktiverade funktioner.

Källa:
https://help.openai.com/en/articles/9358033-key-guidelines-for-writing-instructions-for-custom-gpts

## Webbsökning

Webbsökning används för aktuell eller realtidsnära information och källförsedda svar. Idékompassen behöver den för researchgrinden.

Källor:
https://help.openai.com/en/articles/9260256-chatgpt-capabilities-overview  
https://help.openai.com/en/articles/9237897-chatgpt-search

Tillgänglighet och kontroller kan bero på plan, arbetsyta och administratörsinställningar.

## Code Interpreter & Data Analysis

Idékompassen behöver funktionen för att skapa och returnera nedladdningsbara filer. OpenAI rekommenderar att den kontrolleras när en anpassad GPT inte kan generera eller lämna filer.

Källa:
https://help.openai.com/en/articles/11325361-why-cant-i-download-files-generated-by-my-custom-gpt

## Rekommenderad konfiguration

Aktivera:

- Webbsökning.
- Code Interpreter & Data Analysis.
- Filuppladdning/Knowledge.

Aktivera endast vid konkret behov:

- Bildgenerering.
- Actions.
- Appar eller andra anslutningar.

## Versionsregel

När paketet uppdateras:

1. verifiera officiell OpenAI-dokumentation igen;
2. notera verifieringsdatum;
3. skilj generell funktion från plan- eller arbetsyteberoende funktion;
4. undvik att hårdkoda modellnamn;
5. uppdatera `KALLOR.md`;
6. testa filskapande i Preview.
