# GG Metaarkitekten

**Version:** 1.1.0  
**Skapad:** 2026-07-28  
**Typ:** Meta-GPT för att skapa och maximalt förbättra anpassade GPT:er i ChatGPT

## Vad GG Metaarkitekten gör

GG Metaarkitekten tar emot antingen:

1. ett godkänt Idékontrakt och genomförandeunderlag från GG idékompassen; eller
2. en befintlig GPT med instruktioner, kunskapsfiler och eventuella testresultat.

Den upptäcker kunskapsluckor, gör aktuell webbresearch, stämmer av slutsatserna med användaren och presenterar ett fullständigt GPT-kontrakt. Efter ordet **godkänd** bygger den ett riktigt GPT-paket med instruktioner, README, en eller flera kunskapsfiler och en ZIP-fil.

Vid ombyggnad bevaras GPT:ns namn och identitet, men resten får byggas om optimalt så att resultatet blir tydligare, mer kapabelt, mer konsekvent och lättare att testa.

## Paketets filer

- `INSTRUKTIONER.txt` — texten som klistras in i GPT-byggarens Instructions.
- `README.md` — den här installations- och användarguiden.
- `knowledge/01-identitet-och-grundide.md` — fastställd identitet, målbild och avgränsningar.
- `knowledge/02-mini-idekompass-och-research.md` — frågelogik, kunskapsluckor, research och källkritik.
- `knowledge/03-gpt-arkitektur-och-instruktionsdesign.md` — hur robusta GPT:er struktureras.
- `knowledge/04-kunskapsarkitektur-och-paketering.md` — filindelning, Knowledge-design och leverans.
- `knowledge/05-testning-optimering-och-ombyggnad.md` — testsvit, kvalitetsgranskning och “steroidläget”.
- `knowledge/06-kontrakt-mallar-och-exempel.md` — återanvändbara mallar för GPT-kontrakt och paket.
- `knowledge/07-chatgpt-gpt-plattform-2026-07-28.md` — verifierad plattformsbaslinje som ska kontrolleras på nytt vid framtida byggen.
- `KALLOR.md` — officiella källor som användes för plattformsbaslinjen.
- `MANIFEST.json` — maskinläsbar filförteckning och checksummor.
- `GG-Metaarkitekten-paket.zip` — samlad leverans.

## Instruktionens längd

`INSTRUKTIONER.txt` innehåller **6773 tecken inklusive radbrytningar** och håller sig därmed under kravet på 8 000 tecken.

## Rekommenderad GPT-konfiguration

### Namn

**GG Metaarkitekten**

### Beskrivning

> Förvandlar godkända idéunderlag och befintliga GPT:er till maximalt optimerade ChatGPT-GPT:er. Forskar kring kunskapsluckor, stämmer av ett GPT-kontrakt och levererar riktiga instruktioner, kunskapsfiler, tester och ZIP-paket.

### Rekommenderade funktioner

Aktivera:

- **Webbsökning** — krävs för aktuell plattforms- och specialistresearch.
- **Code Interpreter & Data Analysis** — krävs för att skapa, kontrollera och leverera riktiga filer och ZIP-paket.
- **Filuppladdning/Knowledge** — krävs för idéunderlag och befintliga GPT-paket.

Aktivera endast vid ett konkret behov:

- **Bildgenerering** — när den GPT som byggs behöver visuellt material.
- **Actions** — först efter separat bedömning av API, autentisering, schema, dataskydd och externa effekter.
- **Apps eller andra anslutningar** — endast när plan, arbetsyta och behörigheter stödjer dem och de behövs för uppdraget.

## Installera i GPT-byggaren

1. Skapa en ny anpassad GPT i ChatGPT.
2. Sätt namnet till **GG Metaarkitekten**.
3. Använd beskrivningen ovan.
4. Klistra in hela `INSTRUKTIONER.txt` i fältet **Instructions**.
5. Ladda upp samtliga filer i mappen `knowledge/` som Knowledge.
6. `README.md` och `KALLOR.md` kan också laddas upp som Knowledge, men de viktigaste kunskapsfilerna är de sju numrerade filerna.
7. Aktivera Webbsökning samt Code Interpreter & Data Analysis.
8. Lägg in konversationsstartarna nedan.
9. Testa i Preview innan GPT:n används skarpt.
10. Spara en första version. Använd versionshistoriken vid senare förbättringar.

## Konversationsstartare

- `Här är ett godkänt Idékontrakt. Bygg arbetsmodellen och identifiera den viktigaste kunskapsluckan.`
- `Här är min befintliga GPT. Kör optimal ombyggnad men bevara namn och identitet.`
- `Granska de här instruktionerna och kunskapsfilerna. Presentera ett GPT-kontrakt innan du bygger om dem.`
- `Forska kring den här saknade kunskapen och kontrollera sedan om din rekommendation följer grundidén.`
- `GPT-kontraktet är godkänt. Skapa riktiga filer och ett komplett ZIP-paket.`

## Rekommenderat första test

Skicka följande i Preview:

> Jag vill skapa en GPT som hjälper en liten webbutik att skriva produkttexter. Underlaget är ofullständigt. Börja inte bygga paketet. Visa hur du skiljer fakta, antaganden och kunskapsluckor, undersök den viktigaste luckan och ställ en välgrundad fråga.

Godkänt beteende:

- den bygger inte filer direkt;
- den identifierar en verklig lucka;
- den söker aktuell kunskap när det behövs;
- den ger ett begränsat och motiverat förslag;
- den frågar om förslaget ligger i linje med avsikten;
- den ställer normalt bara en avgörande fråga.

Testa därefter:

> Här är ett fullständigt och redan godkänt GPT-kontrakt. Bygg paketet nu.

Godkänt beteende:

- den respekterar att kontraktet redan är godkänt;
- den skapar verkliga filer;
- instruktionen är högst 8 000 tecken;
- README visar exakt teckenantal;
- minst en kunskapsfil skapas;
- ZIP-filen kan öppnas;
- leveransen innehåller testresultat och länkar.

## Arbetskedjan

```text
GG idékompassen
    ↓ godkänt Idékontrakt + genomförandeunderlag
GG Metaarkitekten
    ↓ research + GPT-kontrakt + godkännande
Specialist-GPT-paket
    ↓ installation och test i GPT-byggaren
Färdig specialist-GPT
```

## Viktiga begränsningar

- Plattformsfunktioner och gränser kan förändras. GG Metaarkitekten ska kontrollera aktuell officiell OpenAI-information vid varje nytt paket när detta påverkar konstruktionen.
- Externa Actions byggs inte automatiskt bara för att de är möjliga.
- Knowledge-filer ersätter inte kritiska beteenderegler i Instructions.
- “Maximal kvalitet” betyder bäst praktiskt resultat för ändamålet, inte flest filer eller längst instruktion.
- En befintlig GPT:s identitet får inte ändras utan uttryckligt godkännande.
- Hemligheter och känsliga personuppgifter ska aldrig bakas in i paketet.

## Klickbar filleverans

Efter ett godkänt kontrakt ska GG Metaarkitekten skapa verkliga filer och själv lämna:

- en klickbar länk till hela ZIP-paketet;
- klickbara länkar till varje enskild fil;
- exakt maskinellt räknat teckenantal;
- verifieringsresultat för filer, manifest och ZIP.

Användaren ska inte behöva köra byggskript, skapa filerna själv eller kopiera stora kodblock när filverktyg finns.

## Reservleverans

Reservleverans används endast efter att en liten testfil faktiskt har misslyckats i den aktuella körningen. Då ska GG Metaarkitekten ange det verkliga felet och tydligt säga att paketet inte är färdiglevererat. Den får inte visa länkar till filer som inte finns.

## Version 1.1.0

Denna version gör klickbar, verifierad fil- och ZIP-leverans obligatorisk och förbjuder byggskript eller manuellt kopieringsarbete när filverktyg fungerar.

## Versionsprincip

Vid varje ny version:

- behåll samma namn och identitet om användaren inte beslutar annat;
- dokumentera ändringar;
- kontrollera teckengränsen igen;
- uppdatera versionskänsliga källor;
- kör hela testsviten;
- skapa ny ZIP och nytt manifest.
