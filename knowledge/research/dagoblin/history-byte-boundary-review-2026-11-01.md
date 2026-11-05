# DAGoblin: verklig signerad historik vid bytegränsen

## Ursprunglig avsikt

Nätverket ska hantera verkliga transaktioner och återhämtning på långsamma
noder. Kapacitet får inte ersättas med räknare, animationshastighet eller
osignerade fyllnadsbytes. Dagens ändliga labb är ännu inte ett uthålligt nätverk.

## Verifierade fakta

Ett begränsat opt-in-prov fyllde en riktig native ABCI-applikation med
217 block, vardera med 5 000 unika individuellt signerade Ed25519-transaktioner.
Sex disponibla testproducenter använde egna sekvenser och noncer. Verklig
signering, vanlig block-/TX-kontroll, exekvering och synkron beständig lagring
kördes. Inga acceptansregler eller datagränser ändrades för provet.

| Observation | Uppmätt resultat |
|---|---:|
| Antagna block med 5 000 TX vardera | 217 |
| Unika signerade TX vid gränsen | 1 085 000 |
| Antagen rå payload | 536 532 573 byte |
| Oförändrad gräns för vald rå historik | 536 870 912 byte |
| Nästa avvisade 5 000-TX-block | 2 475 573 byte |
| Blockgenerering och faktisk TX-signering, summerad tid | 36,830 s |
| Native FinalizeBlock, summerad tid | 64,195 s |
| Native Commit, summerad tid | 1,879 s |
| Återöppning med full signerad genesisåterspelning | 62,187 s |
| Hela workloaden inklusive felprov och återöppning | 169,482 s |

Go kördes med GOMAXPROCS=2 och GOMEMLIMIT=384 MiB. Hårda gränser var
768 MiB per process och 1,5 GiB för jobbets processer, med CPU-/tidsbudgetar.
Observerad högsta summerade RSS för Go-byggets/testets processträd var
624 631 808 byte. Det är varken telefonminne eller hela Desktop-processens RAM.

Det är en ABCI-applikation på en Windowsvärd. Inga SDK-röster, nätverkslänkar,
fysiska Linux-/Termux-värdar, klientkvitton eller UI-hastigheter mättes här.
Applikationens deterministiska tillstånd är därför inte ett nytt bevis om
fyrvalidatorsfinalitet. Rålogg, workloadens överlagringskälla och bundna
resultat bevaras lokalt; provet körs inte vid normal start eller installation.

## Felprov och återhämtning

Nästa verkligt signerade 5 000-TX-block överskred bytegränsen. Direkt
exekvering avvisade med GG_DAG_EXECUTION_LIMIT, ProcessProposal avvisade,
FinalizeBlock lämnade inget committbart tillstånd och Commit kunde inte
publicera det. En genomgång av databasens samtliga faktiska nycklar och värden
visade att den kanoniska historiken var oförändrad.

En mindre korrekt signerad nästa transaktion fick fortfarande plats. Dess
verkliga beständiga skrivgräns injicerades med ett I/O-fel. Noden gav inget
protokollröstresultat, avvisade ny admission medan lagret var felmarkerat och
ändrade inte den beständiga historiken. Operatörens disk fylldes inte.

Återöppning verifierade alla originalblock och TX-signaturer från genesis.
Exakta rötter, producentidentiteter, sekvenser och noncer bestod. Äldsta
payloaden var byteidentisk, äldre och aktuella konto-/block-/ordningsbevis
verifierades, och återspelningen ändrade inte databasen. Ägaren kunde därefter
antaga exakt en ny transaktion med nästa nonce. Detta ersätter inte ett prov
med fysisk disk full, en avbruten fsync eller oberoende felområden.

## Fynd och beslut

Den tidigare planeringsaritmetiken bekräftas nu med verkliga lagrade block:
dagens råhistorikgräns rymmer 217 sådana block. Om det obekräftade arbetsmålet
200 block/s användes skulle dessa block motsvara 1,085 sekunders historik.
Det är ett villkorat scenario; nätverket uppnådde inte den hastigheten.

Enbart det summerade FinalizeBlock-steget tog ungefär 0,296 s per block i
denna körning. Att invertera detta till cirka 3,38 block/s utesluter signering,
transport, SDK-konsensus och övrigt arbete. Det är ingen uthållig nätmätning
och ingen garanti om linjär skalning med fler CPU-kärnor.

En större konstant skulle flytta stoppet och behålla problemet. Historiska
vald-data får inte kastas medan en fullnod fortfarande påstår att den kan
återspela och tillhandahålla den ursprungliga historiken. Inga gränser höjs,
ingen historik beskärs och ingen snapshot börjar godtas av denna granskning.

## Primärkällor och tillitsgräns

CometBFT v0.40 state sync förutsätter applikationsstöd och en uttrycklig
light-client-förankring med betrodd höjd/hash, trust period och minst två
RPC-källor. Det ger inte dagens GG-applikation snapshotstöd automatiskt.
[CometBFT:s egen dokumentation](https://raw.githubusercontent.com/cometbft/cometbft/v0.40.0/docs/core/state-sync.md).

Bitcoin Core skiljer antagen snapshot-historik från bakgrundsvalideringen som
senare verifierar den tidigare historiken. Separata chainstates och exakta
övergångar är en del av konstruktionen.
[Assumeutxo-design](https://github.com/bitcoin/bitcoin/blob/master/doc/design/assumeutxo.md).

EIP-4444 är fortfarande ett utkast. Det kopplar historikborttagning till
checkpoint-bootstrap och weak subjectivity samt beskriver tillgänglighets-
och centraliseringsrisker för äldre data. Det bevisar inte säker pruning för GG.
[EIP-4444](https://eips.ethereum.org/EIPS/eip-4444).

Egen slutsats: nästa kodfas behöver en versionsbunden policy för beständigt
arkiv, retention, återstart och tillgång till originaldata. Lokal resursbrist
måste skiljas från en transaktions konsensusgiltighet. Bootstrapens
verifieringsomfång måste vara explicit och bevara identitet, ägare, noncer och
valda rötter. Ett sådant protokollbyte får inte smygas in som en cacheoptimering.

## Antaganden och kvarstående krav

200 block/s är fortfarande ett arbetsantagande. Uthållig end-to-end-kapacitet,
fysisk acceptans, lång partition, verkligt disktryck och oberoende
säkerhetsgranskning återstår. Offentlig monetär modell, medlemskap,
miningbelöning och poolutbetalningar är inte definierade av de sex
icke-finansiella testproducenterna. Inget publikt testnät eller huvudnät
aktiveras och denna komponentgranskning gör inte hela leveransen färdig.
