# DAGoblin: automatisk checkpoint och bevisat blockmedlemskap

Detta fortsätter CLI-/Desktop-etappen. Arbetet är lokalt verifierad privat
LAN-kod; det är inte ett färdigt publikt nät eller ett uppnått kapacitetsmål.

## Ursprunglig avsikt

Varje producent äger sina egna signerade block. Noder arbetar i egen takt.
CLI/backend gör arbetet, och Desktop ska återge verifierade fakta från samma
nod. Lokalt godtagande, transportkvittens och konsensus får inte blandas ihop.

## Fakta och upptäckter

Den befintliga CometBFT-kedjans AppHash binder DAG-ordningsroten. En ny ABCI-
fråga `/gg/dag/order-page` lämnar högst 32 efterföljande medlemsbevis under
en gemensam kontext. Startpositionen är en nollbaserad sidgräns. Sista sidan
måste innehålla alla återstående löv; tom efterföljande sida tillåts inte.
Tom genesis har en unik tom sida. Native- och WASM-verifieraren delar samma
SDK-kontroll av certifikat, förankrad genesis, höjd, tillståndsrot, DAG-kontext,
producentpolicy, exakt position och Merkle-väg. Utelämning, omordning, dubblett,
felaktig avslutningsflagga och ändrad kontext avvisas. Ett sidbevis säger
medlemskap, inte att lättklienten själv exekverat alla tidigare transaktioner.

Controller läser samtliga sidor under ett och samma certifierade tillstånd
och kontrollerar hela ordningens antal, TX-summa och producentsekvenser innan
den publicerar medlemskap. Ett saknat eller felaktigt sidbevis ger ingen
partiell lyckad delvy. Ett oförändrat DAG-åtagande kan återanvända tidigare
verifierade medlemskap när nästa SDK-certifikat binder exakt samma åtagande.
Statusvisning väntar fortsatt inte på detta arbete.

Granskningen hittade ett tidigare regelglapp: native-exekveringen tillät tomma
DAG-block men åtagande-/medlemsverifieringen krävde minst en TX per block.
Verifieringen tillåter nu samma signerade tomma block som exekveringen.
De ökar blockantalet och producentsekvensen men tillför exakt noll TX.
Övre TX-gränser, signaturkrav, kausalitet och saldo-/nonce-regler är kvar.

## Beslut och implementation

En uttryckligen startad validator i en signerad konsensussession underhåller
checkpoints automatiskt. Den väljer redan lokalt godtagna signerade payloads
mot den kompletta certifierade ordningen. Kända kanoniska block utelämnas.
Föräldrar måste vara tillgängliga i kanonisk historik eller vald batch, och
varje producents nästa block måste fortsätta rätt egen sekvens och huvud.
Batchen sorteras efter rank och blockhash och begränsas till 128 block,
32 MiB avkodade payloads och 48 MiB kodad begäran. Det finns ingen väntan på
att alla anslutna fullreplikor har verifierat varje block.

Validatorprofilen sparar begärans publika identitet, föregångare, sekvens och
ordnade block-ID:n synkront före sändning. Payloads finns redan i LAN-nodens
beständiga journal. Vid återstart måste exakt samma bytes kunna återskapas;
förlorad eller ändrad payload stoppar i stället för att ersättas. Varje ägd
controller gör högst ett sändningsförsök för samma väntande begäran. En ny
controller efter återstart kan skicka exakt samma begäran igen; föregångare,
sekvens och identiskt innehåll förhindrar en andra exekvering.

`MEMPOOL_ACCEPTED`, `REJECTED` och `BROADCAST_UNKNOWN` ger ingen finalitet.
En väntande begäran ersätts först när ett nytt verifierat DAG-åtagande visar
att dess föregångare passerats. Kompletta medlemsbevis avgör vilka block som
certifierats; konkurrerande batcher kan ha certifierat samma block eller bara
en delmängd. Kvarvarande giltiga block väljs då mot den nya kanoniska historiken.
Detta påstår inte ett separat bevis för den stora batchens native-TX-inclusion.

Desktop projicerar endast medlemskap som controller faktiskt verifierat.
Kanoniskt antal räknas för lokalt tillgängliga block; certifierad DAG-rot visar
separat nätets certifierade total. Bevisade synliga block får bock/markering,
kanonisk position och förklaring i detaljvyn. Andra signerade block är fortsatt
ofinaliserade. Genesis får ingen påhittad producent eller finalitetsstämpel.
En fullreplika utan certifikatflöde får fortfarande noll som bevisat antal.

## Verifiering och avgränsning

Go-tester omfattar historiska flersidiga ordningar, SDK-kvorum, mutationer,
tom genesis, signerade tomma block och sidstorlek vid maximal tillåten
4095-blockshistorik. Python-tester använder riktiga signerade/admitterade
payloads för kausalt val, egna sekvenser, batchgräns, byteexakt återställning,
saknade payloads och sparningsfel före broadcast. Qt/QML provas offscreen.

Ett separat prov kör fyra riktiga SDK-processer och tre temporära LAN-ägare
på en fysisk Windows-värd. Det certifierar automatiskt ett 5 000-TX-block och
33 block från en annan producent. Native verifierar ordningen över två sidor;
WASM verifierar en 32-lövssida och avvisar mutation. En ytterligare begäran
sparas utan sändning, alla LAN-/validatorprofiler stängs, och återstarten
återskapar begäran byteexakt och certifierar dess block. Vanlig autentiserad
LAN-gossip hämtar sedan samtliga 35 block/5 034 TX till alla tre ägarna.
Fullreplikan räknas inte som certifikatverifierare. Detta är inte ett prov
på fysiska Linux-/Androidmål eller ett uthålligt hastighetsprov.

## Öppna krav och antaganden

Den fasta privata kommittén har fyra identiteter, kvorum tre och ingen
ny publik Sybil-/medlemskapspolicy. Signerade block och individuella TX är
fortfarande producentägda icke-finansiella testposter; mining, poolutbetalning
och monetär huvudnätsmodell är inte genomförda.

Certifikat-/medlemsflöde till fullreplikor och en riktig lättklient har därefter
lagts till i [roll- och bevisgranskningen](replica-light-proof-review-2026-10-31.md).
Grenåterhämtning vid equivocation, beständig spridning av verifierade
konflikter mellan controllers och insamling av ocommittade kandidater återstår.
Maximal historiks återhämtningstid och arbete under samtidiga nya rötter är
inte verifierade av sidstorleksprovet. P2P-budgetar, fysisk transport, pruning,
uthållig kapacitet och oberoende säkerhetsacceptans är fortfarande öppna.
Inga automatiska appomstarter, bootstrapuppdateringar eller Git-pushar görs
under denna interna etapp. Hela åttastegskontraktet är inte klart.
