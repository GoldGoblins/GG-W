# DAG-data bundna till ett certifierat applikationstillstånd

Detta är en lokalt verifierad, opublicerad prototyp för det femte kodlagret.
Hela leveranskontraktet är fortfarande ofärdigt. Ingen app har startats om och
ingen ny fysisk Linux-/Termuxkörning eller Git-publicering ingår i detta prov.

## Ursprunglig avsikt och beslut

CLI-noden ska vara källa till verkliga signerade block och kontotillstånd.
Desktop ska visa dessa uppgifter korrekt. En långsam klient ska inte bli en
obligatorisk röst eller ge sken av global finalitet genom sin synkkvittens.

Den befintliga CometBFT-kommittén behålls: fyra fasta testvalidatorer med lika
vikt och SDK-kontrollerat kvorum om tre. DAG-producenterna, de anslutna
LAN-apparaterna och dessa validatorer är skilda roller. Alla fyra validatorer
i detta prov ägs av samma lokala kontrollör på samma Windowsdator. Detta
bevisar inte oberoende operatörer, publik antagning eller huvudnätssäkerhet.

## Implementerad bindning

Native-genesis v2 förankrar DAG-nätets identitet, befintlig offentlig genesis,
sex producentnycklar, signerad rosters tillåtna producentplatser och strikt
signaturprofil. Python härleder dessa uppgifter från en installerad LAN-nod.
En aktiv kommitté kan inte tyst byta DAG-källa. V1 förblir den separata äldre
testledgerns format; dess regressionstester finns kvar.

Varje konsensusbatch innehåller fullständiga signerade blockdata. Go verifierar
varje transaktion och blocksignatur, egen producentsekvens, nonce, rollpolicy,
föräldrar, rang, rot och belopp. Ordningen inom batchen är rang följd av
innehållsidentitet. Konsensus väljer ordningen mellan batcher. En okänd
förälder eller en konflikt avvisas; en lokalt mottagen graf räcker inte.

Applikationsroten binder DAG-kontorot, blockordningens medlemskapsrot,
checkpointkedja, vald payloadmanifest och verkliga antal block/transaktioner.
Tidsregeln använder förslagets konsensustid, aldrig varje verifierares egen
väggklocka. Mempoolens tidlösa förkontroll är inte ett certifierbart tillstånd.

Den native LevelDB-lagringen skriver payload och manifest atomiskt med
synkron beständig skrivning före PrepareProposal/ProcessProposal lämnar
godkännande. En senare synkron commit väljer exakt förberett tillstånd.
Förberedd data väljs alltså inte automatiskt som kanonisk. Lagringsfel
stoppar fortsatta acceptanser; även förlorat svar efter genomförd skrivning
provas. Återöppning återverifierar den beständiga manifestkedjan och all
vald exekvering. Saknad eller ändrad data repareras inte tyst.
[LevelDB WriteOptions](https://pkg.go.dev/github.com/syndtr/goleveldb/leveldb/opt#WriteOptions).

Lagringens garanti förutsätter filsystemets/enhetens synkroniseringskontrakt.
Provet är inte ett strömavbrottsprov på fysisk lagringshårdvara eller ett
bevis mot återställning av en hel äldre, tidigare giltig diskavbild.

Kontobevis och blockbevis verifieras av samma Go-regler i native och WASM.
De förankras i ett SDK-verifierat certifikat vid nästa native-höjd, vars
AppHash binder det visade applikationstillståndet. Beviset väljer inte själv
sin kommitté. Index, riktning och duplicerad udda Merkle-gren kontrolleras.
Ett blockbevis binder dess innehållsidentitet, producent, sekvens, plats och
transaktionsantal. Detta är certifierat medlemskap, inte ett påstående att
lättklienten själv har spelat igenom global historik.

DAG-tillgången är fortsatt `PRODUCER_OWNED_NONFINANCIAL`: sex testkonton,
belopp ett och utgifter begränsade av producentens ursprungliga allokering.
Den är inte samma tillgång som native-ledgerns GG-NET-TEST. Ingen monetär
huvudnätsmodell, miningbelöning eller poolutbetalning har införts genom denna
bindning.

Native-överföringar och DAG-batcher läggs i separata konsensusblock. Båda
transaktionstyperna finns kvar, men blandade block avvisas även vid direkt
ProcessProposal/FinalizeBlock. Därmed behåller den äldre testtillgångens
avgränsade exekveringsbevis en komplett återspelning av sitt block. Detta
provas också efter en verkligt committad DAG-checkpoint i native-ledgern.

## Fynd och verifiering

69 Go-testfall inklusive underfall passerade utan överhoppningar. De omfattar
befintlig native-ledger, verkliga Python-signerade payloads, otillåtna roller,
felaktiga signaturer/noncer/föräldrar, atomisk exekvering, lagringsfel före
och efter synkron skrivning, exklusiv databasägare, ändrade data, historiska
bevis, SDK-kvorum och manipulerade bevis. En annan giltig yttre signatur för
samma blockinnehåll får inte förgifta en alternativ kandidats payloadcache.

En separat WASM-körning accepterade giltigt certifierat medlemskap och
avvisade tio manipulationer av saldo, nonce, gren, block, förankring och
kvorum. Den laddade ingen global DAG-historik. Uppmätt linjärt WASM-minne
var 19 922 944 byte i provet; detta är inte telefonens totala resurskostnad.

Det verkliga fyrprocessprovet certifierade först fyra Python-signerade
DAG-block med sammanlagt 5 015 individuellt signerade transaktioner, varav
ett block hade 5 000 TX. Kontoresultatet matchade Python-exekveringen.
WASM verifierade konto- och blockbevis från det verkliga processcertifikatet.
En terminerad process återöppnade exakt samma checkpoint. Därefter
certifierade tre levande validatorer nästa batch, två certifierade inte
den väntande batchen, en tredje återstartade och certifierade samma väntande
batch utan omsändning, och den fjärde hann ikapp. Slutresultatet var sex
block och 5 018 TX.

Den samlade Python-/runtime-/UI-regressionen passerade 337 tester med noll
fel och noll överhoppningar. Källfilerna var oförändrade under den körningen.
CLI:s explicita paketlista behövde därefter den nya rena backend-modulen.
De tre opublicerade källarkiven innehåller 118 granskade filer och har
kontrollerats byte för byte. Den projicerade CLI-miljön importerades utan Qt,
nyckelskapande eller öppnade sockets. Linux-/Termuxarkivens innehållskontroll
är inte körningsverifiering på dessa operativsystem.

Tre första stora processprov nådde sin 45-sekundersgräns utan certifierad
DAG-uppdatering. Diagnostik
visade upprepade nil-röster medan den tidigare småtransaktionsdemons
400 ms-förslagsbudget löpte ut under mottagning/verifiering av cirka
3,3 MB. V2 har därför en större initial förslagsbudget och omröstningsbudget.
Kvorum och signaturkontroller har inte sänkts. Detta rättar observerad
framstegsförlust; det är inte en genomströmningsoptimering eller ett bevis
för hundratals block per sekund.

## Återstående arbete och gränser

Den ordinarie LAN/CLI/Desktop-vägen har ännu ingen komplett anslutning till
batchinlämning, certifierad återhämtning och en verklig DAG-lättklientroll.
`canonical_finalized` i befintlig LAN-vy aktiveras därför inte av detta prov.
Det nya backend-API:t kan starta en uttryckligt vald lokal DAG-testkommitté
och exportera verifierade medlemskapsbevis; ingen sådan kommitté startar
automatiskt i den aktiva appen.

Publik Sybil-/medlemskapspolicy, flera oberoende validatoroperatörer,
nyckelrotation/epoker, konfidentiell publik transport, säker långtidspruning,
extern checkpointförankring, bysantinska withholding-/equivocationfall och
lång uthållighetsverifiering är fortfarande öppna krav. Lagringen och
batcherna har ändliga experimentgränser; de är inte en obegränsad kedja.
Ocommittade kandidaters cacheinsamling behöver också en verifierad regel;
nuvarande ändliga gränser stoppar förbrukning men garanterar inte fortsatt
framsteg under obegränsad tillförsel av giltigt signerade alternativ.
Validatorernas identiteter är fortfarande kontrollörens RAM-ägda testnycklar.
Processåterstarten behåller dem; en fullständig kontrollörsavslutning är inte
en beständig publik kommitté. Ett gemensamt auktoritativt konsensusankare i
LAN-genesis och senare epoker måste bindas innan prototypen får presenteras
som hela LAN-nätets kanoniska finalitet.
Målet 5 000 TX/block vid hundratals block/s är fortfarande ouppnått och
omätt. Enstaka större block gör inte det kapacitetskravet godkänt.
