# Migrering från Gold Goblins Content Studio 1.0.0 till 1.1.0

## Mål

Uppgraderingen bevarar GPT:ns identitet och produktintegritet men lägger till ett beständigt visuellt referensbibliotek med sex bilder och en textbaserad reservbeskrivning.

## Före start

1. Öppna den befintliga GPT:n i redigeraren på ChatGPTs webbversion.
2. Spara eller dokumentera nuvarande Instructions, beskrivning, konversationsstartare och aktiverade funktioner.
3. Använd versionshistoriken eller skapa en kopia om funktionen finns i din arbetsyta.
4. Kontrollera att du har hela version 1.0.0-paketet för rollback.
5. Publicera eller dela inte den nya versionen före Preview-test.

## Filer som ersätts

Ersätt dessa med version 1.1.0:

- `INSTRUKTIONER.txt`
- `README.md`
- `TESTSVIT.md`
- `KALLOR.md`
- `MANIFEST.json`
- `knowledge/01-gold-goblins-identitet-och-verksamhet.md`
- `knowledge/02-visuell-profil-och-studio-look.md`
- `knowledge/03-saljbild-konceptbild-och-produktintegritet.md`
- `knowledge/04-bildfloden-produkter-personer-och-miljoer.md`
- `knowledge/05-sociala-format-copy-och-mallar.md`
- `knowledge/06-kort-video-och-produktionsbriefar.md`

## Filer som läggs till

- `CHANGELOG.md`
- `MIGRERING.md`
- `knowledge/07-visuellt-referensbibliotek.md`
- `references/REF-01-gravyr-precisionsarbete.png`
- `references/REF-02-smycke-i-hand.png`
- `references/REF-03-handarbete-arbetsbank.png`
- `references/REF-04-adelstenar-morkgron-sammet.png`
- `references/REF-05-kedjor-komponenter-verkstad.png`
- `references/REF-06-aldre-silverforemal-arbetsyta.png`

## Installation

1. Öppna **Edit GPT** och konfigurationsvyn.
2. Ersätt hela Instructions-fältet med innehållet i version 1.1.0 av `INSTRUKTIONER.txt`.
3. Ta bort de sex gamla Knowledge-filerna när de nya versionerna är redo.
4. Ladda upp alla sju filer i `knowledge/`.
5. Ladda upp alla sex PNG-filer i `references/` som Knowledge.
6. Kontrollera att totalt 13 rekommenderade Knowledge-filer visas.
7. Ladda vid behov upp `KALLOR.md`; totalsumman blir då 14.
8. Kontrollera att Bildgenerering och Webbsökning är aktiverade.
9. Behåll Actions avstängt.
10. Uppdatera beskrivning och konversationsstartare enligt `README.md`.
11. Spara ändringen som utkast och gå till Preview.

## Kontroll av referensfiler

Bekräfta att följande mappning är intakt:

| ID | Motiv |
|---|---|
| REF-01 | gravyr och precisionsarbete |
| REF-02 | smycke i hand |
| REF-03 | handarbete vid arbetsbänk |
| REF-04 | ädelstenar på mörkgrön sammet |
| REF-05 | kedjor och komponenter i verkstad |
| REF-06 | äldre silverföremål på arbetsyta |

Byt inte innehåll mellan ID:n utan att samtidigt uppdatera `07-visuellt-referensbibliotek.md`, tester och manifest.

## Preview-test efter migrering

Kör minst:

1. T-001 — Säljbild av verklig ring.
2. T-002 — Förbjuden produktändring.
3. T-023 — REF-01 för ringmakro.
4. T-026 — REF-04 är inte stenlager.
5. T-027 — REF-05 för vertikal kedjebild.
6. T-029 — Referenshierarki.
7. T-031 — Textbaserad reserv.
8. T-032 — Samma stil i tre format.

Använd samma målprodukt för version 1.0.0 och 1.1.0 där det är möjligt.

## Godkänd migrering

Migreringen är godkänd när:

- namnet och kärnuppdraget är oförändrade;
- Instructions visar versionens nya referenshierarki;
- alla sju textbaserade Knowledge-filer finns;
- alla sex REF-bilder finns;
- målprodukten vinner över stilreferensen;
- REF-04 inte behandlas som lager eller stenregister;
- kritiska tester är godkända;
- nya bilder uppvisar tydligare stilkonsistens utan produktförvanskning.

## Rollback

Om ett kritiskt test misslyckas:

1. publicera inte utkastet;
2. återställ föregående version via versionshistoriken eller den sparade kopian;
3. dokumentera prompt, målbild, vald REF och avvikelse;
4. justera Instructions eller relevant Knowledge-fil;
5. kör om det kritiska testet och regressionskontrollen.

## Viktig begränsning

Bildbaserad Knowledge kan tolkas mindre exakt än text. `knowledge/07-visuellt-referensbibliotek.md` är därför obligatorisk och ska inte ersättas av bilderna ensamma.
