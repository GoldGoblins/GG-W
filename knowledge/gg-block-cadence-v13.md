# Verkliga block vid tomgång och kompakt blockvy

Avsikten är en synlig blockkedja ungefär varannan sekund, med mjuk grafik
som följer Qt:s bildklocka. Bildfrekvens och blockproduktion är separata.

Hardhat startar nu med både automining och ett faktiskt intervall på 2 000 ms.
Tomma block skapas av noden även utan överföringar. Fyra CometBFT-validatorer
föreslår och signerar verkliga tomma block efter två sekunders väntan, med
oförändrat kvorum och SDK-verifiering. Ingen dummytransaktion skickas.

Två disponibla prov utan transaktioner verifierade Hardhat höjd 0→2 på 4,417 s
och Comet höjd 1→3 på 4,711 s. Alla kontosaldon och nonces var oförändrade.
Föräldrarnas hashvärden stämde och Comets toppcertifikat verifierades. De
uppmätta lokala observationshastigheterna var 0,453 respektive 0,425 block/s.
Uppstart, observationsfönster och operativsystemet påverkar mätningen; det är
inte ett löfte om exakt tid eller en ny konsensusalgoritm.

Grafen behåller högst 48 verkliga block och visar de senaste 6–12 som små
numrerade rutor, med transaktionsantal, riktade föräldralänkar och verkliga
proposer-banor där de är kända. Ett klick markerar högst sju verkliga
efterföljare. Följ-läget flyttar fönstret med toppen. Positioner och nyblocks-
markeringar animeras med Qt:s bildklocka och blir sedan stilla. Det finns ingen
16 ms RPC-loop eller påhittad framtid i grafen.

Nativebyggaren publicerar en ny receiptbunden körbar fil bredvid en äldre
version. Den öppna appen och dess noder stoppas inte av ett bygge. Nya
konfigurationer används vid nästa uttryckliga normala start av app/nod.
Hardhats rena JavaScript-konfiguration laddas som `.mjs` för att slippa en
TSX/esbuild-barnprocess; Windows befintliga enprocessgräns behålls.

Grafens historia och UI-listor är begränsade. Själva testnodernas kedja och
offentliga databaser växer under en uttryckligt startad session. Detta är inte
ett bevis för ett totalt RAM-tak på 200–300 MiB. Användarens befintliga noder,
nycklar och plånbok används inte av de disponibla testerna.

Kontroller: `tests/test_gg_block_cadence.py`, `tests/test_block_relations_graph.py`
och befintliga service-/RPC-/kvorumtester. Offentlig lokal evidens finns under
`.runtime/network-v13-cadence`.

Primärkällor: [Hardhat 3 mining modes](https://hardhat.org/docs/reference/edr-simulated-networks),
[CometBFTs konfiguration](https://github.com/cometbft/cometbft/blob/v0.40.0/config/config.go),
[CometBFT tomma block](https://github.com/cometbft/cometbft/blob/v0.40.0/docs/core/configuration.md).
