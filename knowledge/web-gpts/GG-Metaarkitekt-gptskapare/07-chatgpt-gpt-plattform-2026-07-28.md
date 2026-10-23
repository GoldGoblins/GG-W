# ChatGPT-GPT-plattformen — verifierad baslinje 2026-07-28

## Syfte

Den här filen dokumenterar sådant som var verifierat mot officiella OpenAI-källor den 28 juli 2026. Informationen är versionskänslig. GG Metaarkitekten ska söka och verifiera på nytt när ett framtida paket beror på plattformens aktuella funktioner eller gränser.

## Vad en anpassad GPT består av

OpenAI beskriver GPT:er som versioner av ChatGPT som konfigurerats för ett särskilt ändamål. De kan kombinera:

- specifika instruktioner;
- Knowledge-filer;
- valda funktioner eller capabilities;
- i vissa konfigurationer appar eller Actions;
- delning och publicering beroende på plan och arbetsyta.

Instruktioner och Knowledge har olika roller:

- **Instructions** beskriver hur GPT:n ska bete sig, fatta beslut och använda materialet.
- **Knowledge** ger källmaterial som GPT:n kan hämta relevant information ur under samtalet.

Kritiska beteenderegler får därför inte endast ligga i Knowledge.

## Knowledge-gränser

Den officiella GPT-dokumentationen angav vid verifieringen:

- upp till 20 Knowledge-filer per GPT;
- upp till 512 MB per fil;
- stöd för vanliga dokument-, text-, kod-, bild- och dataformat;
- vissa filtyper och arbetsflöden kan bero på att Code Interpreter & Data Analysis är aktiverat.

Gränserna ska inte betraktas som permanenta. Kontrollera aktuell dokumentation före paket som använder många eller stora filer.

## Filskapande

För GG Metaarkitekten är verkligt filskapande centralt eftersom huvudleveransen består av nedladdningsbara filer och ZIP-paket.

Vid ett godkänt paket ska GPT:n:

1. använda tillgängligt filverktyg för att skapa en liten testfil om verktygsstatusen är osäker;
2. kontrollera att testfilen finns och kan öppnas;
3. skapa de verkliga leveransfilerna;
4. verifiera varje fil;
5. skapa och testa ZIP;
6. visa klickbara länkar först när filerna har verifierats.

GPT:n får inte dra slutsatsen att filskapande saknas enbart för att tidigare försök, ett annat samtal eller ett gränssnitt misslyckats. Ett faktiskt försök ska göras i den aktuella körningen.

När filskapande fungerar ska användaren inte få:

- Python- eller shellskript som den måste köra;
- instruktioner att själv skapa mappar och filer;
- stora kodblock som ersättning för nedladdningsbara filer;
- länkar till gamla eller ej skapade filer.

Om ett faktiskt test misslyckas ska GPT:n ange felet, avstå från falska länkar och tydligt beskriva leveransen som ofullständig. Separata kodblock är endast en tillfällig reserv.

## Webbsökning

Webbsökning behövs för:

- aktuell GPT-plattformsinformation;
- versionskänslig specialistkunskap;
- officiella produktsidor;
- säkerhets- och kompatibilitetskontroller;
- aktuell dokumentation för verktyg och integrationer.

Webbsökning ska användas selektivt men obligatoriskt när fakta kan ha ändrats.

## Actions

Actions ansluter en GPT till externa API:er. De kan kräva:

- OpenAPI-schema;
- autentiseringsmodell;
- tydlig beskrivning av operationer;
- sekretess- och dataskyddsbedömning;
- workspace-behörighet;
- publiceringskrav;
- kontroll av externa effekter.

GG Metaarkitekten ska inte rekommendera Actions som standard. Den ska först bevisa att den tänkta GPT:n behöver handla i ett externt system och att en vanlig konversation, Knowledge, webbsökning eller filanalys inte räcker.

För Actions ska paketet vid behov innehålla en separat teknisk specifikation. Hemligheter eller riktiga API-nycklar får aldrig placeras i Knowledge eller instruktionstext.

## Appar och arbetsytor

Tillgång till appar, Actions, delning, publicering och andra funktioner kan variera beroende på:

- ChatGPT-plan;
- arbetsyta;
- administratörsinställningar;
- användarroll;
- region;
- säkerhetspolicy.

Paketets README ska därför beskriva rekommenderade funktioner och samtidigt säga att GPT-byggarens aktuella gränssnitt och arbetsytans inställningar är källan till vad som faktiskt kan aktiveras.

## Versioner och Preview

Den officiella GPT-dokumentationen beskriver skapande, redigering, testning och versionshistorik. GG Metaarkitekten ska alltid rekommendera att:

- GPT:n testas i Preview;
- en version sparas före större ombyggnad;
- gamla och nya versioner jämförs med samma testfall;
- migrationsinstruktioner används när en befintlig GPT byggs om.

## Delning och publicering

Delningsalternativ kan omfatta privat användning, specifika användare eller arbetsyta, länkdelning och GPT Store, men tillgången beror på plan och workspace.

GG Metaarkitekten ska skilja mellan:

- **bygga GPT-paketet**;
- **installera GPT:n**;
- **dela eller publicera GPT:n**.

Publicering är ett separat beslut och ska inte antas.

## Regel för framtida research

När aktuell plattformsinformation behövs:

1. sök endast eller i första hand officiella OpenAI-källor;
2. dokumentera verifieringsdatum;
3. skilj på generell GPT-funktion, planberoende funktion och betafunktion;
4. undvik att hårdkoda modellnamn eller gränssnitt som kan förändras;
5. uppdatera `KALLOR.md` och relevant kunskapsfil;
6. skriv tidskänslig information som baslinje, inte evig sanning.
