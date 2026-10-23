# GPT-kontrakt, mallar och exempel

## 1. Mall för GPT-kontrakt

```markdown
# GPT-kontrakt

## Namn
[GPT:ns namn]

## Kärnuppdrag
[Vad den ska skapa eller hjälpa användaren att göra]

## Viktigaste löfte
> [Ett tydligt löfte]

## Användare
[Vem som använder den och i vilket sammanhang]

## Identitet
- Huvudsyfte:
- Kärnvärderingar:
- Tonalitet:
- Målgrupp:
- Sådant som aldrig får tappas:

## Arbetslägen
1. [Läge]
2. [Läge]

## Huvudflöde
1. ...
2. ...
3. ...

## Indata
- ...

## Utdata
- ...

## Kunskapsområden
- ...

## Rekommenderade funktioner
- Webbsökning:
- Code Interpreter & Data Analysis:
- Bildgenerering:
- Actions:
- Övrigt:

## Researchmodell
[När, hur och vilka källor]

## Säkerhet och godkännande
- ...

## Omfattning
### Ingår
- ...

### Ingår inte
- ...

## Leveransfiler
- `INSTRUKTIONER.txt`
- `README.md`
- `knowledge/...`
- ZIP

## Teststrategi
- ...

## Klart när
- ...

## Antaganden
- ...

## Begränsningar
- ...

> Är detta rätt förstått? Svara **godkänd**, eller rätta det som inte stämmer.
```

## 2. Mall för README

```markdown
# [GPT-namn]

**Version:**  
**Skapad:**  
**Typ:**

## Syfte

## Filer

## Instruktionens teckenantal

## Rekommenderad konfiguration
### Namn
### Beskrivning
### Funktioner
### Konversationsstartare

## Installation i GPT-byggaren

## Första test

## Godkänt beteende

## Begränsningar

## Versionsprincip
```

## 3. Mall för instruktion

```markdown
# [GPT-namn] — huvudinstruktion

## Roll och uppdrag

## Grundprincip

## Arbetslägen

## Arbetsflöde

## Frågelogik

## Verktygsregler

## Säkerhet och stoppvillkor

## Leveransformat

## Kvalitetskontroll

## Kommunikation
```

Använd endast rubriker som behövs.

## 4. Mall för Knowledge-fil

```markdown
# [Ämne]

## Syfte

## Definitioner

## Principer

## Arbetsflöden

## Exempel

## Fel och undantag

## Källor och verifieringsdatum
```

## 5. Mall för källpost

```markdown
## [Källtitel]

- Organisation:
- URL:
- Verifierad:
- Stödjer:
- Versions-/planberoende:
- Kommentar:
```

## 6. Mall för testfall

```text
Test-ID: T-001
Syfte:
Indata:
Förväntat beteende:
Förbjudet beteende:
Godkänt när:
Resultat:
```

## 7. Mall för CHANGELOG

```markdown
# Ändringslogg

## Version X.Y.Z — YYYY-MM-DD

### Bevarat
- ...

### Ändrat
- ...

### Tillagt
- ...

### Borttaget
- ...

### Rättat
- ...

### Testat
- ...
```

## 8. Mall för MIGRERING

```markdown
# Migrering från [gammal version] till [ny version]

## Före start
- exportera gamla instruktioner;
- ladda ned gamla Knowledge-filer;
- dokumentera aktiverade funktioner;
- spara testresultat.

## Installation
1. ...
2. ...

## Funktioner att aktivera

## Filer att ersätta

## Filer att behålla

## Test efter migrering

## Rollback
```

## 9. Mall för capability-bedömning

```markdown
## Funktion: [namn]

### Behov
[Vilket problem löser den?]

### Nytta
[Vad blir möjligt?]

### Risk
[Data, externa effekter, kostnad, integritet]

### Alternativ utan funktionen
[Kan målet nås enklare?]

### Rekommendation
[Aktivera / aktivera senare / aktivera inte]

### Godkännandekrav
[Vilket beslut krävs?]
```

## 10. Mall för Action-bedömning

```markdown
# Action-bedömning

## Affärsbehov

## Externt system

## Operationer
- read:
- write:
- delete:

## Autentisering

## Data som skickas

## Externa effekter

## Användargodkännande

## Felhantering

## Rate limits och kostnad

## OpenAPI-schema

## Testmiljö

## Loggning

## Säkerhetsbedömning

## Rekommendation
```

## 11. Exempel på välgrundad fråga

> Underlaget visar att GPT:n ska skapa rapporter från uppladdade kalkylblad. Officiell produktinformation anger att filanalys och filgenerering kräver Code Interpreter & Data Analysis, medan webbsökning bara behövs om rapporten även ska innehålla aktuella externa data. Jag rekommenderar därför Data Analysis som obligatoriskt och webbsökning som valbar. Ska rapporterna enbart bygga på uppladdade filer, eller även kompletteras med aktuella marknadsdata?

## 12. Exempel på onödig fråga

> Vilka funktioner vill du aktivera?

Den frågan saknar analys och lämnar plattformsdesignen till användaren.

## 13. Exempel på identitetsutvinning

Underlag:

> “Min GPT heter Kundvännen. Den ska vara lugn, varm och hjälpa äldre kunder att förstå fakturor utan att ge juridisk rådgivning.”

Extraherad identitet:

- namn: Kundvännen;
- huvudsyfte: förklara fakturor;
- kärnvärden: lugn, begriplighet, respekt;
- tonalitet: varm och pedagogisk;
- målgrupp: äldre kunder;
- löfte: göra fakturor begripliga;
- gräns: inte juridisk rådgivning.

Ombyggnaden får förbättra arbetsflöden, Knowledge och tester men får inte göra GPT:n kall, juridiskt rådgivande eller byta namn utan godkännande.

## 14. Exempel på paketbeslut

Behov:
- specialist-GPT för ett smalt, stabilt ämne;
- ingen aktuell webbinformation;
- inga filer behöver genereras.

Lämpligt paket:
- Instructions;
- README;
- en Knowledge-fil;
- testfil;
- ZIP.

Olämpligt:
- åtta Knowledge-filer;
- Actions;
- bildgenerering;
- webbsökning som obligatorisk.

## 15. Exempel på leveranssammanfattning

```markdown
## Leverans

Skapat:
- instruktion på 7 412 tecken;
- README;
- fyra Knowledge-filer;
- testsvit;
- manifest;
- ZIP.

Verifierat:
- instruktionen är under 8 000 tecken;
- ZIP kan öppnas;
- samtliga filer matchar manifestet;
- normalfall, kunskapslucka, research, stoppregel och filskapande testades.

Begränsning:
- plattformens aktuella Knowledge-gräns måste verifieras igen vid framtida version.
```

## 16. Mall för klickbar slutleverans

När verkliga filer har skapats ska slutmeddelandet följa denna struktur:

```markdown
# [GPT-namn] är färdig

[Hämta hela [GPT-namn]-paketet som ZIP](sandbox:/mnt/data/[paketnamn].zip)

## Paketets innehåll

- [INSTRUKTIONER.txt](sandbox:/mnt/data/[sökväg]/INSTRUKTIONER.txt) — [exakt antal] tecken, under gränsen 8 000.
- [README.md](sandbox:/mnt/data/[sökväg]/README.md) — installation och konfiguration.
- [TESTSVIT.md](sandbox:/mnt/data/[sökväg]/TESTSVIT.md) — testfall och klart-kriterier.
- [KALLOR.md](sandbox:/mnt/data/[sökväg]/KALLOR.md) — verifierade källor.
- [MANIFEST.json](sandbox:/mnt/data/[sökväg]/MANIFEST.json) — filförteckning och checksummor.

## Kunskapsfiler

1. [01-...md](sandbox:/mnt/data/[sökväg]/knowledge/01-...md)
2. [02-...md](sandbox:/mnt/data/[sökväg]/knowledge/02-...md)

## Verifierat

- instruktionen är maskinellt räknad;
- samtliga filer finns;
- ZIP kan öppnas;
- ZIP innehåller rätt filer;
- manifestet stämmer.
```

Regler:

- använd endast länkar till filer som faktiskt skapats och verifierats;
- ZIP-länken ska stå först och vara tydlig;
- visa både ZIP och enskilda filer;
- skriv inte råa filvägar utan klickbara länkar i slutleveransen;
- lämna inte byggskript i stället för filer;
- lägg inte filinnehåll i kodblock när nedladdningsbara filer fungerar.

## 17. Mall för misslyckad filleverans

När testfil eller ZIP verkligen inte kan skapas:

```markdown
## Filleveransen är inte färdig

Jag försökte skapa [testfil/ZIP], men verktyget returnerade: [kort faktisk felbeskrivning].

Detta har inte skapats:
- [fil]
- [ZIP]

Jag visar inga nedladdningslänkar eftersom filerna inte finns.
```

Använd inte den mallen utan ett faktiskt misslyckat skapandeförsök.
