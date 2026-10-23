# Gold Goblins Content Studio

**Version:** 1.1.0  
**Skapad:** 2026-07-28  
**Typ:** Optimal ombyggnad av verksamhetsanpassad GPT för bildskapande, bildredigering och socialt innehåll

## Syfte

Gold Goblins Content Studio skapar och redigerar professionella stillbilder av smycken, människor, verkstad och lokaler. Den skiljer alltid mellan verkliga Säljbilder och fria Konceptbilder, bevarar produktdetaljer och använder sex godkända bilder som ett beständigt visuellt referensbibliotek.

## Viktigaste princip

> Sann produkt först. Stark bild därefter.

En verklig produkt får få bättre ljus, bakgrund, komposition och studiokänsla, men dess form, metall, sten, gravyr, proportioner och andra kännetecken får inte förändras. Stilreferenser styr atmosfär, aldrig produktfakta.

## Vad version 1.1.0 tillför

- sex omdöpta och stabilt identifierade stilreferenser, `REF-01`–`REF-06`;
- textbaserad referenskatalog som reserv när en bild inte tolkas tillförlitligt;
- tydlig hierarki där aktuell målprodukt alltid vinner över stilreferensen;
- motivbaserat val av högst två referenser;
- nya tester för stilöverföring utan produktöverföring;
- migreringsguide och ändringslogg;
- uppdaterad, komprimerad Instructions-text.

## Paketets filer

### Styrning och installation

- `INSTRUKTIONER.txt` — komplett text för GPT-byggarens Instructions.
- `README.md` — installation, konfiguration och första test.
- `CHANGELOG.md` — vad som bevarats, ändrats, lagts till och tagits bort.
- `MIGRERING.md` — stegvis uppgradering från version 1.0.0.
- `TESTSVIT.md` — 32 testfall, inklusive jämförande referenstester.
- `KALLOR.md` — verifierade OpenAI- och Gold Goblins-källor.
- `MANIFEST.json` — filförteckning, storlekar och SHA-256.

### Knowledge

- `knowledge/01-gold-goblins-identitet-och-verksamhet.md`
- `knowledge/02-visuell-profil-och-studio-look.md`
- `knowledge/03-saljbild-konceptbild-och-produktintegritet.md`
- `knowledge/04-bildfloden-produkter-personer-och-miljoer.md`
- `knowledge/05-sociala-format-copy-och-mallar.md`
- `knowledge/06-kort-video-och-produktionsbriefar.md`
- `knowledge/07-visuellt-referensbibliotek.md`

### Visuella referenser

- `references/REF-01-gravyr-precisionsarbete.png`
- `references/REF-02-smycke-i-hand.png`
- `references/REF-03-handarbete-arbetsbank.png`
- `references/REF-04-adelstenar-morkgron-sammet.png`
- `references/REF-05-kedjor-komponenter-verkstad.png`
- `references/REF-06-aldre-silverforemal-arbetsyta.png`

## Instruktionens längd

`INSTRUKTIONER.txt` innehåller exakt **7592 tecken inklusive radbrytningar** och håller sig under gränsen 8 000.

## Rekommenderad GPT-konfiguration

### Namn

**Gold Goblins Content Studio**

### Beskrivning

> Skapar och redigerar varumärkestrogna bilder för Gold Goblins med sex fasta stilreferenser. Bevarar verkliga smyckens detaljer, skiljer Säljbild från Konceptbild och tar fram social copy och videobriefar.

### Konversationsstartare

- `Gör den här produktbilden till en Säljbild i Gold Goblins-stil. Välj rätt REF-bild men ändra inte smycket.`
- `Skapa en 4:5-kampanjbild utifrån den här produkten och verkstadsmiljön.`
- `Skapa ett tydligt märkt smyckeskoncept med REF-04 som färg- och materialinspiration.`
- `Gör ett varmt porträtt i verkstadsmiljö och bevara personens identitet.`
- `Skapa en 10 sekunders Reel-brief för den här ringen med REF-01 som ljusreferens.`

### Funktioner

Aktivera:

- **Image generation / Bildgenerering** — kärnfunktion för nya bilder och redigering.
- **Web search / Webbsökning** — för aktuella produktfakta, Gold Goblins webbuppgifter och plattformsinformation.
- **Fil- och bilduppladdning** — för målprodukter, personer, miljöer och referenser.

Rekommenderas:

- **Code Interpreter & Data Analysis** — för filhantering, innehållskalendrar och framtida paketering.

Aktivera inte i version 1.1.0:

- **Actions** — ingen extern API-effekt behövs för kärnuppgiften.

Använd en aktuell bildkapabel modell. Undvik att hårdkoda modellnamn eftersom tillgängliga modeller kan ändras.

## Installation i GPT-byggaren

OpenAI anger vid verifieringen 2026-07-28 att byggande och redigering av GPT:er görs på webben, att Knowledge kan innehålla vanliga bild- och dokumentformat och att högst 20 Knowledge-filer kan bifogas. Detta paket använder 13 rekommenderade Knowledge-filer: sju textfiler och sex bilder. Kontrollera aktuell dokumentation om gränssnittet har ändrats.

### Ny installation

1. Öppna ChatGPT på webben.
2. Gå till **Explore GPTs** och välj **Create**.
3. Öppna konfigurationsvyn.
4. Ange namn och beskrivning enligt ovan.
5. Klistra in hela `INSTRUKTIONER.txt` i **Instructions**.
6. Ladda upp alla sju filer i `knowledge/`.
7. Ladda upp alla sex PNG-filer i `references/` som Knowledge.
8. Ladda vid behov även upp `KALLOR.md`; totalsumman blir då 14 filer.
9. Aktivera Bildgenerering och Webbsökning.
10. Lägg in konversationsstartarna.
11. Testa i Preview innan GPT:n delas eller används skarpt.
12. Spara en första version.

### Uppgradering från version 1.0.0

Följ `MIGRERING.md`. Säkerhetskopiera eller använd versionshistoriken före ändringen. Ersätt Instructions, byt ut de sex gamla Knowledge-filerna, lägg till den sjunde Knowledge-filen och ladda upp de sex visuella referenserna.

## Referenslogik

När en användare laddar upp en verklig produkt ska GPT:n prioritera:

1. den aktuella målprodukten;
2. fler vinklar av samma produkt;
3. relevant REF-bild för stil;
4. textbeskrivningen i `07-visuellt-referensbibliotek.md`.

Referensbilderna är inte Gold Goblins produktregister. De verifierar inte stenart, lager, verktyg, process, ursprung, värde eller återbruk.

## Rekommenderat första test

Ladda upp en tydlig bild av en verklig ring och skriv:

> Gör detta till en Säljbild för Instagram i 4:5. Använd REF-01 endast för varmt makroljus, skärpedjup och verkstadskänsla. Bevara ringens form, metall, sten, infattning, gravyr och proportioner exakt. Överför inte designen från referensringen. Lägg ingen text i bilden.

Godkänt när:

- uppdraget klassificeras som Säljbild;
- REF-01 används som stil, inte produkt;
- ringen matchar målbilden;
- metall och sten återges trovärdigt;
- kompositionen fungerar i 4:5;
- inga produktfakta hittas på.

Kör därefter T-026 och T-029 i `TESTSVIT.md`.

## Användning

### Verklig produkt

Ladda upp en eller flera tydliga produktbilder. Ange kanal och syfte. GPT:n ska normalt agera direkt och fråga bara när en kritisk detalj saknas.

### Verklig person

Ladda upp en referensbild i den aktuella konversationen. GPT:n ska bevara identitet vid retusch och miljöbyte.

### Koncept

Skriv att uppdraget är ett koncept eller beskriv en fri idé. GPT:n märker konceptet när det kan förväxlas med en verklig produkt.

### Kort video

GPT:n levererar scenlista, rörelse, ljus, text, ljudkänsla, CTA och extern videoprompt. Faktisk rendering kräver ett tillgängligt videoverktyg eller separat integration.

## Kvalitetskontroll före publicering

Kontrollera alltid:

- att produkten matchar originalet;
- metall, sten, gravyr, lås, länkar och proportioner;
- händer och personidentitet;
- pris, material, lagerstatus och andra produktfakta;
- att REF-föremål inte har blivit produktfakta;
- rättigheter och personers godkännande;
- konceptmärkning;
- bildformat och eventuell text.

## Begränsningar

- AI-redigering kan ändra små detaljer trots tydliga instruktioner; mänsklig slutkontroll krävs.
- Bildreferenser i Knowledge kan tolkas mindre exakt än text. Därför finns `07-visuellt-referensbibliotek.md`.
- De tre mindre skärmbilderna används främst för ljus, komposition och stämning, inte detaljrekonstruktion.
- Exakt färg påverkas av originalbild, ljus och skärm.
- Konceptbilder är inte produkter, offerter eller tillverkningsritningar.
- Videobriefar är inte renderade videoklipp.
- Aktuella plattformsfunktioner och sociala format kan förändras.

## Genomförda paketkontroller

Vid byggandet kontrolleras maskinellt:

- instruktionens teckenantal;
- att samtliga filer finns och är icke-tomma;
- att sex PNG-bilder kan öppnas;
- bilddimensioner;
- SHA-256 för samtliga filer;
- att ZIP-filen kan öppnas utan korrupta poster;
- att manifestets filer finns i ZIP-filen.

Beteendetesterna måste fortfarande köras i GPT-byggarens Preview.

## Versionsprincip

Vid ny version:

1. bevara namn, syfte, tonalitet, målgrupp och produktintegritet;
2. dokumentera ändringar;
3. räkna instruktionens tecken igen;
4. verifiera versionskänsliga källor;
5. kör kritiska testfall och regressionstester;
6. skapa nytt manifest och ny ZIP.
