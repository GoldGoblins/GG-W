# DAGoblin: exakt metadataövergång från beständigt vald rot

## Ursprunglig avsikt och fynd

Snabba producenter ska inte behöva göra om hela den gamla historikens arbete
för varje nytt block. Samma signerade data, ägare, konton och certifikat ska
fortfarande representeras korrekt i CLI och Desktop. Nästa push och fysiska
prov väntar tills den samlade kodfasen är klar.

Prepare och Commit läste tidigare hela ordningslistan, kontrollerade alla
gamla löv igen och byggde fullständiga Merkle-träd. Även prefixkontrollen
gjorde om det arbetet. Ett strömmande mellanled minskade allokeringen men
behöll linjärt arbete. Den vanliga livevägen har nu en oberoende kontroll
av den exakta metadataövergången från föregående beständiga rot.

## Genomförande och säkerhetsargument

Store behåller ett litet värdekopierat prefix: vald commitment, autentiserad
AVL-rot, befintlig Merkle-frontier, sex producenthuvuden, sekvenser, noncer
och byteantal. Prefixet publiceras först efter lyckad gemensam Sync. Efter
omstart skapas det först ur full signerad återspelning och exakt kontroll av
alla lagrade index. Ett versionsmärkt live-store utan detta prefix vägrar
arbete; det får ingen implicit tom eller godtycklig bas.

För varje nytt ordningslöv, högst 128 i en checkpoint, kontrolleras index,
producentroll, sekvens, transaktionsantal, motsvarande blockmetadata och
den separata väntande rådatapostens metadata. Wire-hasharna måste också
ha exakt manifestordning. Posterna sätts därefter oberoende in i den kända
gamla AVL-roten, i samma deterministiska b/- och o/-ordning som exekveringen.
Insättning kan inte ersätta gamla nycklar. Det avvisar både gamla och nya
dubbla blockidentiteter.

Den oberoende framräknade roten måste vara exakt kandidatens historikrot.
Med hashfunktionens kollisionsresistens och de oföränderliga gamla noderna
binder detta även allt gammalt innehåll. Kandidatens egna prefixpåståenden
används inte som bas. Alla nya RAM-objekts kanoniska innehåll, hash och faktiska
barnreferenser kontrolleras också, så en felaktig pekarstruktur inte kan
gömmas bakom en gammal cachad hash.

Samma nya löv läggs till en kopia av den beständiga Merkle-frontiern.
Hela frontiern, producenthuvuden, sekvenser, noncer, konto-noncer, totalt
transaktionsantal och byteantal måste stämma med exekveringen. Det gör även
en oförändrad checkpoint till en kontrollerad övergång. Bara den nya
lövsvansen lämnas vidare till det befintliga publika indexets atomiska batch.

Ingen signatur- eller meddelandeverifiering cachas eller tas bort. Signaturer,
rådataexekvering, nonce-/saldo-/föräldraregler och förberedelse före accept
behåller sina faktiska kontroller. Prepare-data och valda index har kvar
synkron beständighet och felstopp vid oklart slutförande. Oselekterade
fristående lagringsfixturer behåller den gamla fullständiga kontrollvägen.
Protokoll, lagringsschema, Merkle-domäner och signerade bytes ändras inte.

## Lagringsintegritetens omfattning

Gamla disk-noder autentiseras när en ändrad sökväg eller fråga använder dem.
Hela signerade historiken och alla förväntade lagrade metadata kontrolleras
fortfarande vid öppning. Varje nytt förslag är däremot inte längre en fysisk
genomsökning av alla gamla metadatafiler. Skada i en orörd gammal nod upptäcks
vid autentiserad åtkomst eller full återöppning. Saknade data får då aldrig
tolkas som giltig frånvaro eller repareras tyst; lokal otillgänglighet låses
och nya kvittenser stoppas. Detta beteende provas uttryckligen.

## Verifierat komponentomfång

Riktade prov använder verkligt signerade block och riktiga temporära LevelDB-
databaser. Varje checkpoint genom 129 jämförs med den tidigare fullständiga
ordnings- och prefixkontrollen. Negativa fall ändrar gammal ordning, gammal
och ny blockmetadata, frontier, producenthuvud, sekvens, nonce, byteantal,
konton, manifest, rådata, RAM-barnreferens och det beständiga prefixet.
Förlorat Sync-slutförande provas före och efter faktisk skrivning. Minnesprefixet
får inte flytta fram vid fel; återöppning måste finna exakt verkligt diskutfall.

Ett prov med 4 094 gamla signerade block och ett nytt block jämför samma
giltiga kandidat med den fullständiga referensen. En riktad körning gav
35 104 736 respektive 483 288 totalt allokerade byte och 4 090 respektive
48 metadata-Get. Endast ett nytt löv behölls i resultatet. Get-antal är
biblioteksanrop, inte fysiska IOPS; total allokering är inte topp-RAM.
Samlad regression, färska native-artefakter och verkliga SDK-/UI-felprov
binds separat till etappens oförändrade källor.

Två fel i de första nya provuppsättningarna är bevarade: en återanvänd helper
med fast checkpointtid gav ogiltiga senare kandidater, och en läsräknargräns
räknade felaktigt även nya RAM-noder som nödvändiga disk-läsningar. Tiderna
följer nu nästa verkliga checkpoint; läsgränsen härleds från antal faktiskt
bifogade nya objekt. Produktionskodens valideringskrav sänktes inte.

## Kvarstående arbete

Vanlig metadatakontroll följer nu nya sökvägar, ungefär O(k log n), där k är
antal nya block. Kandidater med fullt materialiserad äldre RAM-historik
kräver fortfarande kontroll av alla bifogade objekt. Startup/migrering gör
fortfarande full återspelning. Storets storlekskarta för kanoniska objekt och
vissa klientvyer har kvar kostnader som växer med historiken. Native-ledgern
skriver dessutom om sitt behållna fönster av högst 256 stateposter vid Commit;
det fönstret växer inte vidare med hela DAG-historiken. Detta är inte en
färdig obegränsad lagringspolicy.

Gränserna 4 095 block och 512 MiB, långa partitioner och disktryck, uthålligt
5 000 TX/block vid hundratals block/s, fysisk fel-/uthållighetsacceptans,
offentlig ekonomisk modell/mining/pooler/medlemskap och oberoende acceptans
återstår. Tidigare oförklarad tidsgräns i Go-verktygets fixturförberedelse
kvarstår i granskningshistoriken. Ingen push, appomstart, bootstrap eller
publik aktivering följer av denna lokala komponentändring.
