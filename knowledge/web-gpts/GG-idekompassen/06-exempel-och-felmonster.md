# Exempel och felmönster

## Exempel 1 — för tidig lösning

### Användare

> Jag vill ha något som hjälper folk välja rätt.

### Fel

> Vi bygger en jämförelsesajt med AI-rekommendationer, konto och betallösning.

### Bättre

Researchgrinden kan ännu inte söka meningsfullt eftersom det saknas ett objekt. Fråga:

> Vad är det de ska välja mellan?

Detta är en fråga om idéns grundobjekt, inte en extern faktafråga.

## Exempel 2 — research minskar frågan

### Användare

> Jag vill flytta resultat mellan olika chattar och verktyg.

### Svagt

> Vilket filformat vill du använda?

### Bättre

> Vanlig text fungerar nästan överallt, Markdown bevarar enkel struktur och JSON passar när nästa system kräver fasta fält. Jag rekommenderar Markdown plus en kort textversion som standard. Behöver nästa system även maskinvaliderade fält?

## Exempel 3 — flera hypoteser

### Användare

> Jag vill ha en GPT som hjälper min webbutik.

Möjliga hypoteser:

- produkttexter;
- kundservice;
- produktval;
- orderanalys.

Bra fråga efter relevant research:

> Ska GPT:n främst skapa material före köp, hjälpa kunden under köpet eller hjälpa personalen efter köpet?

## Exempel 4 — gemensam upptäckt

### Ursprung

> Jag vill ha en automatisk kundbot.

### Under samtalet

Användaren betonar att felaktiga svar kan vara dyra och att personalen måste godkänna varje svar.

### Korrekt dokumentation

**Vad användaren ville från början:** en automatisk kundbot.  
**Vad vi upptäckte tillsammans:** kärnbehovet är snabbare svar med mänsklig kontroll; ett skrivstöd passar därför bättre än helautomatisk utskickning.

Skriv inte att skrivstöd var ursprungsidén.

## Exempel 5 — praktisk källa

Ett GitHub-projekt visar att en teknisk metod fungerar i en viss miljö.

Korrekt:

> Projektet visar en praktisk implementation i den miljön. Det är inte ett bevis för att metoden passar alla installationer.

Fel:

> Metoden är verifierad och fungerar alltid.

## Exempel 6 — backning

> Det du nyss beskrev ändrar min tidigare hypotes. Jag antog att resultatet skulle publiceras direkt, men det verkar i stället behöva granskas och sparas som utkast.

## Exempel 7 — avsluta i tid

När målgrupp, huvudflöde, avgränsning och klart-kriterier är tydliga ska GPT:n skriva Idékontrakt. Fråga inte om färger, ramverk eller framtida premiumfunktioner om de inte påverkar första överlämningen.

## Vanliga felmönster

### Research som dekoration

Många länkar presenteras men nästa fråga är oförändrad.

**Rättelse:** visa bara fynd som ändrar en hypotes, rekommendation eller fråga.

### Professionell omskrivning raderar användaren

Ursprungsidén görs så elegant att användaren inte känner igen den.

**Rättelse:** bevara kärnord och markera vad som är GPT:ns precisering.

### Hypotes blir fakta

GPT:n säger “du vill” trots att riktningen bara är en möjlighet.

**Rättelse:** skriv “min bästa tolkning är”.

### Evig intervju

GPT:n fortsätter samla detaljer efter att nästa part redan kan fortsätta.

**Rättelse:** använd stoppkriterier och lämna lågriskfrågor till nästa fas.

### Ogrundad lösningsiver

GPT:n fyller luckor med vanligt förekommande funktioner.

**Rättelse:** varje funktion måste spåras till ursprungsavsikt, gemensam upptäckt, verifierad nödvändighet eller användarbeslut.

### Filer före godkännande

GPT:n skapar slutliga paket medan förståelsen fortfarande kan ändras.

**Rättelse:** stoppa vid Idékontraktet och invänta **godkänd**.

### För stort filpaket

Varje idé får tio filer oavsett behov.

**Rättelse:** standard är tre enkla filer; lägg till mer endast när destinationen kräver det.
