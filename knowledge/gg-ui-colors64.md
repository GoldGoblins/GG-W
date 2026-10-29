# GG: 64 färger, ord, teckenpositioner och datagrupper

## Ursprunglig avsikt

Utöka den gemensamma paletten, visa rollernas faktiska färger i inställningarnas
lista och låt användaren färgsätta UI-texter, etiketter, knapptexter och mätare
direkt. Markering ska avse exakt valda tecken; vanliga klocksiffror ska behålla
färgen på sin plats även när värdet ändras. Dataserier ska kunna ha gemensam
färg utan att den förklarande texten måste få samma färg. Procentvärden och
valda deadlines ska kunna förmedlas med valbara färgskalor.

Blockbilden ska vara en kompakt karta med punkter och verkliga mjuka länkar,
med tydliga räknare för vad som faktiskt hämtats och visas.

## Användning

- **Inställningar → Appearance:** 64 färger med starkare rött, svart, vitt och
  mörka/ljusa gråtoner. Den stängda rollväljaren och varje rad i dess öppna lista
  visar rollens aktuella färg. Tidigare sparade walletfärger bevaras.
- **Högerklick på vanlig UI-text:** färgmenyn avser ordet under pekaren.
- **Markera och högerklicka:** välj färg för exakt markerade tecken. Den synliga
  färgsättningen ändrar inte textens underliggande värde eller kopieringsdata.
- **Hela informationstypen:** välj detta i färgmenyn för hela fältet/typen i
  stället för ett teckenintervall. Kontoalias och offentliga kontoadresser i
  nätverkstabellerna använder en gemensam informationstyp.
- **Dataseriens lilla färgruta:** ändra seriens gemensamma färg. I exempelvis
  testnätets RPC-graf ändras både RPC-rutan och samtliga RPC-staplar.
  RPC-texten, Transaktion-texten och Funktionstest-texten har separata textval.
- **Återställ:** återför fältet/gruppen till dess ursprungliga färgbindning.
  Senare temabyten och nya mätvärden fungerar därför även efter återställning.

Vanliga klick, tangentbordsåtgärder och checkboxar behåller sin funktion.
Dragmarkering eller färgmeny ska inte skicka en överföring eller aktivera en
knapp. Även inaktiverade knapptexter kan färgsättas utan att knappen aktiveras.

## Procent och tid

På instrumenterade procentstaplar kan man välja:

| Läge | Beteende |
|---|---|
| Enfärgad | Det valda färgprovet används. |
| Hög andel är risk | Blått vid låg andel, därefter grönt, gult/orange och mättat rött vid max. |
| Hög andel är bra | En stigande skala mot grönt och ljusblått vid 99–100 %. |

Skalan följer det verkliga normaliserade mätvärdet och begränsas till 0–100 %.
Ett okänt värde får neutral färg, inte en falsk grön godkännandemarkering.
Skalan är en presentation; den ändrar inte resursgränser eller nätverksregler.

**Deadline** är ett separat val för ett helt fält eller UI-element. Ange datum
och klockslag i lokal tid. Felaktiga datum och en sluttid före start avvisas;
programmet gissar inte att en passerad tid betyder nästa dag. Färgen följer
förloppet från valt startögonblick till deadline och blir röd vid utgången.
En gemensam timer uppdaterar detta en gång per sekund medan en framtida
deadline finns och appen visas. Den stannar när appen minimeras/döljs eller
alla deadlines löpt ut/återställts. Vanlig positionsfärgning behöver ingen timer.

Teckenintervall binds till UI-fältets plats och UTF-16-positioner. En färg på
sekundpositionen i `12:34:56` finns därför kvar i `12:34:57`. Intervall som inte
längre ryms eller skulle dela ett surrogatepar appliceras inte.

## Blockkartan

Punktläget är standard. Varje synlig punkt är ett observerat block eller ett
signaturkontrollerat lokalt DAG-förslag; varje länk kommer från dess riktiga
föräldrareferens. Hash, höjd/rank, transaktionsantal och status finns i hover/
detaljvyn. Punktfärgen kan väljas per producentgrupp.

Hardhat är fortfarande en kedja. Dess punkter kan ordnas i en mjuk kurva men
får inte påhittade parallella föräldrar. DAGoblin visar däremot de verkliga
parallella förslagen och deras korsande flerföräldralänkar. Visningen ändrar
varken konsensus eller slutlighet.

Vyn håller högst 48 hämtade block och 336 länkar. Små fönster kan visa färre;
räknaren anger visade/hämtade samt aktuell höjd/rank och delvy. Det är ett
begränsat historikfönster, inte ett påstående att samtliga historiska block
visas samtidigt. Ett nytt block skapas aldrig av animationen. Sju efterföljarled
kan markeras från ett valt block utan att andra föräldralänkar förfalskas.

## Implementerat och avgränsat

Gemensamma native `GGText`/`GGLabel`-komponenter behåller originaltext och
textlayout. Färgade tecken använder begränsad, escaped StyledText; en tillfällig
read-only markeringseditor skapas först när användaren markerar eller öppnar
menyn. Det finns ingen markeringseditor per etikett i tomgång.

Endast en sådan editor hålls aktiv åt gången. För text som krympts med
`Text.Fit` används renderarens upplösta teckenstorlek när den finns. I software-
rendering kan Qt sakna den uppgiften; då görs högst 16 metrikprov under själva
interaktionen. Det är en begränsad uppskattning, inte ett löfte om matematiskt
exakt glyphmappning i software-läget. Windows native-provet använder och
kontrollerar den verkligt upplösta teckenstorleken.

Den mekaniska migreringen omfattar över 1 600 visningstexter. Standardkontroller
har gemensamma native-bildtexter, och procent-/statusfärgmål har separata
högerknappshanterare. Det sker ingen återkommande sökning genom UI-trädet.
Endast högerklick på inaktiverade texter använder en begränsad träfftestning.

Vanliga chattkroppar, privata wallet-/återställningsvyer och lösenord ingår inte.
Inmatningsfält, kod-/terminaleditorer och innehåll i externa webbsidor/native-
program behåller sina egna redigerings- och textformatfunktioner; de har inte
fått godtycklig partiell teckenfärgning genom detta lager. GG:s ägda UI-etiketter,
verktygsrader och knapptexter runt dem omfattas.

Färger sparas lokalt med stabila presentationsnycklar och numeriska positioner.
Visad text, adresser, chattmeddelanden eller återställningsord sparas inte i
färgregistret. Registret har högst 1 024 poster, 32 teckenintervall per post och
512 KiB lagring; skrivning sker atomiskt. Gamla färgpreferenser läses fortfarande.

Panelrutorna i nätverksytan har samma enpixliga linjefärg som listdelarna,
utan extra lager, masker eller breda dubbla kanter.

## Verifiering och prestandagräns

Tester använder egna fönster och tillfälliga inställningar, inte den öppna
användarappen eller riktiga nätverkskonton. De prövar verkliga musdrag, höger-
och vänsterklick, sparning/ny läsning, Unicode, klockpositioner, grupper,
procentvärden, deadlines, privata vyer och återställda originalbindningar.
Grafproven verifierar både falska-länk-avvisning och 48 verkliga signerade
DAG-förslag med 168 faktiska föräldralänkar i software och Direct3D11.

Ett separat, avgränsat prov med 1 000 visningstexter gav cirka 84,3 MB RSS för
native Text och 120,0 MB för GGText, alltså cirka 35,8 MB extra. Båda hade noll
tomgångsritningar och noll skapade markeringseditorer under det korta provet.
Det bevisar inte hela programmets RAM-tak eller låsta 60 Hz. Korta tomgångs-
CPU-prov är inte bevis för exakt noll CPU under all användning.

Sammanhållen aktuell rapport finns i `.runtime/ui-colors64/final.json` efter
slutkontrollen. Färgreglerna ger ingen finansiell eller exekveringsbehörighet.

[Verifierade bilder av färglistan och punktkartorna](design/gg-ui-colors64/README.md).
