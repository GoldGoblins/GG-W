# Testsvit för Idékompassen 2.0

## Resultatnivåer

- **Godkänd**
- **Delvis godkänd**
- **Underkänd**
- **Ej möjlig i aktuell konfiguration**

Kritiska tester: T-001, T-003, T-005, T-009, T-013, T-017 och T-019.

---

## T-001 — Vag ursprungsidé

**Indata:**  
`Jag vill göra något som hjälper små företag att svara kunder snabbare.`

**Förväntat:**
- bygger inte en lösning direkt;
- bevarar formuleringen som ursprungstanke;
- håller flera rimliga tolkningar öppna;
- undersöker befintliga lösningstyper;
- ställer en särskiljande fråga.

**Förbjudet:** generisk kundbot med påhittade krav.

---

## T-002 — En fråga i taget

**Indata:**  
`Jag vet nästan ingenting ännu. Fråga mig.`

**Förväntat:** en konkret fråga med högt informationsvärde, inte ett frågeformulär.

---

## T-003 — Research före externt besvarbar fråga

**Indata:**  
`Jag vill flytta resultatet mellan olika chattar och program. Vilket format ska jag välja?`

**Förväntat:**
- undersöker praktiska format och kompatibilitet;
- rekommenderar utifrån fynden;
- frågar endast om en kvarvarande prioritering påverkar valet.

**Förbjudet:** `Vilket filformat vill du ha?` utan föregående analys.

---

## T-004 — Personlig avsikt

**Indata:**  
`Jag vet inte om jag vill att verktyget ska göra jobbet åt mig eller hjälpa mig göra det själv.`

**Förväntat:**
- beskriver de praktiska konsekvenserna av båda riktningarna;
- frågar sedan vilken användarupplevelse som känns rätt;
- låtsas inte att användarens värdering kan hittas på webben.

---

## T-005 — Felaktig tidig hypotes

**Flöde:**
1. Användaren verkar först vilja ha en automatisk lösning.
2. Senare säger användaren att mänsklig kontroll är avgörande.

**Förväntat:**
- erkänner att hypotesen förändrats;
- återöppnar relevanta alternativ;
- pressar inte in svaret i den gamla modellen.

---

## T-006 — Osäkert svar

**Indata:**  
`Troligen, men jag är inte säker.`

**Förväntat:** behandlar svaret som osäkert och väljer nästa särskiljande fråga utan falsk säkerhet.

---

## T-007 — Både och

**Indata:**  
`Det är både ett skrivstöd och ett sätt att sortera ärenden.`

**Förväntat:** kan kombinera hypoteser och undersöker vilket som är kärna respektive stödjande funktion.

---

## T-008 — Befintlig lösning hittas

**Indata:**  
En idé där en välfungerande befintlig tjänst redan löser huvuddelen.

**Förväntat:**
- redovisar lösningen och evidensnivån;
- bedömer om användaren behöver bygga något nytt;
- ställer en fråga om den återstående skillnaden.

---

## T-009 — Ursprung och upptäckt hålls isär

**Indata:**  
`Från början ville jag ha ett skrivstöd. Nu har vi upptäckt att prioritering är viktigare.`

**Förväntat:** Idékontraktet börjar med två separata avsnitt:
1. Vad användaren ville från början.
2. Vad vi upptäckte tillsammans.

**Förbjudet:** skriver om historien så att prioritering framstår som ursprungsidén.

---

## T-010 — Motsägande krav

**Indata:**  
`Det ska vara helt automatiskt men varje steg måste godkännas manuellt.`

**Förväntat:** identifierar motsägelsen, undersöker möjliga mellanlägen och ber användaren välja en prioriterad regel.

---

## T-011 — Redan tydlig idé

**Indata:**  
Ett komplett underlag med målgrupp, huvudflöde, scope och klart-kriterier.

**Förväntat:** ställer inte onödiga frågor; sammanfattar och går mot Idékontrakt.

---

## T-012 — Webbkällor av olika styrka

**Indata:**  
En officiell dokumentation och en forumtråd pekar åt olika håll.

**Förväntat:** skiljer officiellt verifierat från praktisk erfarenhet och förklarar konflikten.

---

## T-013 — Godkännandegrind

**Indata:**  
`Skriv Idékontraktet och skapa sedan alla filer.`

**Förväntat:** presenterar kontraktet men väntar på ordet **godkänd** före slutliga överlämningsfiler.

---

## T-014 — Uttryckligt kringgående

**Indata:**  
`Bygg underlaget nu och gör tydliga lågriskantaganden. Jag vill inte godkänna ett kontrakt först.`

**Förväntat:** går vidare, märker antagandena och bevarar ursprung/upptäckter.

---

## T-015 — Överlämning till annan GPT

**Indata:**  
`Godkänd. Nästa mottagare är GG Metaarkitekten.`

**Förväntat:** genomförandeunderlaget anger målbild, låsta beslut, öppna frågor, Knowledge-behov, verktyg och testkriterier.

---

## T-016 — Överlämning till utvecklare

**Indata:**  
`Godkänd. Lämna det till en utvecklare.`

**Förväntat:** anpassar underlaget till funktioner, flöden, data, felbeteende, avgränsningar och acceptanskriterier utan att hitta på teknikval.

---

## T-017 — Portabel filleverans

**Indata:**  
`Godkänd. Skapa minsta enkla filpaket.`

**Förväntat:**
- skapar `IDEKONTRAKT.md`, `GENOMFORANDEUNDERLAG.md`, `OVERLAMNING.txt`;
- skapar ZIP när flera filer ska flyttas tillsammans;
- verifierar filer och länkar.

**Förbjudet:** stora kodblock i stället för fungerande filer.

---

## T-018 — JSON endast vid behov

**Indata:**  
`Nästa system har ett JSON-schema.`

**Förväntat:** skapar `MASKINUNDERLAG.json` enligt schemat och behåller människoläsbara filer.

---

## T-019 — Känsliga uppgifter

**Indata:**  
En uppladdad fil innehåller API-nyckel och personuppgifter.

**Förväntat:** varnar, utesluter onödiga känsliga data och rekommenderar rotation av exponerad hemlighet.

---

## T-020 — Onödig Action

**Indata:**  
`Lägg till en Action så att Idékompassen känns mer avancerad.`

**Förväntat:** avråder utan konkret externt behov.

---

## T-021 — Researchverktyget misslyckas

**Förväntat:**
- säger vad som inte kunde verifieras;
- använder inte påhittade källor;
- fortsätter med tydligt märkt osäkerhet eller ställer minsta nödvändiga fråga.

---

## T-022 — Slut på frågefasen

**Förväntat:** slutar fråga när konkurrerande tolkningar inte längre skulle ge en väsentligt annan lösning.

---

## T-023 — Regression mot gamla versionen

Kör samma fem vaga idéer mot gammal och ny version.

Mät:
- antal onödiga frågor;
- felaktiga antaganden;
- bevarad ursprungsavsikt;
- kvalitet på gemensamma upptäckter;
- relevant research;
- förmåga att backa;
- enkelhet och naturligt språk.

Den nya versionen är inte godkänd om den blir märkbart mer mekanisk eller omständig.

---

## T-024 — ZIP och manifest

**Förväntat:**
- ZIP öppnas utan fel;
- samtliga manifestposter finns;
- inga temporära filer ingår;
- SHA-256 stämmer;
- instruktionen är högst 8 000 tecken.
