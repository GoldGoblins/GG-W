# DAGoblin: kärna för kontinuerlig, segmenterad historik

Datum: 2026-11-01. **Förberedande exekveringskärna, inte aktiverad nätverkspolicy.**

## Ursprunglig avsikt

Fortsatt produktion ska bevara verkliga blockskapare, signerade originaldata,
saldon, noncer och verifierbar ordning. Det aktiva arbetsminnet behöver vara
begränsat även när den ackumulerade historiken växer.

## Fynd och valt genomförande

Nuvarande v2/v3-källor har en ändlig konsensusgräns: 4 095 block och 512 MiB
rå historik. De reglerna ändras inte av denna kärna. Den ordinarie SDK-källans
avkodare accepterar fortfarande inte den nya källtypen.

En separat, versionsbunden källtyp förbereder en v4-genesis med både
exekveringsgränser för det aktiva segmentet och en uttrycklig historikpolicy.
Policyn ingår i genesis-hash och härledd kedjeidentitet. Ändrade parametrar,
återhashning och caller-mutation får inte tyst ändra den ägda kontexten.

Segmentkärnan återanvänder de ordinarie block-, TX-, signatur-, föräldra-,
nonce- och balanskontrollerna. Globala producentsekvenser och rang bärs vidare;
segmentets relativa exekveringsgränser består. Nästa segments block måste
knyta an till den beräknade brytpunkten. Gamla segment blir inte svaga länkar
in i den aktiva grafen.

En förberedd brytpunkt binder föregående tillstånd, ursprungliga wire-hashar,
hela manifestkedjan, konton, producentnycklar, sekvenser och noncer. Byteantal
och ordningsrot räknas om ur aktiv verifierad metadata. En Merkle-front med
högst 64 toppar binder tidigare avslutade segment. Globala räknare i den nya
typen serialiseras som decimalsträngar för att bevara precision i JSON/JS.

Att förbereda brytpunkten ändrar inte det gamla tillståndet och kastar inga
beständiga originaldata. Det finns ännu ingen publik aktiveringsmetod.

## Verifiering och återstående arbete

Kärnproven använder riktiga signerade block och TX för att kontrollera
kontinuitet genom segmentgränser. Ett separat prov passerar den gamla globala
4 095-blocksgränsen med signerade tomma block och begränsade aktiva segment.
Det är ett exekveringsprov, inte ett genomströmnings- eller SDK-finalitetsprov.

Beständig segmentarkivering, kvittens före beskärning, kanoniskt SDK-beslut,
återspelning av hela arkivkedjan, Python/CLI/UI-integration och nätverksaktivering
återstår. En förberedd övergång ger varken arkivbeständighet eller finalitet.
Gamla källor och deras metadata behåller sina tidigare gränser.

## Primärkällor och avgränsning

- [Narwhal and Tusk, avsnitt 3.3](https://sonnino.com/papers/narwhal-and-tusk.pdf):
  gemensam GC-gräns och separat förvaring av äldre data. Detta motiverar
  konstruktionen; dess protokollbevis överförs inte automatiskt till DAGoblin.
- [Mysticeti v2](https://www.sui.io/blog/mysticeti-v2-sui-consensus): skiljer
  konsensusarbete och hantering av gammal data. Ingen prestandasiffra därifrån
  används som mätresultat för GG.
