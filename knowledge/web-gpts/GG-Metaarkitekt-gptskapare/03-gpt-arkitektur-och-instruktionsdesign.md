# GPT-arkitektur och instruktionsdesign

## 1. Grundmodell

En stark specialist-GPT behöver en tydlig uppdelning mellan:

- identitet;
- uppdrag;
- beslutslogik;
- arbetsflöden;
- verktygsregler;
- stopp- och godkännandegränser;
- referenskunskap;
- testbarhet.

Instruktionen ska styra beteendet. Knowledge ska ge ämnesmaterial.

## 2. Instruktionens prioriterade innehåll

När 8 000 tecken är en hård gräns ska utrymmet prioriteras så här:

1. roll och kärnuppdrag;
2. tvingande arbetsflöde;
3. besluts- och frågelogik;
4. säkerhet och stoppvillkor;
5. verktygsregler;
6. leveransformat;
7. kvalitetskontroll;
8. tonalitet;
9. exempel endast där de löser verklig tvetydighet.

Historik, långa domänförklaringar och referensmaterial ska flyttas till Knowledge.

## 3. Bra instruktioner

Bra instruktioner är:

- konkreta;
- handlingsorienterade;
- prioriterade;
- fria från onödig repetition;
- tydliga om när en regel gäller;
- tydliga om vad som händer vid konflikt;
- möjliga att testa.

Exempel:

> När användarens fråga gäller aktuell lagstiftning ska du söka officiella rättskällor innan du svarar. Ange datum och jurisdiktion. Om jurisdiktion saknas, fråga vilken som gäller.

Det är bättre än:

> Var alltid juridiskt korrekt och noggrann.

## 4. Utlösare–åtgärd–stopp

Komplexa arbetsflöden bör skrivas som:

```text
Utlösare:
Vad som aktiverar flödet.

Åtgärd:
Vad GPT:n gör i vilken ordning.

Stopp:
När GPT:n pausar, frågar eller vägrar gå vidare.

Leverans:
Vilket resultat som ska lämnas.
```

## 5. Prioritetsregler

När två krav kan krocka ska instruktionen ange prioritet.

Exempel:

1. säkerhet och laglighet;
2. bevarad identitet;
3. godkänt GPT-kontrakt;
4. användarens aktuella uppdrag;
5. effektivitet och stil.

Undvik att skriva många absoluta “alltid” som senare motsäger varandra.

## 6. Frågelogik

En specialist-GPT ska veta när den ska fråga.

Fråga när:

- svaret förändrar lösningen väsentligt;
- risk eller behörighet är oklar;
- flera helt olika slutresultat är möjliga;
- användaren behöver göra ett värde- eller affärsval;
- data saknas för ett säkert beslut.

Fråga inte när:

- uppgiften redan är tydlig;
- svaret finns i underlaget;
- en lågriskdetalj kan väljas reversibelt;
- webbresearch kan ge fakta;
- frågan bara skjuter upp arbetet.

## 7. Verktygsdesign

För varje funktion eller capability ska paketet beskriva:

- varför den behövs;
- när den ska användas;
- när den inte ska användas;
- vilken information som får skickas;
- vad som kräver godkännande;
- hur fel hanteras.

### Webbsökning

Bra för aktuella fakta, specialistresearch och källor.

### Code Interpreter & Data Analysis

Bra för:

- riktiga filer;
- ZIP;
- dataanalys;
- verifiering;
- tabeller;
- kodbaserade kontroller.

### Bildgenerering

Bra när den färdiga GPT:ns kärnuppgift kräver bilder. Aktivera inte av rutin.

### Actions

Bra när GPT:n måste kommunicera med ett externt API. Kräver mer teknisk och säkerhetsmässig design.

## 8. Knowledge-hänvisningar

Instruktionen kan beskriva hur Knowledge ska användas:

- använd identitetsfilen som källan för kärnsyftet;
- använd testfilen före leverans;
- använd versionsfilen endast efter aktuell verifiering;
- prioritera projektspecifika fakta framför generella exempel.

Skriv inte att GPT:n ska “läsa alla filer varje gång” om det inte behövs. Bättre är att ange vilken filtyp som är relevant för vilket beslut.

## 9. Felhantering

En specialist-GPT ska kunna:

- säga vilken information som saknas;
- skilja fel i data från fel i verktyg;
- undvika att låtsas ha skapat en fil;
- återuppta från senaste verifierade steg;
- beskriva vad som misslyckades;
- lämna ett säkert nästa steg.

## 10. Säkerhetsdesign

För känsliga GPT:er ska instruktionen ange:

- förbjudna data;
- tillåtna datakällor;
- godkännande före externa effekter;
- minsta möjliga behörighet;
- maskering av hemligheter;
- stopp vid osäker identitet eller destination;
- loggning;
- vad som aldrig får automatiseras.

## 11. Tonalitet

Tonalitet ska stödja uppgiften. Definiera:

- språk;
- formell eller vardaglig nivå;
- önskad detaljnivå;
- hur osäkerhet uttrycks;
- hur frågor ställs;
- hur leveranser sammanfattas.

Undvik att låta personlighet tränga undan korrekthet eller uppdrag.

## 12. Instruktionskomprimering

När texten närmar sig 8 000 tecken:

1. ta bort dubbleringar;
2. flytta stabil referenskunskap till Knowledge;
3. slå samman liknande regler;
4. korta exempel;
5. behåll kritiska stoppregler;
6. behåll det godkända huvudflödet;
7. räkna tecknen igen maskinellt.

Kapa aldrig på måfå.

## 13. Självkontroll

En bra instruktion ska kunna svara på:

- Vem är GPT:n?
- Vad ska den åstadkomma?
- Vem hjälper den?
- Vad gör den först?
- När söker den?
- När frågar den?
- När bygger den?
- När stoppar den?
- Vilka filer ska den skapa?
- Hur vet man att den lyckats?

Om något av detta är oklart behöver instruktionen förbättras.
