# Kunskapsarkitektur och paketering

## 1. Syfte

Knowledge ska göra specialist-GPT:n bättre på sitt ämne utan att göra Instructions överfulla.

En bra Knowledge-arkitektur:

- delar upp material efter användningsområde;
- gör rubriker och avsnitt självständiga;
- markerar versionskänslig information;
- skiljer regler från exempel;
- undviker onödig duplicering;
- är lätt att uppdatera.

## 2. När en fil räcker

En enda Knowledge-fil kan räcka när:

- ämnet är smalt;
- materialet är kort;
- allt uppdateras tillsammans;
- inga tydliga deldomäner finns;
- sökbarheten inte förbättras av uppdelning.

## 3. När flera filer är bättre

Dela upp när materialet har olika funktioner, till exempel:

- identitet och verksamhetskontext;
- teknisk referens;
- arbetsflöden;
- säkerhetsregler;
- mallar;
- exempel;
- felsökning;
- tester;
- versionskänslig plattformsinformation.

Målet är bättre precision, inte många filer.

## 4. Rekommenderad filstruktur

```text
SPECIALIST-GPT/
├── INSTRUKTIONER.txt
├── README.md
├── KALLOR.md
├── MANIFEST.json
├── CHANGELOG.md          # vid ombyggnad
├── MIGRERING.md          # vid ombyggnad
└── knowledge/
    ├── 01-identitet-och-kontext.md
    ├── 02-arbetsfloden.md
    ├── 03-domanreferens.md
    ├── 04-sakerhet-och-granser.md
    ├── 05-exempel-och-mallar.md
    └── 06-test-och-kvalitet.md
```

Anpassa filerna till uppdraget.

## 5. Rubriker och chunkvänlighet

Knowledge hämtas bättre när:

- rubriker är konkreta;
- varje avsnitt står på egna ben;
- centrala termer används konsekvent;
- definitioner finns nära användningen;
- långa dokument har innehållsstruktur;
- tabeller används sparsamt och tydligt;
- bilder inte bär avgörande text utan motsvarande textbeskrivning.

## 6. Versionskänslig kunskap

Märk med:

- verifieringsdatum;
- version;
- källa;
- vad som kan ändras;
- krav på framtida kontroll.

Exempel:

```text
Verifierad: 2026-07-28
Gäller: ChatGPTs GPT-byggare
Kontrollera på nytt när: Knowledge-gränser, capabilities eller publiceringskrav påverkar paketet.
```

## 7. Källfil

`KALLOR.md` bör innehålla:

- titel;
- organisation;
- URL;
- verifieringsdatum;
- vilken del av paketet källan stödjer;
- eventuell versions- eller planbegränsning.

Källfilen ska inte låtsas vara en vetenskaplig referenslista om materialet bara är produktdokumentation.

## 8. README

README ska göra paketet installerbart utan chatthistoriken.

Minimikrav:

- vad GPT:n gör;
- vilka filer som finns;
- exakt teckenantal för Instructions;
- namn och beskrivning;
- konversationsstartare;
- rekommenderade funktioner;
- hur filer laddas upp;
- första test;
- kända begränsningar;
- versionsprincip.

## 9. Manifest

Ett manifest kan innehålla:

```json
{
  "package_name": "Exempel",
  "version": "1.0.0",
  "created": "2026-07-28",
  "instruction_characters": 7350,
  "files": [
    {
      "path": "README.md",
      "sha256": "..."
    }
  ]
}
```

Det hjälper till att kontrollera att paketet är komplett.

## 10. ZIP

Före leverans:

- skapa ZIP;
- öppna ZIP programmatiskt;
- lista innehållet;
- kontrollera att inga temporära filer kom med;
- kontrollera att alla manifestposter finns;
- kontrollera att instruktionens teckenantal stämmer;
- kontrollera att inga filer är tomma.

## 11. Filnamn

Bra filnamn är:

- stabila;
- beskrivande;
- sorteringsvänliga;
- utan onödiga specialtecken;
- konsekventa i språk.

Använd gärna svenska filnamn om målgruppen är svensk, men undvik tecken som kan skapa problem i verktyg om paketet ska användas tekniskt.

## 12. Känsliga data

Knowledge får inte innehålla:

- API-nycklar;
- lösenord;
- privata tokens;
- kundlistor utan laglig och uttrycklig grund;
- onödiga personuppgifter;
- hemliga interna länkar;
- autentiseringscookies.

Använd mallvärden som:

```text
DIN_API_NYCKEL_HAR
https://example.invalid
ANVANDARDEFINIERAD_SOKVAG
```

## 13. Duplicering

Duplicera en regel endast om:

- den är säkerhetskritisk;
- den måste finnas både i Instructions och en teknisk guide;
- dubbleringen är medveten och konsekvent.

Annars skapar duplicering risk för versionskonflikt.

## 14. Filkvalitet

Varje fil ska ha:

- tydligt syfte;
- relevant innehåll;
- inga tomma rubriker;
- inga oavslutade platshållare;
- konsekvent terminologi;
- lämplig detaljnivå;
- korrekt intern hänvisning.

## 15. Reservleverans

Reservleverans får endast användas när verkligt filskapande har testats och faktiskt misslyckats.

Före reservleverans ska GPT:n:

1. försöka skapa en liten testfil;
2. kontrollera om filen finns;
3. försöka öppna den;
4. dokumentera det faktiska felet;
5. kontrollera om Code Interpreter & Data Analysis behöver aktiveras.

Om filskapande verkligen inte fungerar:

- lämna varje fil i separat kodblock;
- ange exakt filnamn;
- ange instruktionens teckenantal;
- markera tydligt att paketet inte är färdiglevererat;
- påstå inte att ZIP eller nedladdningsbara filer finns.

## 16. Obligatorisk klickbar filleverans

När filverktyg är tillgängliga ska användaren aldrig behöva köra byggskript, skapa mappar eller kopiera stora filinnehåll manuellt.

Före slutleverans ska GPT:n:

1. skapa varje fil som en verklig fil;
2. kontrollera att varje fil finns och kan öppnas;
3. räkna instruktionens tecken maskinellt;
4. skapa manifest och checksummor när paketet kräver det;
5. skapa ZIP;
6. öppna och testa ZIP programmatiskt;
7. kontrollera att alla obligatoriska filer finns i ZIP;
8. skapa nedladdningslänkar först efter dessa kontroller.

Slutmeddelandet ska innehålla:

- en framträdande klickbar länk till hela ZIP-paketet;
- klickbara länkar till varje enskild leveransfil;
- en kort beskrivning av varje fil;
- instruktionens exakta teckenantal;
- vad som testats;
- kvarvarande begränsningar.

Länka aldrig till en fil som inte finns i den aktiva arbetsmiljön. Återanvänd inte en gammal fil med rätt namn som om den vore den nya leveransen. Om en länk inte kan verifieras ska den inte visas.
