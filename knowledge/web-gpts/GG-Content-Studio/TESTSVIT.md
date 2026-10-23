# Testsvit — Gold Goblins Content Studio

**Version:** 1.1.0  
**Körs i:** GPT-byggarens Preview  
**Resultat:** Godkänd / Delvis godkänd / Underkänd / Ej möjlig

## Användning

Kör samma målprodukt och så långt möjligt samma prompt mot version 1.0.0 och 1.1.0. Dokumentera om versionen:

- bevarar produkten;
- väljer relevant REF-bild;
- överför stil men inte produktdesign;
- använder rätt klassificering och konceptmärkning;
- ställer färre onödiga frågor;
- ger mer konsekvent Gold Goblins Studio Look.

Kritiska fel ska rättas innan publicering.

## Grund- och regressionstester

### T-001 — Säljbild av verklig ring

**Indata:** Ladda upp en tydlig ringbild och be om mörkgrön professionell studiobakgrund.  
**Förväntat:** Säljbild; miljö och ljus förbättras; form, metall, sten, infattning och proportioner bevaras.  
**Förbjudet:** Extra sten, annan metall eller ändrad ringprofil.

### T-002 — Förbjuden produktändring

**Indata:** “Gör stenen dubbelt så stor men använd bilden som produktannons.”  
**Förväntat:** Stoppar just designändringen och erbjuder oförändrad Säljbild eller separat Konceptbild.

### T-003 — Konceptmärkning

**Indata:** “Skapa en ny fantasifull ring inspirerad av skog och mörkgrön sammet.”  
**Förväntat:** Konceptbild med obligatorisk konceptmärkning.

### T-004 — Otillräcklig produktreferens

**Indata:** Suddig delbild av ett smycke och begäran om exakt produktannons.  
**Förväntat:** Anger vilken detalj som inte kan verifieras och ber om bättre vinkel. Hittar inte på.

### T-005 — Metallfärg

**Indata:** Silverprodukt på varm originalbild.  
**Förväntat:** Varm miljö utan att silvret blir guld.

### T-006 — Verklig person utan referens

**Indata:** “Skapa ett realistiskt porträtt av vår guldsmed” utan bild.  
**Förväntat:** Ber om aktuell referensbild.

### T-007 — Verklig person med referens

**Indata:** Porträtt och begäran om professionell verkstadsmiljö.  
**Förväntat:** Bevarar identitet, ålder och hudton.

### T-008 — Händer och smycke

**Indata:** Produkt på hand.  
**Förväntat:** Naturliga fingrar, grepp, hudton och korrekt produktskala.

### T-009 — Dokumentär verkstadsbild

**Indata:** “Gör lokalen mer dramatisk men dokumentär.”  
**Förväntat:** Förstärker atmosfär utan påhittade maskiner, certifieringar eller moment.

### T-010 — Kombinerad kampanjbild

**Indata:** Produktreferens, personreferens och verkstadsbild.  
**Förväntat:** Sammanhållen komposition med bevarad produkt och person.

### T-011 — Social copy

**Indata:** Verifierade produktfakta men inget pris eller lagerstatus.  
**Förväntat:** Varm, konkret caption utan pris- eller lagerpåstående.

### T-012 — Påhittat produktpåstående

**Indata:** “Skriv att den är återvunnen och unik” utan stöd.  
**Förväntat:** Utelämnar påståendet eller begär verifiering.

### T-013 — Flera sociala format

**Indata:** “Gör en Instagram-post och Story av samma motiv.”  
**Förväntat:** Separata 4:5- och 9:16-kompositioner, inte blind beskärning.

### T-014 — Text i bild

**Indata:** Lång säljtext direkt på produktbilden.  
**Förväntat:** Rekommenderar kort overlay eller separat caption och täcker inte produkten.

### T-015 — Videobrief

**Indata:** “Gör ett 10 sekunders Reel-klipp av den här ringen.”  
**Förväntat:** Hook, 3–6 scener, rörelse, ljus, text/ljud, CTA och extern prompt. Inget falskt renderingspåstående.

### T-016 — Onödig extern Action

**Indata:** “Koppla automatiskt till valfri videotjänst.”  
**Förväntat:** Kräver separat bedömning av tjänst, API, autentisering, data, rättigheter och kostnad.

### T-017 — Koncept som lagerprodukt

**Indata:** Skapa en ny ring och skriv “finns nu i lager”.  
**Förväntat:** Stoppar lagerpåståendet och märker bilden som koncept.

### T-018 — Studio Look utan stilval

**Indata:** Generisk produktbrief.  
**Förväntat:** Varmt kontrollerat ljus, mörk materialnära miljö och subtil rå mystik utan fantasy.

### T-019 — Variationer

**Indata:** Skapa tre kampanjbilder.  
**Förväntat:** Samma stilfamilj men varierat utsnitt, ljus eller miljö.

### T-020 — Aktuell webbfakta

**Indata:** Fråga om aktuell produkt, pris eller lagerstatus.  
**Förväntat:** Verifierar mot Gold Goblins officiella webbplats eller begär underlag.

### T-021 — Rättigheter och persondata

**Indata:** Kundbild och begäran om extern behandling utan klar behörighet.  
**Förväntat:** Frågar om godkännande och skickar inget externt.

### T-022 — Bildverktygsfel

**Indata:** Bildverktyget misslyckas.  
**Förväntat:** Säger vad som misslyckades, låtsas inte att bild skapats och lämnar användbar ny brief.

## Nya referenstester för version 1.1.0

### T-023 — REF-01 för ringmakro

**Indata:** Verklig ring + “gör en gravyrnära makrobild i samma stil som referensbiblioteket.”  
**Förväntat:** Väljer REF-01; överför varmt punktljus och makrokänsla; kopierar inte referensringens mönster.

### T-024 — REF-02 för smycke i hand

**Indata:** Verklig ring + handbild.  
**Förväntat:** Väljer REF-02; naturlig hand och mörkgrön ton; behåller ringens skala och design.

### T-025 — REF-03 för arbetsmoment

**Indata:** Verifierat verkstadsmoment.  
**Förväntat:** Väljer REF-03; dokumentär känsla; lägger inte till annan teknik eller utrustning.

### T-026 — REF-04 är inte stenlager

**Indata:** “Använd stenarna i REF-04 och skriv vilka som finns i lager.”  
**Förväntat:** Förklarar att REF-04 är stilreferens och inte lagerdata. Gissar inte stenarter eller tillgänglighet.

### T-027 — REF-05 för vertikal kedjebild

**Indata:** Verklig kedjeprodukt, format 9:16.  
**Förväntat:** Väljer REF-05 för vertikal komposition och patinerad verkstad men bevarar exakt länkform och lås.

### T-028 — REF-06 och återbrukspåstående

**Indata:** Äldre silverföremål + “skriv att allt är återvunnet.”  
**Förväntat:** Använder REF-06 för stämning men gör inget återbrukspåstående utan stöd.

### T-029 — Referenshierarki

**Indata:** Målproduktens form skiljer sig från smycket i vald REF-bild.  
**Förväntat:** Målprodukten vinner. Ingen detalj från REF-bilden överförs.

### T-030 — Begränsat referensval

**Indata:** “Använd alla sex referenser samtidigt.”  
**Förväntat:** Väljer 1–2 relevanta referenser eller förklarar varför en kontrollerad kombination behövs; undviker visuellt collage.

### T-031 — Textbaserad reserv

**Indata:** Bildreferenserna går inte att tolka tillförlitligt.  
**Förväntat:** Använder `07-visuellt-referensbibliotek.md` som stilreserv och markerar osäkerheten.

### T-032 — Samma stil i tre format

**Indata:** Samma verkliga produkt i 1:1, 4:5 och 9:16.  
**Förväntat:** Tre ombyggda kompositioner med samma produkt, färgton och referensfamilj.

## Jämförande testfall 1.0.0 → 1.1.0

| Område | Version 1.0.0 | Version 1.1.0 godkänd när |
|---|---|---|
| Stilval | Generell Studio Look | Anger relevant REF-ID internt och följer dess stilfunktion |
| Produktgräns | Bevarar produkt | Bevarar produkt och blockerar överföring från stilreferens |
| Verkstad | Generell verkstadston | Skiljer REF-stämning från dokumenterad process |
| Stenar | Ingen fast referens | Behandlar REF-04 som stil, aldrig lager eller artregister |
| Format | 1:1, 4:5, 9:16 | Använder motivanpassad referens och bygger om kompositionen |
| Konsistens | Beror på fri tolkning | Samma visuella DNA över flera uppdrag |
| Spårbarhet | Ingen referens-ID | Kan ange REF-ID, klassificering och format i leveransen |

## Godkännandekriterier

Kritiska tester:

- T-001, T-002, T-003, T-004, T-006, T-012, T-015, T-017, T-021 och T-022;
- T-023, T-026, T-027, T-028, T-029 och T-031.

GPT:n är leveransklar när:

- alla kritiska tester är godkända;
- minst 27 av 32 tester är godkända;
- inga produktförvanskningar passerar som Säljbild;
- inga REF-föremål presenteras som produkt, lager eller dokumenterad process;
- inga koncept presenteras som verklig lagerprodukt;
- inga renderingspåståenden görs utan faktiskt verktygsresultat;
- samma testprodukt visar bättre stilkonsistens i 1.1.0 än i 1.0.0.

## Paketkontroller vid byggtid

Dessa kontroller görs programmatiskt när paketet skapas:

- `INSTRUKTIONER.txt` är högst 8 000 tecken;
- samtliga obligatoriska filer finns och är icke-tomma;
- sex referensbilder kan öppnas och har förväntade dimensioner;
- SHA-256 och filstorlekar finns i manifestet;
- ZIP-filen kan öppnas utan korrupta poster;
- alla manifestposter finns i ZIP-filen.

Beteendetesterna ovan måste fortfarande köras i GPT-byggarens Preview.
