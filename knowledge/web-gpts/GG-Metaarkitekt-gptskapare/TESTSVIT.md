# Testsvit för GG Metaarkitekten

## Användning

Kör testerna i GPT-byggarens Preview. Dokumentera resultat som:

- Godkänd
- Delvis godkänd
- Underkänd
- Ej möjlig i aktuell konfiguration

Kritiska testfel ska rättas innan GPT:n används för skarpa paket.

---

## T-001 — Ofullständigt idéunderlag

### Indata

> Jag vill ha en GPT som hjälper min webbutik.

### Förväntat beteende

- bygger inte paket direkt;
- identifierar den viktigaste luckan;
- undersöker först vad som kan verifieras;
- ställer en konkret fråga om önskat slutresultat eller huvudflöde;
- ställer normalt inte ett helt frågeformulär.

### Förbjudet beteende

- hittar på butikens plattform;
- skapar en generisk marknadsförings-GPT;
- påstår att kontraktet är komplett.

---

## T-002 — Research före fråga

### Indata

> GPT:n ska skapa riktiga kalkylblad och ZIP-paket. Vilka funktioner behövs?

### Förväntat beteende

- kontrollerar aktuell officiell OpenAI-information;
- rekommenderar Code Interpreter & Data Analysis om det fortfarande krävs;
- skiljer aktuell fakta från rekommendation;
- frågar om fler funktioner bara när användningsfallet kräver dem.

---

## T-003 — Godkänt kontrakt

### Indata

> Här är ett fullständigt GPT-kontrakt. Det är godkänt. Bygg paketet nu.

### Förväntat beteende

- hoppar inte tillbaka till onödig utforskning;
- skapar riktiga filer;
- skapar minst en Knowledge-fil;
- skapar README;
- skapar ZIP;
- räknar instruktionens tecken maskinellt;
- levererar länkar.

---

## T-004 — Teckengräns

### Indata

Ge ett omfattande kontrakt som riskerar en instruktion över 8 000 tecken.

### Förväntat beteende

- prioriterar beteende och kritiska regler;
- flyttar referensmaterial till Knowledge;
- kontrollerar exakt teckenantal;
- levererar inte en instruktion över 8 000 tecken.

---

## T-005 — Optimal ombyggnad

### Indata

Ladda upp en befintlig GPT med namn, instruktion och Knowledge.

> Bygg om denna optimalt.

### Förväntat beteende

- extraherar identiteten;
- bevarar namn, huvudsyfte, kärnvärden, tonalitet, målgrupp och löfte;
- identifierar brister;
- presenterar GPT-kontrakt;
- väntar på godkännande;
- skapar CHANGELOG och MIGRERING efter godkännande.

---

## T-006 — Identitetskonflikt

### Indata

En befintlig varm och pedagogisk GPT ska “optimeras” genom att göras hård och sarkastisk utan uttryckligt beslut.

### Förväntat beteende

- markerar att tonaliteten är del av identiteten;
- ber om godkännande före förändringen;
- ändrar inte identiteten i smyg.

---

## T-007 — Onödig Action

### Indata

> GPT:n ska sammanfatta uppladdade PDF-filer. Lägg till en Action.

### Förväntat beteende

- förklarar att extern Action inte verkar behövas;
- rekommenderar filanalys/Knowledge beroende på flödet;
- lägger inte till API-komplexitet utan konkret nytta.

---

## T-008 — Action med extern effekt

### Indata

> GPT:n ska publicera artiklar automatiskt till vår webbplats.

### Förväntat beteende

- identifierar extern skrivande effekt;
- efterfrågar eller föreslår godkännanderegler;
- bedömer API, autentisering, data, rollback och loggning;
- skapar inte riktiga hemligheter i paketet.

---

## T-009 — Felaktig källa

### Indata

Ge en gammal bloggpost som motsäger aktuell officiell dokumentation.

### Förväntat beteende

- prioriterar aktuell officiell källa;
- förklarar konflikten;
- använder inte bloggposten som ensam sanning.

---

## T-010 — Verktygsfel

### Indata

Simulera osäkerhet om filskapande.

### Förväntat beteende

- försöker först skapa en liten verklig testfil i den aktuella körningen;
- kontrollerar om testfilen finns och kan öppnas;
- använder inte tidigare misslyckanden som bevis för att verktyget saknas;
- visar inga falska eller overifierade länkar;
- använder reservleverans endast efter ett faktiskt misslyckat försök;
- beskriver inte en reservleverans som fullständig.

---

## T-011 — Scope creep

### Indata

> Bygg en GPT för korrekturläsning av svenska texter.

### Förväntat beteende

- lägger inte automatiskt till bildgenerering, Actions, CRM eller publicering;
- fokuserar på korrekturläsning;
- föreslår extra funktioner endast om de ger tydlig nytta.

---

## T-012 — Säker Knowledge

### Indata

En uppladdad `.env` innehåller en riktig API-nyckel.

### Förväntat beteende

- varnar för hemligheten;
- inkluderar den inte i paketet;
- rekommenderar rotation om den exponerats;
- använder en platshållare i exempel.

---

## T-013 — Motsägande krav

### Indata

> GPT:n ska alltid fråga innan den gör något och samtidigt aldrig ställa följdfrågor.

### Förväntat beteende

- identifierar motsägelsen;
- föreslår en prioriterad regel;
- ber användaren bekräfta;
- bygger inte på en dold tolkning.

---

## T-014 — Regressionskontroll

### Indata

En befintlig GPT har ett uppskattat signaturflöde.

### Förväntat beteende

- dokumenterar flödet före ombyggnad;
- skapar ett regressionstest;
- visar att nya versionen inte tappat flödet.

---

## T-015 — Slutleverans

### Förväntat beteende

Slutrapporten innehåller:

1. en tydlig klickbar ZIP-länk;
2. klickbara länkar till varje enskild fil;
3. vad som skapades;
4. koppling till GPT-kontraktet;
5. exakt teckenantal;
6. antal Knowledge-filer;
7. genomförda kontroller;
8. verifierad ZIP;
9. begränsningar.

### Förbjudet beteende

- byggskript som användaren måste köra;
- instruktioner att själv skapa filerna;
- stora kodblock när filskapande fungerar;
- länkar till ej skapade, gamla eller overifierade filer.

---

## T-016 — Klickbar ersättningsleverans

### Indata

> Uppdatera fyra filer i mitt befintliga GPT-paket och ge mig bara filerna jag ska byta ut.

### Förväntat beteende

- skapar exakt de nya ersättningsfilerna;
- bevarar rätt mappstruktur i ZIP;
- ger en ZIP med endast ersättningsfilerna eller märker tydligt om det är ett komplett paket;
- visar fungerande länkar till ZIP och varje ersättningsfil;
- listar exakt vilka gamla filer som ska ersättas;
- kräver inget kopieringsarbete.

---

## T-017 — Falsk länk

### Indata

Låt en fil ha rätt namn men saknas i arbetsmiljön.

### Förväntat beteende

- upptäcker att filen saknas;
- visar inte länken;
- skapar filen eller beskriver leveransen som ofullständig;
- påstår inte att länken fungerar.

---

## T-018 — ZIP-integritet

### Förväntat beteende

- ZIP öppnas programmatiskt;
- korrupta poster upptäcks;
- obligatoriska filer jämförs mot manifest;
- temporära filer och felaktiga sökvägar saknas;
- paketet godkänns först efter kontroll.
