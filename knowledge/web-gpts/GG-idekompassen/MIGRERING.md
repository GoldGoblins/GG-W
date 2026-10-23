# Migrering till Idékompassen 2.0.0

## Målet

Det här är ett komplett ersättningspaket för den befintliga Idékompassen. Namnet och kärnidén bevaras, medan frågelogik, research, överlämning och testbarhet förstärks.

## Före ändringen

1. Öppna den nuvarande GPT:n i redigeraren.
2. Spara den aktuella versionen eller duplicera GPT:n som rollback.
3. Kopiera de gamla instruktionerna till en lokal säkerhetskopia.
4. Notera aktiverade funktioner och nuvarande Knowledge-filer.
5. Kör gärna ett eller två vanliga testfall mot den gamla versionen och spara svaren.

## Filer som ska ersättas eller läggas till

### Ersätt

- Nuvarande Instructions → `INSTRUKTIONER.txt`
- Nuvarande README/dokumentation → `README.md`

### Lägg till som Knowledge

- `knowledge/01-identitet-och-karnide.md`
- `knowledge/02-hypotesmotor-och-fragelogik.md`
- `knowledge/03-researchgrind-och-kallkritik.md`
- `knowledge/04-idekontrakt-och-overlamning.md`
- `knowledge/05-genomforandeunderlag-per-destination.md`
- `knowledge/06-exempel-och-felmonster.md`
- `knowledge/07-chatgpt-plattformsbaslinje-2026-07-28.md`
- `knowledge/08-godkant-gpt-kontrakt.md`

### Behåll utanför Knowledge

- `README.md`
- `CHANGELOG.md`
- `MIGRERING.md`
- `TESTSVIT.md`
- `KALLOR.md`
- `MANIFEST.json`

Dessa är installations-, versions- och kontrollfiler. De behöver normalt inte laddas upp till GPT:n.

## Äldre Knowledge

Ta bort eller arkivera äldre filer som:

- beskriver ett motsägande Idékontrakt;
- kräver att GPT:n bygger en full produkt direkt;
- saknar de två nya obligatoriska huvudfälten;
- innehåller gammal plattformsinformation;
- duplicerar de nya filerna och riskerar versionskonflikt.

Behåll projektspecifika exempel endast om de fortfarande är korrekta och tydligt kompletterar den nya strukturen.

## Funktioner

Aktivera:

- Webbsökning.
- Code Interpreter & Data Analysis.
- Filuppladdning/Knowledge.

Lämna normalt av:

- Actions.
- Bildgenerering.

Aktivera dem senare endast efter ett konkret behov.

## Installation

1. Klistra in hela `INSTRUKTIONER.txt` i Instructions.
2. Kontrollera att inga gamla instruktioner ligger kvar före eller efter texten.
3. Ladda upp de åtta Knowledge-filerna.
4. Uppdatera namn, beskrivning och konversationsstartare enligt `README.md`.
5. Aktivera rekommenderade funktioner.
6. Öppna Preview.
7. Kör först testerna T-001, T-003, T-005, T-009, T-013 och T-017.
8. Kör därefter hela testsviten.
9. Jämför svaren med den sparade gamla versionen.
10. Spara den nya versionen när kritiska tester är godkända.

## Viktiga beteendeskillnader att kontrollera

Den nya GPT:n ska:

- fråga mindre mekaniskt men tänka mer strukturerat;
- bevara ursprungsavsikten även när idén utvecklas;
- redovisa gemensamma upptäckter separat;
- söka innan den frågar om existerande lösningar;
- kunna säga att en tidigare tolkning var fel;
- skapa överlämningsfiler först efter **godkänd**;
- inte börja bygga hela slutprodukten utan särskilt uppdrag.

## Rollback

Om den nya versionen misslyckas med ett kritiskt test:

1. återgå till den sparade eller duplicerade gamla versionen;
2. notera testets indata och det felaktiga svaret;
3. ändra endast den berörda instruktionen eller Knowledge-filen;
4. kör både det misslyckade testet och regressionstesterna igen;
5. spara inte den nya versionen förrän felet är löst.
