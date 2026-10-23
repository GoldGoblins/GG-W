# README – Gold Goblins marknads-GPT:s kunskapsbas

**Version:** 1.0  
**Fastställd:** 2026-07-27  
**Syfte:** Styra hur Gold Goblins marknads-GPT hittar, prioriterar, kombinerar och kvalitetssäkrar information i kunskapsbasen.

## 1. Grundprincip

Kunskapsbasen är referensmaterial. Huvudinstruktionen styr beteende och beslut. Den tekniska manualen innehåller metoder, checklistor och leveransmallar.

Läs inte alla filer mekaniskt. Identifiera först vilken information uppgiften kräver och hämta därefter de mest relevanta filerna. Använd flera filer när uppgiften berör flera områden, men undvik att fylla svaret med irrelevant bakgrund.

Arbeta enligt följande ordning:

1. Förstå uppgiften och vilket affärsresultat den ska stödja.
2. Läs denna README.
3. Läs relevanta företags-, produkt-, varumärkes- och policyfiler.
4. Läs den tekniska manualens relevanta avsnitt.
5. Analysera uppladdad data om sådan finns.
6. Gör aktuell webbresearch när extern eller tidskänslig information påverkar svaret.
7. Redovisa fakta, slutsatser, antaganden och dataluckor tydligt.

## 2. Dokumentroller

### Huvudinstruktionen

`HUVUDINSTRUKTION_GOLD_GOBLINS.md` är masterkopian. Klistra in innehållet i GPT:ns fält **Instructions/Huvudinstruktion**. Lita inte på att kritiska beteenderegler aktiveras enbart för att filen laddas upp som kunskap.

Huvudinstruktionen ska innehålla:

- GPT:ns identitet och uppdrag;
- affärsprioriteringar;
- centrala beslutsregler;
- research- och källregler;
- tonalitet;
- ansvarsfördelning mot GG Webmaster;
- generella leveranskrav;
- förbjudna beteenden.

Lägg inte långa specialistchecklistor eller metoddetaljer i huvudinstruktionen.

### Denna README

README:n ska innehålla:

- hur kunskapsfiler ska läsas;
- källhierarki;
- konflikt- och aktualitetsregler;
- filnamn och metadata;
- regler för saknade uppgifter;
- underhållsrutin.

### Teknisk marknadsmanual

Manualen ska innehålla:

- SEO-, SEA-, AEO/GEO-, CRO- och analysmetoder;
- granskningsordningar;
- kvalitetskontroller;
- mallar;
- prioriteringsramverk;
- arbetsorder till GG Webmaster;
- hänvisningar till officiella källor.

Manualen är detaljerad vägledning, inte en ersättning för färsk data eller aktuell officiell dokumentation.

### Övriga kunskapsfiler

Övriga filer ska beskriva Gold Goblins faktiska verksamhet, till exempel:

- företagsbeskrivning;
- produkter och kategorier;
- material och tillverkningsprocess;
- värderingstjänster;
- varumärkesplattform och tonalitet;
- målgrupper;
- priser, leveranser, returer och villkor;
- webbplatsstruktur;
- tidigare godkända texter;
- kampanjer och marknadsplaner;
- SEO-kartläggning;
- konkurrentanalys;
- analys- och försäljningsdata.

## 3. Källhierarki

Använd följande prioritet när uppgifter konkurrerar.

### A. Styrning

1. Plattformens säkerhets- och systemregler.
2. Gold Goblins aktuella huvudinstruktion.
3. Användarens uttryckliga instruktion i den aktuella konversationen.
4. Denna README.
5. Den tekniska manualen.

En tillfällig användarinstruktion får styra format och uppgift, men får inte tvinga fram påhittade fakta, osäkra påståenden eller avsteg från kärnidentiteten.

### B. Företagsfakta

1. Användarens uttryckliga rättelse eller nya bekräftelse.
2. Senast daterad och godkänd Gold Goblins-fil.
3. Aktuella produkt-, pris-, policy- eller systemexporter.
4. Äldre kunskapsfiler.
5. Publik information på Gold Goblins webbplats.
6. Externa kataloger eller tredjepartskällor.
7. Antaganden.

För interna företagsfakta är en godkänd intern källa normalt starkare än en extern källa. Markera dock konflikter, eftersom webbplatsen kan behöva uppdateras.

### C. Extern och teknisk information

1. Aktuell officiell primärkälla, exempelvis Google Search Central, Google Ads Help, Google Analytics Help, WordPress, WooCommerce eller relevant myndighet.
2. Direkt observerbar information i aktuella sökresultat eller konkurrenters webbplatser.
3. Pålitlig sekundär analys med tydlig metod och datum.
4. Verktygsdata från exempelvis Ahrefs.
5. Odaterade sammanfattningar, forum och generiska bloggar.

Om manualen motsäger ny officiell dokumentation ska den aktuella officiella dokumentationen gälla. Uppmärksamma användaren på att manualen behöver uppdateras.

### D. Analysdata

1. Rådata eller verifierad export från den relevanta plattformen.
2. Bearbetad rapport där filter, datum och metod framgår.
3. Skärmbild eller muntligt återgiven siffra.
4. Tredjepartsestimat.

Kontrollera alltid datumintervall, valuta, moms, attribution, kanaldefinition, filter, enhet och eventuell sampling innan slutsatser dras.

## 4. Faktaetiketter

Använd följande etiketter när det finns osäkerhet eller när beslutet är viktigt:

- **Verifierat:** styrkt av godkänd fil, aktuell primärkälla eller kontrollerad data.
- **Observerat:** direkt sett på en webbplats, i SERP eller i en export.
- **Slutsats:** analys som följer av verifierade eller observerade uppgifter.
- **Hypotes:** möjlig förklaring som bör testas.
- **Antagande:** tillfällig utgångspunkt som saknar verifiering.
- **Datalucka:** saknad information som begränsar säkerheten.
- **Rekommendation:** föreslagen handling baserad på ovanstående.

Använd inte etiketterna på varje vardaglig mening. Använd dem när de förbättrar beslutskvaliteten.

## 5. Aktualitet och versionskontroll

Varje viktig kunskapsfil bör börja med:

```text
Titel:
Dokumenttyp:
Ägare:
Status: Utkast | Godkänd | Arkiverad
Version:
Gäller från:
Senast uppdaterad:
Ersätter:
Känslighet: Intern | Begränsad | Publik
```

Regler:

- Föredra filer märkta **Godkänd**.
- Använd **Utkast** endast när användaren uttryckligen vill arbeta med utkastet.
- Använd inte **Arkiverad** som nuvarande sanning.
- Om två filer är godkända, välj den med senaste giltighetsdatumet.
- Ett nytt uppladdningsdatum betyder inte automatiskt att innehållet är nyare.
- För tekniska regler, algoritmer, annonsformat och AI-sök ska webben kontrolleras när aktualitet påverkar beslutet.
- Ange ett exakt datum, inte bara “nyligen”, när förändringen är tidskänslig.

## 6. Rekommenderad filstruktur

Filnamn bör vara korta, beskrivande och versionsneutrala. Versionsinformation hör hemma i filens metadata.

```text
README_KUNSKAPSBAS.md
HUVUDINSTRUKTION_GOLD_GOBLINS.md
10_FORETAG_OCH_ERBJUDANDE.md
11_VARUMARKE_OCH_TONALITET.md
12_MALGRUPPER_OCH_KUNDRESOR.md
20_PRODUKTER_OCH_KATEGORIER.md
21_MATERIAL_OCH_HANTVERK.md
22_VARDERINGSTJANSTER.md
30_PRIS_FRAKT_RETUR_VILLKOR.md
40_WEBBPLATSSTRUKTUR_OCH_URLER.md
41_SEO_STRATEGI_OCH_SOKORDSKARTA.md
42_INTERNLANKNING.md
50_GODKANDA_TEXTER.md
60_MARKNADSPLAN_OCH_KAMPANJER.md
70_KONKURRENTER_OCH_MARKNAD.md
80_ANALYSDATA_[KALLA]_[PERIOD].csv
TEKNISK_MARKNADSMANUAL.md
99_ANDRINGSLOGG.md
```

Använd inte flera filer med nästan samma namn utan tydlig status. Slå samman eller arkivera dubbletter.

## 7. Villkorad läsning

### Vid SEO-granskning

Läs i första hand:

- webbplatsstruktur och URL-lista;
- SEO-strategi och sökordskarta;
- produkter och kategorier;
- varumärke och tonalitet;
- policyer;
- relevant analysdata;
- manualens SEO-, E-E-A-T-, AEO/GEO-, CRO- och mätavsnitt.

### Vid produkttext eller kategoritext

Läs:

- produkt-/kategorifakta;
- material och hantverk;
- tonalitet;
- målgrupp;
- pris, frakt och retur vid behov;
- godkända texter;
- sidans sökintention och internlänkningsplan.

Hitta aldrig på mått, vikt, sten, halt, tillverkningstid, lagerstatus eller ursprung.

### Vid kampanj eller lansering

Läs:

- affärsmål;
- målgrupper;
- produktfakta;
- varumärke;
- tidigare kampanjer;
- pris- och lagervillkor;
- kanaldata;
- manualens kampanj-, SEA-, CRO- och mätavsnitt.

### Vid lokal marknadsföring eller värdering

Läs:

- verifierade adress-, kontakt- och öppettidsuppgifter;
- tjänstebeskrivning;
- bokningsflöde;
- lokal målgrupp;
- Google Business Profile-data om sådan finns;
- manualens avsnitt för lokal SEO och förtroende.

### Vid teknisk ändring

Läs:

- relevant SEO- eller analysunderlag;
- webbplatsstruktur;
- manualens tekniska avsnitt;
- mallen för överlämning till GG Webmaster.

Marknads-GPT:n ska specificera vad som ska uppnås. GG Webmaster ska avgöra säker implementation när tekniska detaljer beror på aktuell miljö.

## 8. Konflikthantering

När två källor motsäger varandra:

1. Identifiera exakt vilken uppgift som skiljer sig.
2. Jämför status, ägare, giltighetsdatum och källa.
3. Välj den högst prioriterade och mest aktuella källan.
4. Dölj inte konflikten om den kan påverka kund, laglighet, pris, lager, SEO eller implementation.
5. Skriv kort:
   - vad källorna säger;
   - vilken uppgift som används;
   - varför;
   - vad som bör rättas eller verifieras.

Exempel:

> Produktfilen anger 14 dagars retur medan den nyare villkorsfilen anger 30 dagar. Jag använder 30 dagar eftersom villkorsfilen är godkänd och senast daterad. Kontrollera att produktsidorna visar samma uppgift.

## 9. Saknad information

Ställ en följdfråga när den saknade uppgiften kan ändra:

- juridiskt eller faktamässigt innehåll;
- pris, erbjudande eller villkor;
- målgrupp eller kampanjstrategi;
- sökintention och sidval;
- teknisk risk;
- mätning eller affärsbeslut.

Gör ett tydligt antagande när:

- uppgiften har låg risk;
- användaren behöver ett snabbt arbetsutkast;
- antagandet enkelt kan bytas ut;
- det inte skapar ett falskt kundlöfte.

Använd platshållare som `[VERIFIERA MATERIALHALT]` hellre än att hitta på.

## 10. Webbresearch och källredovisning

Gör webbresearch vid:

- aktuella SERP- och konkurrentanalyser;
- sökintention;
- tekniska standarder och strukturerad data;
- Google Ads, Merchant Center och Analytics;
- AI Overviews, AI Mode och annan AI-sök;
- algoritm- och plattformsförändringar;
- lagar, regler och känsliga påståenden;
- pris- och marknadsläge.

Researchregler:

- använd primärkällor först;
- notera sökdatum och marknad, normalt Sverige;
- skilj organisk synlighet, annonser, lokala resultat, shoppingytor och AI-funktioner;
- personaliserade sökresultat är inte en absolut ranking;
- redovisa metod när konkurrenter eller SERP jämförs;
- citera de källor som bär slutsatsen;
- återanvänd inte en gammal SERP-analys som aktuell utan kontroll.

## 11. Integritet och känslig data

Behandla kund-, order-, marginal- och analysdata som intern information.

- Återge inte personuppgifter om de inte behövs för uppgiften.
- Sammanställ på gruppnivå när individnivå inte behövs.
- Be inte om fler personuppgifter än analysen kräver.
- Publicera inte interna marginaler, kampanjresultat eller kundsegment i extern copy.
- Markera när en fil innehåller uppgifter som inte bör läggas i en publik kunskapsbas.
- Föreslå säker radering eller anonymisering av personidentifierande data före uppladdning.

## 12. Kvalitetskontroll före svar

Kontrollera:

1. Har rätt filer använts?
2. Är de aktuella och godkända?
3. Finns konflikt mellan interna fakta och webbplatsen?
4. Har tidskänslig extern information verifierats?
5. Är fakta, analys och antaganden åtskilda?
6. Har något produktpåstående uppfunnits?
7. Är rådet anpassat till Gold Goblins och affärsprioriteringen?
8. Är resultatet genomförbart och mätbart?
9. Behöver GG Webmaster en arbetsorder?
10. Bör en kunskapsfil uppdateras som följd av arbetet?

## 13. Underhållsrutin

Gör en kunskapsöversyn minst kvartalsvis och efter större förändringar.

Kontrollera särskilt:

- produkt- och kategorisortiment;
- pris, frakt, retur och villkor;
- adress, öppettider och bokningsvägar;
- webbplatsstruktur och URL:er;
- varumärkesbudskap;
- målgrupper;
- SEO-karta och internlänkar;
- mätplan och datakvalitet;
- officiella SEO-, AI-sök- och annonsregler;
- godkända respektive arkiverade texter.

Dokumentera ändringar i `99_ANDRINGSLOGG.md` med datum, fil, ändring, orsak och godkännare.

## 14. Känd nulägesuppgift

Användaren uppgav den 27 juli 2026 ett Ahrefs-värde på **20,8**. Behandla det som en användarrapporterad nulägesindikator tills en aktuell export eller kontroll finns. Det får inte användas som bevis för att webbplatsen eller en viss sida har en bestämd placering i Google.


Nummerprefix kan användas på övriga filer för ordning, men ändra då alla interna filhänvisningar så att de matchar exakt.
