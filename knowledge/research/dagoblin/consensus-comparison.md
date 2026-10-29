# DAGoblin: jämförelse av protokollfamiljer

Granskningsdatum: 2026-10-29. Fakta från originalarbeten och officiella
specifikationer skiljs nedan från våra designslutsatser. Tabellen är ett urval
som täcker väsentligt olika modeller, inte ett påstående att alla publicerade
konsensusalgoritmer är genomgångna. Inga andras marknadsförda TPS-tal används
som GG:s benchmarkresultat.

## Fakta och aktuellt versionsläge

| Familj | Hur parallellitet och ordning hanteras | Säkerhets-/kostnadsfråga att behålla |
|---|---|---|
| Bitcoin/Nakamoto | Konkurrerande PoW-kedjor; mest ackumulerat arbete avgör gren. | Bekräftelser ger probabilistisk säkerhet under arbets-/nätantaganden. Fler block är inte automatiskt mer säkerhet. |
| Kaspa/GHOSTDAG | Block-DAG; blue-set/blue-work, vald förälder och mergeset ger en deterministisk ordning. | PoW, anticoneparameter, block-/föräldragränser, pruning och nätfördröjning måste analyseras ihop. |
| DAGKnight | Separat adaptivt DAG-förslag och utvecklingsgren. | Parameteranpassning tar inte bort kapacitets- och klientantaganden. Ingen aktiverad huvudnäts-DAGKnight påvisas i den granskade releasen. |
| Narwhal/Tusk | Tillförlitlig datadistribution skiljs från ordningsprotokollet; flera arbetare kan distribuera data. | Tillgänglighetscertifikat och BFT-antaganden ersätts inte av fler godtyckliga föräldrar. |
| DAG-Rider | Reliable broadcast bygger rund-DAG; gemensamt slumpmynt hjälper lokal ordning. | `f<n/3`, autentiserade tillförlitliga kanaler och korrekt coininstans behövs. Referensernas kommunikation kostar. |
| Bullshark | Utläser konsensus från en strukturerad DAG, med snabb väg vid gynnsam synkroni. | DAG-struktur och beslutströsklar är del av beviset; kan inte bytas till sju föräldrar på känsla. |
| Mysticeti | Ocertifierade block, implicita röst-/certifikatmönster och förutbestämda proposerplatser. | Modell: `n=3f+1`, högst `f` fel, autentiserade kanaler; liveness kräver partiell synkroni. |
| Starfish | Header/payload separeras; push-pacemaker, kodade fragment och DAG-bundna tillgänglighetscertifikat. | Liveness, catch-up och faktisk dataåterhämtning måste granskas även när normalfallet är snabbt. |
| Hedera/Hashgraph | Gossip-historik och virtual voting används för att härleda ordning. | Röstvikt/medlemskap och asynkrona BFT-antaganden försvinner inte för att separata röstpaket undviks. |
| Avalanche/Snowman | Upprepade slumpade viktade delurval och konfidensregler. | Probabilistiska trösklar beror på modell och urval; elva godtyckliga peers ger inte samma regel. |
| HotStuff/CometBFT | BFT-röstning och certifierad gemensam ordning, med olika faser/pipelining. | Medlemskap, kvorumöverlapp, låsregler och pacemaker är centrala. Lokala processer är inte oberoende operatörer. |
| Ethereum/Gasper | LMD-GHOST för grenval och Casper-FFG för checkpointslutlighet. | Separata egenskaper och antaganden; en snabb grenobservation är inte FFG-finalitet. |
| Solana/Alpenglow | Votor ersätter TowerBFT:s röstning med certifikat. Exekveringsmotorn är en separat del. | Aktuell aktivering, röstavikt och datadistribution måste användas; gammal TowerBFT-tabell är otillräcklig. |
| Lightning | Uppdateringar mellan finansierade kanaler, med onchainverkställighet. | Kapacitet, likviditet, routing, backups och stängning är andra flaskhalsar än L1-BPS. |

Bitcoinraden bygger på originalets §§4–6, 11:
[Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf).
Kaspa/DAGKnight granskas mer ingående i [egen rapport](kaspa-ghostdag-dagknight.md).

Narwhal och Tusk är skilda komponenter; flera dataarbetare skalar inte automatiskt
hela ordnings-/exekveringsvägen. [Originalarbete](https://arxiv.org/abs/2105.11827).
DAG-Rider bygger uttryckligen på reliable broadcast och ett globalt coin; dess
postkvantumpåstående är beroende av hur byggblocken realiseras, inte ett intyg
för Ed25519-baserad GG. [§§1–2](https://arxiv.org/html/2102.08325v2).
Bullshark använder strukturer som gör ytterligare ordningsmeddelanden onödiga,
inte all kommunikation onödig. [Originalarbete](https://arxiv.org/abs/2201.05677).

Mysticetis modell och direkta/indirekta commitregler har lästs i §§II-A och
III-B–C. Oavgjorda platser kan hålla tillbaka den slutliga sekvensen; fler
parallella proposerplatser är alltså inte en kostnadsfri vinst under alla fel.
[Mysticeti v6](https://arxiv.org/html/2310.14821v6).
Starfish-arbetets reviderade abstract pekar uttryckligen på desynkronisering och
livenessluckor i tidigare ocertifierade modeller. Fullständiga bevis har inte
reviderats här. [IACR 2025/567, reviderad 2026-04-08](https://eprint.iacr.org/2025/567).

Två viktiga uppdateringar mot äldre jämförelser:

- IOTA:s aktuella dokumentation anger **Starfish** för Devnet, Testnet och Mainnet.
  Gamla Tangle-beskrivningar används därför endast som historiska modeller.
  [IOTA consensus](https://docs.iota.org/about-iota/iota-architecture/consensus).
- Solanas officiella sida, uppdaterad oktober 2026, anger Votor aktivt sedan
  epok 1064 den 21 oktober. Rotor beskrivs fortfarande som senare datadistribution.
  Cirka 150 ms är ett finalitetsmål; 200 ms slots är en separat förändring.
  Detta är källans uppgift, inte vår oberoende nätmätning. Äldre SIMD-0326 har
  fortfarande metadata `Review`; den avvikelsen dokumenteras, inte döljas.
  [Aktuellt läge](https://solana.com/upgrades/alpenglow),
  [SIMD-0326](https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0326-alpenglow.md).

Hashgraphs virtual voting sparar explicita röster men kräver den distribuerade
gossip-historiken. [Officiell beskrivning](https://docs.hedera.com/learn/core-concepts/hashgraph).
Avalanches aktuella huvudnät använder linjär Snowman även för X-Chain sedan
Cortina 2023; den historiska DAG-motorn får inte blandas ihop med dagens läge.
[Arkitektur](https://build.avax.network/docs/nodes/architecture/consensus).
HotStuff utgår från partiell synkroni och väldefinierade röster/lås.
[Originalarbete](https://arxiv.org/abs/1803.05069).
Gasper skiljer safety- och livenessantaganden; en idealiserad analys är inte
hela dagens klientimplementation. [Originalarbete](https://arxiv.org/abs/2003.03052),
[officiell introduktion](https://ethereum.org/developers/docs/consensus-mechanisms/pos/gasper/).
Lightning kräver säkert tillståndsbyte och återanslutning; en gammal backup får
inte blint omsändas. [BOLT 0](https://github.com/lightning/bolts/blob/master/00-introduction.md),
[BOLT 2](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md).

## Egna slutsatser för DAGoblin

Vi bör jämföra kompletta vägar: avsändararbete → admission → tillgänglighet →
ordning → exekvering → slutligt kvitto. Att optimera bara blockproduktion kan
flytta flaskhalsen till verifiering, nät, tillståndslås eller disk.

En mobil klient behöver inte delta i varje validatorröst. En snabb producent
kan leverera batcher till en kapabel validatoruppsättning, medan en lätt klient
kontrollerar autentiserade checkpoint och egna bevis. Det ändrar klientrollen;
det gör inte telefonen till en full validator med samma lagrings-/säkerhetsmodell.

Att kombinera GHOSTDAG:s arbetsbaserade grenval med BFT-certifikat, en snabb
objektväg och sampling är ett **nytt kompositionsproblem**, inte summan av fyra
redan färdiga bevis. Första nätförsöket ska därför hålla slutlighetsregeln
oförändrad och isolera experimentell distribution/förberäkning framför den.

## Granskningsomfattning och luckor

Kaspa: pinnad release och utvalda kritiska kodvägar, se detaljrapport.
DAG-Rider/Mysticeti: modell och utvalda algoritmavsnitt; ingen full formell
beviskontroll. Narwhal/Bullshark/HotStuff/Gasper: originalens översikt och
specificerade relevanta byggblock; inga egna reproduktioner av publicerade WAN-
benchmarks. Hedera/Avalanche/IOTA/Solana/Lightning: ovan länkade officiella
beskrivningar/specifikationsavsnitt; ingen full klientrevision eller aktiv
sårbarhetstestning. SPECTRE/PHANTOM, äldre IOTA, Cordial Miners, sharding-
kompositioner och nyare varianter behöver separata fördjupningar innan de kan
styra en konsensusändring. Urvalet ska växa efter konkreta hypoteser, inte genom
att kalla en länklista för genomförd forskning.
