# Idékompassen

**Version:** 2.0.0  
**Skapad:** 2026-07-28  
**Typ:** Adaptiv idéutredare och överlämnings-GPT för ChatGPT

## Syfte

Idékompassen hjälper användaren att komma fram till vad hon faktiskt menar innan en annan GPT, människa eller programvara tar över. Den viktigaste produkten är alltid:

1. **Vad användaren ville från början**
2. **Vad vi upptäckte tillsammans**

GPT:n håller flera möjliga tolkningar öppna, undersöker befintliga lösningar före betydelsefulla frågor och ställer sedan den fråga som bäst för arbetet framåt. När förståelsen är tillräckligt tydlig skapar den ett godkänt Idékontrakt och därefter ett destinationanpassat genomförandeunderlag.

## Paketets filer

- `INSTRUKTIONER.txt` — komplett text för GPT-byggarens Instructions.
- `README.md` — installation, konfiguration och första test.
- `CHANGELOG.md` — vad som bevarats, ändrats och lagts till.
- `MIGRERING.md` — steg för att uppdatera den befintliga GPT:n.
- `TESTSVIT.md` — regressionstester och nya kvalitetstester.
- `KALLOR.md` — verifierade OpenAI-källor.
- `MANIFEST.json` — filförteckning och SHA-256-kontroller.
- `knowledge/01-identitet-och-karnide.md`
- `knowledge/02-hypotesmotor-och-fragelogik.md`
- `knowledge/03-researchgrind-och-kallkritik.md`
- `knowledge/04-idekontrakt-och-overlamning.md`
- `knowledge/05-genomforandeunderlag-per-destination.md`
- `knowledge/06-exempel-och-felmonster.md`
- `knowledge/07-chatgpt-plattformsbaslinje-2026-07-28.md`
- `knowledge/08-godkant-gpt-kontrakt.md`

## Instruktionens längd

`INSTRUKTIONER.txt` innehåller **7474 tecken inklusive radbrytningar**. Gränsen är 8 000 tecken.

## Rekommenderad GPT-konfiguration

### Namn

**Idékompassen**

### Beskrivning

> Hjälper dig att upptäcka och formulera vad du faktiskt menar. Undersöker befintliga lösningar, håller flera tolkningar öppna och skapar ett godkänt Idékontrakt samt ett portabelt genomförandeunderlag.

### Funktioner

Aktivera:

- **Webbsökning** — för researchgrinden före betydelsefulla frågor.
- **Code Interpreter & Data Analysis** — för riktiga `.md`-, `.txt`-, `.json`- och ZIP-filer.
- **Filuppladdning** — för anteckningar, tidigare dokument och referensmaterial.

Aktivera inte som standard:

- **Bildgenerering** — endast om visuell idéutveckling blir en uttrycklig del av uppdraget.
- **Actions** — endast när en konkret extern överlämning kräver API-åtkomst och har säkerhetsbedömts.

## Installation i GPT-byggaren

1. Öppna den befintliga **Idékompassen** i GPT-redigeraren.
2. Spara eller duplicera den nuvarande versionen innan ändringar.
3. Ersätt hela fältet **Instructions** med innehållet i `INSTRUKTIONER.txt`.
4. Ta bort äldre Knowledge-filer som överlappar eller motsäger den nya strukturen.
5. Ladda upp samtliga åtta filer i mappen `knowledge/`.
6. Aktivera Webbsökning samt Code Interpreter & Data Analysis.
7. Lägg in beskrivningen och konversationsstartarna nedan.
8. Testa i Preview med `TESTSVIT.md`.
9. Kontrollera särskilt att GPT:n inte skapar överlämningsfiler före **godkänd**.
10. Spara den nya versionen först när de kritiska testerna är godkända.

## Konversationsstartare

- `Jag har en lös idé. Hjälp mig komma fram till vad jag faktiskt menar.`
- `Här är mina anteckningar. Bevara vad jag ville från början och undersök vad vi behöver upptäcka tillsammans.`
- `Jämför möjliga lösningar innan du ställer nästa fråga.`
- `Gör min idé tydlig nog att lämna till en annan GPT eller utvecklare.`
- `Idékontraktet är godkänt. Skapa genomförandeunderlaget och enkla överlämningsfiler.`

## Rekommenderat första test

Skicka:

> Jag vill göra något som hjälper små företag att svara kunder snabbare.

Godkänt beteende:

- bygger inte en kundbot direkt;
- håller flera tolkningar öppna, exempelvis skrivstöd, automation och prioritering;
- undersöker relevanta befintliga lösningstyper;
- ställer en enda särskiljande fråga;
- skiljer researchfynd från användarens beslut.

Fortsätt senare med:

> Min ursprungliga tanke var ett enkelt skrivstöd, men nu har vi upptäckt att sortering av ärenden är viktigare. Skriv Idékontraktet.

Godkänt beteende:

- låter inte den nya upptäckten radera ursprungsidén;
- placerar **Vad användaren ville från början** och **Vad vi upptäckte tillsammans** först;
- inväntar **godkänd** före filskapande.

## Förväntat arbetssätt

Idékompassen ska:

- ställa normalt en fråga i taget;
- forska innan den belastar användaren med externt besvarbara frågor;
- använda fungerande praktiska källor när de är relevanta;
- skilja fakta, praktiska belägg, egen slutsats och osäkerhet;
- kunna backa från en tidig hypotes;
- avsluta frågefasen när nästa part kan fortsätta utan att börja om;
- skapa minsta användbara filuppsättning efter godkännande.

## Begränsningar

- Webbkällor och programvaror kan förändras och måste kontrolleras vid användning.
- Användarens privata avsikt kan inte sökas fram; research ska i sådana fall belysa alternativ, inte ersätta användarens beslut.
- Idékompassen förbereder produktion men bygger inte hela slutprodukten som standard.
- Instruktionsstyrd hypoteshantering är inte en exakt statistisk sannolikhetsmodell.
- Tillgängliga funktioner kan bero på plan, arbetsyta och behörighet.

## Versionsprincip

Vid framtida uppdateringar:

- bevara namn, kärnuppdrag, enkelhet och de två viktigaste slutdelarna;
- jämför gammal och ny version med samma testfall;
- kontrollera aktuella OpenAI-funktioner på nytt;
- räkna instruktionen maskinellt;
- skapa nytt manifest och verifierad ZIP.
