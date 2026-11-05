# DAGoblin: beständigt register för exekveringshistorik

## Ursprunglig avsikt

Behåll nätverkets funktioner och låt långsammare noder arbeta i egen takt.
En nod och dess block ska ha samma verifierbara identitet i CLI och Desktop.
Optimera verkligt arbete utan att ersätta signaturer, exekvering eller
konsensus med visuella räknare. Samla kodändringarna före nästa fysiska prov
och publicering.

## Fynd och beslut

SDK-motorn kopierade tidigare hela historikens ordning, blockregister och
rankregister när en kandidat skapades. Rådata hade redan flyttats till ett
beständigt arkiv, men dessa historiska metadata låg fortfarande i RAM.

Exekveringshistoriken använder nu ett oföränderligt AVL-träd. Nycklar för
blockmetadata och ordningslöv ligger i samma träd. Varje nod binds till sitt
kanoniska innehåll med en separat domänseparerad hash. Insättning kopierar
bara sökvägar och balanseringsnoder; en kandidat delar oförändrad historik
med sin bas. Endast ännu ej committade rådata finns i kandidatens arbetsmängd.
Konton, producenthuvuden, sekvenser, noncer och Merkle-frontier har kvar sina
tidigare exekveringsregler.

En commit skriver endast nya nåbara trädnoder och vald rot i samma synkrona
LevelDB-batch som den kanoniska native-historiken och det publika bevisindexet.
RAM-vyn publiceras först efter lyckad Sync. Ett oklart slutförande låser
fortsatt skrivning; återöppning avgör det faktiska atomiska diskutfallet.
Förberedda men förlorande kandidater skriver inga historiska trädnoder.

Den kanoniska exekveringen behåller sedan en hashrot och en disk-läsare.
Metadata-cachet har högst 512 noder. Gamla trädnoder tas inte bort, så en
äldre kandidat eller fråga kan fortsätta använda sin ursprungliga rot.
Cachelåset hålls inte under disk-I/O. En långsam metadatafråga genom den
verkliga SDK-klienten ska därför kunna överlappa en ny faktisk DAG-commit.
En separat lässpärr skyddar databasens livstid: avstängning stoppar nya
metadataläsningar och inväntar pågående läsningar före DB.Close. Den håller
inte konsensus-, store- eller cachelåset över disk-I/O. Detta provas separat
med en avsiktligt pausad läsning och samtidig avstängning.

## Integritet och återöppning

Metadataindexets version 1 är separat från det publika bevisindexets version 2.
Gränserna är 2 048 byte per nod, 262 144 historiska noder och 128 MiB
logiska nyckel-/nodbyte. Detta är ändliga skyddsgränser, inte en uppmätt
lagringskapacitet eller gränslös historik.

Vid start återspelas fortfarande varje ursprungligt signerat block och varje
transaktion. Vid varje kanonisk checkpoint återskapas de härledda trädnoderna
och jämförs exakt mot lagringen. Samtliga förväntade noder, vald rot, antal
och storlekar måste stämma. Saknade, extra, ändrade eller felrotade
versionsmärkta data repareras inte tyst. Äldre databaser utan metadataindex
får det först efter lyckad full återspelning, i en atomisk migrering.

En tom autentiserad gren betyder att ett block saknas i historiken. En
förväntad trädnod som inte kan läsas betyder i stället lokal otillgänglighet.
CheckTx, PrepareProposal och ProcessProposal får inte omvandla det felet till
ett konsensusbeslut att en deterministiskt giltig transaktion är ogiltig.

## Granskning och verifiering

Riktade prov kontrollerar balans och innehållshashar, isolerade gamla rötter,
begränsade disk-sökvägar, tom kanonisk rådataarbetsmängd, återöppning och
fortsatt exekvering. Migrering provas före Sync och efter faktisk Sync med
förlorat slutförandebesked. Negativa prov ändrar enbart ägda testdatabaser.
Separata prov behåller tidigare oberoende fullordningskontroll, arkiverade
signaturkontroller, noncehistorik och gamla Merkle-bevis som orakel.

Slutliga antal, byggartefakter och oförändrade källor binds i etappens privata
verifieringskvitto. Native och WASM byggs om från denna källversion. Linux och
Android korskompileras; det ersätter inte fysisk körning på dessa enheter.
CLI-/Desktop-projektion provas utan att operatörens öppna app påverkas.

Bitcoin Cores egen rapport om CVE-2018-17144 visar att en optimerad kontroll
kan påverka monetär giltighet. Därför behålls oberoende slutlig validering även
när historikrepresentationen ändras. Detta är en tillämpad granskningsprincip,
inte ett påstående att GG använder Bitcoins konsensus.
[Bitcoin Core, originalrapport](https://bitcoincore.org/en/2018/09/20/notice/).

Den ekonomiska granskningen håller också isär blockproduktion, konsensusröst
och poolutbetalning. Moneros beskrivning av P2Pool visar hur poolandelar och
PPLNS-utbetalning kan organiseras samtidigt som deltagaren kontrollerar sin
nod. Det är ett referensexempel; dagens GG-testproducenter har inte blivit
PoW-miners eller fått verkliga poolbelöningar genom denna ändring.
[Monero, P2Pool](https://web.getmonero.org/2021/10/05/p2pool-released.html).

## Kvarstående arbete och antaganden

Kandidatkloning kopierar inte längre hela det kanoniska metadataregistret.
Vissa prepare-/commit-kontroller materialiserar fortfarande hela ordningen,
och klientens lövlistor är fortfarande ändliga. Start återspelar alla rådata.
Ingen av dessa återstående linjära kostnader döljs av det nya trädet.

Gränserna 4 095 block och 512 MiB ursprunglig rådata kvarstår. Maximal
nätåterhämtning, långa partitioner, disktryck, fysisk fel-/uthållighetsacceptans
och uthålligt kapacitetsmål återstår. Offentligt medlemskap, monetära regler,
mining/pooler och oberoende säkerhetsacceptans är inte färdigställda. Ingen
Git-push, appomstart, ny bootstrap eller publik aktivering görs genom denna
lokala etapp.
