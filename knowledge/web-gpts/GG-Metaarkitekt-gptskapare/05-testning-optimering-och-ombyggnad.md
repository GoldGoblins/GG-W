# Testning, optimering och ombyggnad

## 1. Syfte

En GPT ska inte kallas förbättrad bara för att instruktionen blivit längre. Förbättring ska visas genom testning mot samma uppgifter och tydliga kriterier.

## 2. Testnivåer

### Nivå 1 — struktur

Kontrollera:

- instruktionen under teckengränsen;
- alla obligatoriska filer;
- fungerande ZIP;
- inga tomma filer;
- rätt interna filnamn;
- manifest och checksummor.

### Nivå 2 — identitet

Testa om GPT:n:

- beskriver sitt namn korrekt;
- håller fast vid huvudsyftet;
- använder rätt tonalitet;
- hjälper rätt målgrupp;
- inte tappar kärnlöftet.

### Nivå 3 — arbetsflöde

Testa om GPT:n:

- analyserar underlag före byggande;
- identifierar luckor;
- gör research när den behövs;
- ställer en välgrundad fråga;
- presenterar GPT-kontrakt;
- väntar på **godkänd**;
- bygger efter godkännande.

### Nivå 4 — verktyg

Testa:

- webbsökning när fakta är aktuella;
- filanalys när underlag laddats upp;
- verklig filgenerering;
- ZIP;
- att Actions inte föreslås utan behov;
- att GPT:n säger sanningen när ett verktyg misslyckas.

### Nivå 5 — gränsfall

Exempel:

- motsägande krav;
- mycket tunt idéunderlag;
- gammal kunskapsfil;
- felaktig källa;
- önskemål om fler än nödvändiga funktioner;
- hemlighet i uppladdad konfiguration;
- användaren godkänner bara delar;
- befintlig GPT saknar tydlig identitet.

### Nivå 6 — säkerhet

Testa om GPT:n:

- undviker hemligheter i paket;
- skiljer read-only från extern handling;
- stoppar vid riskfylld Action;
- markerar osäkerhet;
- inte hittar på källor;
- bevarar användarens beslut.

## 3. Testfallsformat

```text
Test-ID:
Syfte:
Indata:
Förväntat beteende:
Förbjudet beteende:
Godkänt när:
Resultat:
```

## 4. Minsta testsvit för ny GPT

1. Normal, tydlig uppgift.
2. Ofullständig uppgift.
3. Aktuell fakta krävs.
4. Felaktigt antagande från användaren.
5. Verktyg saknas.
6. Förfrågan utanför omfattningen.
7. Säkerhets- eller integritetsgräns.
8. Leveransformat.
9. Tonalitet.
10. Självkorrigering efter rättelse.

## 5. Jämförande test vid ombyggnad

Kör samma testfall mot gammal och ny version.

Mät till exempel:

- om uppgiften slutförs;
- antal onödiga följdfrågor;
- antal felaktiga antaganden;
- följsamhet till identitet;
- källkvalitet;
- korrekt verktygsanvändning;
- formatprecision;
- stopp vid risk;
- användbarhet;
- konsistens över flera körningar.

## 6. Optimal ombyggnadsprocess

### Steg 1 — inventering

Samla:

- nuvarande Instructions;
- Knowledge;
- inställningar;
- capabilities;
- Actions;
- konversationsstartare;
- testfall;
- problemrapporter;
- användarfeedback.

### Steg 2 — identitetsutvinning

Skriv ned:

- namn;
- huvudsyfte;
- kärnvärderingar;
- tonalitet;
- målgrupp;
- kärnlöfte.

Be användaren bekräfta om identiteten är oklar.

### Steg 3 — bristanalys

Leta efter:

- motsägande instruktioner;
- överlapp;
- döda regler;
- otydliga utlösare;
- för många absoluta regler;
- viktiga regler som bara ligger i Knowledge;
- föråldrade fakta;
- verktyg utan behov;
- saknade stoppvillkor;
- svaga testkriterier;
- instruktioner som beskriver mål men inte metod.

### Steg 4 — målarkitektur

Föreslå:

- ny instruktionsstruktur;
- Knowledge-indelning;
- capabilities;
- säkerhetsgränser;
- teststrategi;
- migrering.

Presentera detta i GPT-kontraktet.

### Steg 5 — ombyggnad

Efter godkännande:

- skriv om Instructions;
- omstrukturera Knowledge;
- ta bort onödig duplicering;
- lägg till saknade mallar;
- skapa tester;
- skapa README;
- skapa CHANGELOG;
- skapa MIGRERING;
- skapa manifest och ZIP.

### Steg 6 — jämförelse

Dokumentera:

- bevarat;
- ändrat;
- borttaget;
- tillagt;
- varför;
- testresultat.

## 7. “Steroideffekt” utan överbyggnad

En verklig boost kommer ofta från:

- bättre beslutspunkter;
- bättre researchfrågor;
- tydligare scope;
- rätt verktyg;
- bättre Knowledge;
- starkare testning;
- färre motsägelser;
- bättre stoppregler;
- explicit leveransformat.

Inte från:

- fler adjektiv;
- upprepning;
- överdrivna roller;
- orealistiska påståenden om expertis;
- automatisk aktivering av alla verktyg.

## 8. Kvalitetspoäng

En intern poängmodell kan användas från 0–2 per område:

- identitet;
- uppdrag;
- målgrupp;
- huvudflöde;
- frågelogik;
- research;
- verktyg;
- Knowledge;
- säkerhet;
- leverans;
- testbarhet;
- underhållbarhet.

0 = saknas eller är motsägande.  
1 = finns men är svagt.  
2 = tydligt och testbart.

Poängen är ett analysverktyg, inte ett bevis i sig.

## 9. Regressionskontroll

Efter en förbättring ska GPT:n inte tappa sådant den redan gjorde bra.

Skapa därför testfall för:

- kärnuppgiften;
- signaturtonaliteten;
- viktiga specialregler;
- vanliga användarflöden;
- tidigare lösta fel.

## 10. Leveransrapport

Slutrapporten ska ange:

1. vad som skapades;
2. hur det följer GPT-kontraktet;
3. exakt instruktionsteckenantal;
4. antal Knowledge-filer;
5. vilka tester som kördes;
6. om ZIP verifierades;
7. kvarvarande begränsningar;
8. nästa logiska steg.

## 11. Misslyckad test

Vid testfel:

- rätta den berörda delen;
- kör testet igen;
- kontrollera regression;
- dokumentera avvikelsen;
- påstå inte att allt är godkänt om ett kritiskt test återstår.

## 12. Test av klickbar filleverans

Filleveransen är ett eget kritiskt testområde.

Kontrollera att:

- alla utlovade filer har skapats som verkliga filer;
- varje fil kan öppnas före länkning;
- instruktionens teckenantal har räknats maskinellt;
- ZIP-filen kan öppnas och `testzip()` eller motsvarande kontroll är godkänd;
- ZIP innehåller rätt mappstruktur och alla obligatoriska filer;
- varje länk pekar på den skapade filen i den aktiva arbetsmiljön;
- användaren inte behöver köra Python, terminalkommandon eller byggskript;
- stora kodblock inte används som ersättning när filskapande fungerar;
- inga gamla filer presenteras som den nya versionen;
- ett faktiskt filskapandeförsök görs innan reservleverans används.

Ett paket är underkänt om länkarna ser korrekta ut men filerna saknas, är gamla, inte kan öppnas eller inte motsvarar manifestet.

## 13. Observerbara leveranskriterier

Godkänd slutleverans ska kunna verifieras av användaren genom att:

1. klicka på ZIP-länken;
2. ladda ned och öppna ZIP-filen;
3. klicka på enskilda fillänkar;
4. se samma filnamn och versioner som i README och manifest;
5. installera paketet utan att återskapa filer från chatten.

Om något av detta inte kan uppfyllas ska GPT:n beskriva leveransen som ofullständig.
