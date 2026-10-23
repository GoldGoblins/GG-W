# Ändringslogg

## Version 1.1.0 — 2026-07-28

### Bevarat

- namnet **Gold Goblins Content Studio**;
- huvudsyftet som intern kreativ studio för sociala medier;
- kärnprincipen **Sann produkt först. Stark bild därefter.**;
- varm, mörk och hantverksnära tonalitet;
- Säljbild/Konceptbild-gränsen;
- produktintegritet, personreferenskrav och säkerhetsgränser;
- social copy och produktionsunderlag för kort video;
- alla 22 grund- och regressionstest från version 1.0.0.

### Ändrat

- Instructions har komprimerats och omstrukturerats för att rymma en testbar referenshierarki under 8 000 tecken.
- Gold Goblins Studio Look har preciserats till varmt riktat ljus, djupa skuggor, verklig patina, kort skärpedjup och mörka materialmiljöer.
- Bildflödena väljer nu normalt en huvudreferens och högst en stödreferens.
- Formatflödet kräver ombyggd komposition för 1:1, 4:5 och 9:16 i stället för blind beskärning.
- Videobriefar kan ange en REF-bild som stilkälla utan att överföra dess produkt eller process.

### Tillagt

- sex fasta visuella referenser, `REF-01`–`REF-06`;
- `knowledge/07-visuellt-referensbibliotek.md`;
- explicit prioritet: målprodukt → fler produktvinklar → stilreferens → textbeskrivning;
- regler som förhindrar att smycken, stenar, verktyg eller arbetsmoment i REF-bilder blir produktfakta;
- motivbaserad referensvalstabell;
- negativa stilregler;
- T-023–T-032 för referensval, stilöverföring, lagergräns och formatkonsistens;
- jämförande testmatris för version 1.0.0 och 1.1.0;
- `MIGRERING.md`;
- fullständig ZIP- och manifestkontroll.

### Borttaget

- inget identitetsbärande innehåll;
- ingen befintlig kärnfunktion;
- inga gamla testfall.

Fritt, ospecificerat stilval har ersatts av referensstyrt stilval när en relevant REF-bild finns.

### Rättat

- stilreferenser kan inte längre tolkas som produktregister eller dokumentation av verklig verkstadsprocess;
- produktbilden har uttrycklig prioritet vid konflikt med stilreferens;
- stenbilden kan inte användas för att gissa stenarter eller lagerstatus;
- återbrukskänsla skiljs från verifierat återbrukspåstående.

### Testat vid paketering

- Instructions under 8 000 tecken;
- obligatoriska filer och mappstruktur;
- sex öppningsbara PNG-bilder och deras dimensioner;
- SHA-256 och filstorlekar;
- ZIP-integritet;
- manifest mot ZIP-innehåll.

Beteendetesterna körs efter installation i GPT-byggarens Preview.
