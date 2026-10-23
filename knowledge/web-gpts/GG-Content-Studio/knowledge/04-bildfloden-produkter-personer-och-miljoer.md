# Bildflöden för produkter, människor och miljöer

**Version:** 1.1.0

## Syfte

Praktiska arbetsflöden som gör GPT:n snabb utan att hoppa över produktintegritet, referenshierarki och sanningskontroll.

## Gemensam start

För varje bilduppdrag:

1. Fastställ Säljbild eller Konceptbild.
2. Identifiera målprodukt, person eller miljö.
3. Ange vad som måste bevaras.
4. Välj slutformat.
5. Välj en huvudreferens och högst en stödreferens från `07-visuellt-referensbibliotek.md`.
6. Använd stilreferensen för atmosfär, inte produktdesign.
7. Kontrollera resultatet mot målbilden.

## Flöde A — Redigera verklig produktbild

### Minsta indata

- uppladdad produktbild;
- önskad kanal eller format;
- önskad känsla om annan än Gold Goblins Studio Look.

### Arbetsgång

1. Klassificera som Säljbild.
2. Lista internt produktdetaljer som måste bevaras.
3. Bedöm om målbilden räcker; be bara om ny vinkel när en kritisk detalj inte kan verifieras.
4. Välj relevant REF-bild:
   - makro/gravyr: REF-01;
   - handpresentation: REF-02;
   - stenar/sammet: REF-04;
   - kedjor/komponenter: REF-05;
   - äldre silver/återbruksmood: REF-06.
5. Redigera bara ljus, miljö, skuggor, komposition, rekvisita och format.
6. Jämför resultatet mot originalet.
7. Leverera klassificering och format.

### Standardbrief

> Bevara smycket exakt. Ändra endast bakgrund, ljus, skuggor, komposition och återhållsam rekvisita. Hämta värme, kontrast och materialkänsla från vald REF-bild utan att överföra dess produktdesign.

## Flöde B — Skapa produktkoncept

1. Klassificera som Konceptbild.
2. Identifiera inspirationsriktning och kampanjmål.
3. Välj en relevant REF-bild för stämning.
4. Skapa en fri visualisering.
5. Lägg konceptmärkning i tillhörande text.
6. Undvik pris, lagerstatus och andra produktfakta.
7. Beskriv designval som idéer, inte tillverkningsspecifikationer.

## Flöde C — Personalporträtt

### Krav

En referensbild av personen måste finnas i den aktuella konversationen.

### Arbetsgång

1. Bevara identitet, ålder, hudton och naturliga kännetecken.
2. Välj Human Craft eller Workshop Truth.
3. Använd REF-02 för mjuk hand-/hudkänsla eller REF-03 för dokumentär verkstad.
4. Använd ett verkligt smycke endast när dess egen produktreferens finns.
5. Retuschera varsamt.
6. Kontrollera ansikte, händer, smycke och ljus.

## Flöde D — Händer med smycke

1. Kontrollera rätt hand, finger och produktplacering.
2. Se till att smycket inte smälter ihop med huden.
3. Undvik extra fingrar, fel leder och onaturligt grepp.
4. Bevara smyckets proportioner.
5. Använd REF-02 för lågmäld presentation eller REF-03 för arbete.
6. Prioritera naturlig hudton och kontrollerade reflektioner.

## Flöde E — Verkstad och process

1. Avgör om bilden är dokumentär eller iscensatt.
2. Dokumentär: bevara verklig miljö och arbetsmoment.
3. Iscensatt: använd relevant men sparsam rekvisita.
4. Välj REF-01 för precision, REF-03 för händer eller REF-05 för komponentstilleben.
5. Visa trovärdig handposition och verktygsrelation.
6. Hitta inte på certifieringar, maskiner, tekniker eller processer.
7. Märk som kampanj- eller konceptbild när dokumentär status kan missförstås.

## Flöde F — Kampanjkomposition

Kan kombinera:

- produkt;
- människa;
- verkstad;
- material;
- kort budskap;
- säsong eller lansering.

Arbetsgång:

1. Bestäm huvudmotiv.
2. Avgör om produkten är verklig eller koncept.
3. Säkra aktuella produkt- och personreferenser.
4. Välj en huvud-REF och högst en stöd-REF.
5. Bestäm negativt utrymme och format.
6. Skapa en sammanhållen bild utan att kopiera objekt från stilreferensen.
7. Kontrollera att caption inte gör påhittade påståenden.

## Flöde G — Material- och stenpresentation

1. Verifiera vad materialen faktiskt är.
2. Använd REF-04 för djupgrön sammet och organiserad färg.
3. Använd REF-05 eller REF-06 för metall, komponenter och patina.
4. Undvik att gissa stenart, halt, vikt eller värde.
5. Visa inte en stilreferens som om den vore aktuellt lager.

## Flöde H — Flera format

### 1:1

Fokuserad produkt eller tät detalj. Håll viktig information inom kvadraten.

### 4:5

Standard för flödesinlägg. Bygg en vertikal komposition med plats för produkt eller händer.

### 9:16

Planera från början för vertikal användning. Lämna säkra ytor för gränssnitt och eventuell text. Använd REF-05 som vertikal inspiration när motivet passar.

Skapa separata kompositioner; beskär inte blint.

## Flöde I — Variationer

När användaren ber om flera bilder:

- behåll samma produkt och stilfamilj;
- variera utsnitt, ljusriktning, bakgrund eller referensval;
- undvik nästan identiska bilder;
- håll metall och produktfakta konsekventa;
- märk konceptstatus konsekvent.

## Leveransformat

### Endast bild

- bild;
- `Säljbild` eller `Konceptbild`;
- format;
- eventuell konceptmärkning.

### Komplett socialt inlägg

- bild;
- klassificering och format;
- hook;
- caption;
- CTA;
- alt-text;
- eventuella formatvarianter.

### När bildverktyget misslyckas

- säg att ingen bild skapades;
- ange vad som misslyckades;
- lämna en förbättrad brief eller prompt för nytt försök;
- påstå inte att resultatet är renderat.
