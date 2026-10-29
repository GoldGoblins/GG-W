# Verkliga blockrelationer och separata klockor

Användarens avsikt är att se de faktiska blocken, deras relationer och hur
nätverket arbetar, samtidigt som gränssnittet kan röra sig mjukt i 60 Hz.
Grafiken ska vara begriplig utan påhittade block, anslutningar eller hastigheter.

## Befintlig motor och vad som faktiskt är implementerat

Hardhat-testnätet är en lokal EVM-utvecklingskedja med automining och verkliga
tomma block med tvåsekundersintervall. GG:s andra
testmotor använder fyra separata CometBFT-processer med en fast validatorlista
och 3/4-kvorum, fortfarande på en fysisk dator och med en operatör. Båda ordnar
block i en kedja med en föregångare per block; de är inte Kaspa BlockDAG.

`snapshot.block_graph` innehåller observerade hashvärden, verkliga parent-hashar,
höjd, blocktid och antalet inkluderade transaktioner. Comet visar även den
faktiska proposer-adressen. En kant finns bara när båda blocken finns och
föregångarens hash stämmer med det nästa blockets parent-hash. Okända eller
saknade föregångare fylls aldrig med syntetiska relationer.

Historiken är högst 48 block och 64 lokala tidsobservationer. Varje snapshot
hämtar högst åtta nya blockhuvuden; Hardhat återanvänder redan avläst toppblock
och kan batchläsa högst sju äldre. Uppfyllnadsarbetet är begränsat, och när
fönstret är fullt och toppen är oförändrad hämtas inga nya historikhuvuden.
Ingen ny timer, bakgrundsnod, extern RPC-adress eller 60 Hz-RPC-pollning införs.

`source: OWNED_RPC_OBSERVATION` betyder observerad noddata. Det är skilt från
SDK-verifiering av certifikat och exekvering. `certificate_verified` sätts bara
för exakt höjd/hash som redan verifierats av CometBFT-SDK-vägen. Övriga block
får inte beskrivas som separat kryptografiskt verifierade bara för att de ritas.

## Mätdefinitioner

| Fält i `block_graph.metrics` | Betydelse |
|---|---|
| `bps` | Ökning i observerad blockhöjd dividerad med verklig lokal monotont mätt tid. Första historikhämtningen räknas inte som ny trafik. Minst en sekund behövs; annars `null`. |
| `tps` | Antal transaktioner inkluderade i de nyobserverade blocken dividerat med samma tid. Om fönstret saknar block är värdet `null`; inkluderade transaktioner är inte ett löfte om lyckad applikationsexekvering. |
| `window_seconds` | Faktisk längd på observationsfönstret. |
| `header_bps` | Höjdskillnad dividerad med blockens egna tidsstämplar. En separat klocka; Hardhats syntetiska blocktid är inte verklig API-genomströmning. |
| `block_interval_ms` | Genomsnittligt intervall enligt blockens egna tidsstämplar. |
| `ttf_ms`, `ttf_p50_ms`, `ttf_p95_ms` | Senaste/median/p95 av slutförda lokala API-operationer, med uttrycklig definition i `ttf_basis`. |

Hardhat använder `API_SUBMISSION_TO_RECEIPT`. Comet använder
`API_SUBMISSION_TO_EXECUTION_PROOF`, vilket inkluderar observation och SDK-bevis
mot H+1. Detta är inte samma sak som en isolerad mätning av protokollets tid till
konsensusfinalitet. `null` visas som okänt, inte som noll eller ett löfte om en
framtida hastighet. `stale` och `error` anger när grafen inte är en aktuell läsning.

## 60 Hz, flera transaktioner och konsensus

Rendering med 60 bilder/s är separat från blockproduktion. En kedja med färre
block kan ritas i 60 Hz utan att nya block uppfinns. Den nuvarande Comet-motorn
har `TimeoutCommit = 100 ms` och standardvalet `SkipTimeoutCommit = false`.
Tomma block föreslås med `CreateEmptyBlocksInterval = 2 s`; ett explicit
startat nätverk kan därför synas arbeta även utan överföringar.
Den konfigurationen är inte ett verifierat 60 block/s-system. Att bara sänka
timeouts eller blanda konsensusnamn ger ingen säker DAG eller bevisad skalning.

Motorn stödjer redan flera transaktioner per block med tak på 128 transaktioner
och 64 KiB block, där båda gränserna gäller. Det verkliga, disponibla 16-TX-testet
inkluderade flera transaktioner i samma block och verifierade samtliga slutförda
operationer. Ingen regel kräver en transaktion per block.

Inga konsensusregler, validatorvikter, kvorumgränser, tillgångar eller bridges
ändras av denna visualisering. För en verklig ny DAG/protokollhybrid återstår
protokollspecifikation, konflikt-/ordningsregler, bevis, adversariella tester och
prov med oberoende noder. Ingen likvärdighet med eller överlägsenhet mot publika
Kaspa/Solana/Lightning påstås av dessa lokala mätningar.

## Verifierat i denna ändring

`tests/test_gg_block_graph.py` omfattar begränsad uppfyllnad, luckor, atomiskt
avvisade felaktiga parent-hashar, klockornas skillnad, separat API-finalitet,
kedjeidentitet, exakta SDK-markörer och engångsbudget för RPC-läsningar.
Ett verkligt disponibelt Hardhat-rundturstest jämförde varje synligt block med
RPC. Ett verkligt fyrvalidators-/16-TX-test verifierade flera transaktioner per
block, alla kantrelationer och att endast egna processer stoppades efter testet.
Tillsammans med befintliga RPC- och motortester passerade 52 kontroller.
Användarens öppna nod och wallet användes inte av testerna.

## Ritkostnad och bildfrekvens

`BlockRelationsGraph.qml` använder återanvända ListModel-noder och QtQuick.Shapes
för riktiga kanter. Högst 48 noder behålls; de senaste 6–12 visas som numrerade
rutor med transaktionsantal. Kompakta grafer använder en rad med verkliga
proposer-färger. I grafer med minst 170 pixlars höjd kan V1–V4-banor visas, bara
när blockets faktiska proposer-adress kan kopplas till den ägda genesisens
validatorlista. Klick markerar högst sju verkliga
efterföljare, och detaljrutan visar hela hashvärdet med kopieringsknapp.
420 ms positions-/opacitetsanimationer och 620 ms nyblocksmarkering använder
Qt:s bildklocka och stannar.
Komponenten har ingen Canvas, 16 ms-timer, RPC-pollning eller kontinuerlig
tomgångsanimation.

Faktiska Qt-tester passerade i både software och Direct3D11 vid 360, 430, 900
och 1600 logiska pixlars bredd, utan QML-varningar eller tomgångsbilder.
Software-fixturens animation gav 14 bilder och cirka 16,39 ms medianintervall.
Den dolda native-fixturen kan throttlas av Windows och användes därför inte som
ett påstående om native bildfrekvens.

Ett tidigare V12-test, ett synligt 3,134-sekunderstest med explicit syntetisk märkning,
mätte den riktiga Direct3D11-ritvägen med 48 noder, ett 800×220-fönster och
22 syntetiska uppdateringar. På den aktuella 165 Hz-skärmen gav den två sekunder
långa kontinuerliga mätfasen 187 bilder, **93,59 bilder/s i genomsnitt**,
**8,852 ms median** och **30,903 ms p95**. Inga bilder ritades efter att
animationerna lagt sig. Fokus ändrades inte och testfönstret stängdes automatiskt;
användarens app, testnod och FPS-inställningar ändrades inte.

Det visar över 60 bilder/s i genomsnitt i denna avgränsade fixtur, men p95 visar
att varje bild inte höll 16,7 ms. Det är inte en verifiering av låsta 60 Hz i hela
GG under maximal last, och har ingen koppling till ett löfte om 60 block/s.

V13:s kompakta native-prov med 690×108 grafyta, 12 synliga rutor och 48 behållna
block gav 164,77 FPS i snitt på samma 165 Hz-skärm, 6,072 ms median och
9,423 ms p95 under en 1,8 sekunder lång syntetisk mätfas. Efter animationerna
ritades inga tomgångsbilder. Användarens fokus, app, nod och FPS-inställning
ändrades inte. Det visar den avgränsade renderarens kapacitet, inte hela appens
bildfrekvens eller fler verkliga block. Se [blockkadens V13](gg-block-cadence-v13.md).

Primärkällor: [CometBFT v0.40.0 block-/headerstruktur](https://github.com/cometbft/cometbft/blob/v0.40.0/types/block.go),
[CometBFT v0.40.0 konsensuskonfiguration](https://github.com/cometbft/cometbft/blob/v0.40.0/config/config.go),
[Hardhat 3-konfiguration](https://hardhat.org/docs/reference/configuration).
