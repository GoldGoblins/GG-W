# DAGoblin: begränsad parallell signaturkontroll

## Avsikt och observerad kostnad

Riktiga transaktioner ska verifieras innan deras resultat publiceras. En
långsammare nod ska arbeta inom sin egen resursbudget utan påhittad trafik,
räknad men overifierad historik eller sänkta signaturkrav.

Profilering av ett verkligt block med 5 000 individuellt signerade TX visar
att standardverifierarens kurvoperationer dominerar CPU-kostnaden. Den
tidigare sekventiella kontrollen tog i denna lokala mätning cirka 0,33 s per
verifierande ABCI-fas med GOMAXPROCS=2. Den nya körningen tog cirka 0,21 s.
Full signerad återöppning tog cirka 0,36 respektive 0,24 s. Commit var under
2 ms i båda enskilda observationerna; dess mycket korta tid varierar.

Detta är ett före-/efterprov av komponentkostnad på en Windowsdator. Samma
5 000 unika TX återexekveras i flera faser; de räknas inte som nya TX varje
gång. Det är varken en uthållighetsmätning eller verifierad nätkapacitet.
Resultaten bevisar inte hundratals block per sekund. Profiler, fixture och
ursprunglig baslinje behålls separat från de slutliga integrationsproven.

## Beslut och genomförande

Block med minst 256 TX får högst min(GOMAXPROCS, 8) arbetare. Små block och
processer med en CPU-budget på en kör sekventiellt. Arbetarna startas per
kontroll och inväntas alltid innan den returnerar. Antalet goroutiner växer
inte med antalet TX; varje arbetare bygger bara ett meddelande åt gången.
Arbetsindex och avbrottsflagga är atomiska. Misslyckad kontroll stoppar nya
jobb när felet har publicerats; redan pågående jobb får avslutas och joinas.
Det finns ingen global bakgrundspool eller signatur-/meddelanderesultatcache.
CPU-budgeten är en processinställning, inte ett påstående om mobilens kapacitet.

Billiga kontroller av kedja, konto, belopp och hela noncesekvensen utförs
först. De använder utgångsnoncen plus TX-positionen inom samma befintliga
allokeringsgräns. Därefter kontrolleras varje signatur med exakt den tidigare
strikta verifieraren och samma domänseparerade kanoniska meddelande. En
publiknyckel avkodas en gång per block. Godkända publika punkter får använda
det redan befintliga, begränsade punktcachet; kryptografiska beslut cachas inte.

Först efter lyckad join uppdateras saldo och noncer, sekventiellt i den
ursprungliga ordningen. Inget arbetarschema väljer tillståndsrot eller
finalitet. Kandidatens gamla bas är oförändrad vid fel. De befintliga reglerna
för förberedelse, signerad återspelning och atomisk Sync/Commit består.

Kontroller som tidigare var sammanvävda görs nu i faser. Ett block med flera
oberoende fel kan därför få en annan första felkod. Mängden accepterade
block och de godkända blockens tillstånd måste vara densamma.

Native och WASM bygger samma nya källfil. Den synkrona WASM-miljön använder
sin befintliga CPU-budget på en; ingen ny trådbehörighet införs.
Det befintliga bygggraphtestet binder även körtidskontrollens källfingeravtryck
till samma fullständiga fillista. Första nya artefaktkontrollen avvisade en
missad uppdatering av just körtidslistan innan sviten startade. Listan är nu
uppdaterad; kontrollen behåller sitt krav på exakt matchning.

## Komponentprov och samtidighetsgränser

En oberoende kopia av den tidigare sekventiella TX-kontrollen och saldofolden
används som referens. Verkliga signerade block runt tröskeln och med 5 000 TX
jämförs vid CPU-budget 1, 2 och 8. Konto-/nonceutfall och förseglade åtaganden
måste vara identiska. Negativa prov täcker kedja, domän, ägare, mottagare,
belopp, nonce, allokering, över-/undersaldo och motstridiga fel i samma block.

Instrumenterade callbacks anropar den verkliga strikta verifieraren och
räknar varje kryptografisk kontroll, även vid upprepad identisk körning.
Signaturmutationer placeras först, mitt i och sist i blocket. En barriär
håller åtta faktiska kontroller öppna för att bevisa arbetartaket och att
retur inväntar pågående jobb. Ett separat deterministiskt prov kontrollerar
tidigt avbrott utan antaganden om OS-schemaläggningen. Tomma och för stora
TX-listor ska göra noll kryptografiska anrop.

Denna begränsning gäller en verifieringsinvokation. Den inför inte någon ny
global antagningskvot över alla möjliga samtidiga anrop. Tillståndsobjektet
har fortfarande en ensam skrivare; parallella läsare får inte ändra dess
avkodade kandidat medan arbetarna använder den. Ingen extern otestad anropare
får behandla hjälpfunktionen som en trådsäker generell tillståndsmotor.

## Primärkällor och kvarstående frågor

Go dokumenterar [GOMAXPROCS](https://pkg.go.dev/runtime#GOMAXPROCS),
[atomiska operationers ordning](https://pkg.go.dev/sync/atomic) och
[WaitGroup.Wait](https://pkg.go.dev/sync#WaitGroup.Wait). Dessa avgränsar
resursval, synkronisering och retur efter join. De ersätter inte egna
signatur-, acceptans- eller lagringsprov.

Slutliga native-, WASM-, Python-, SDK- och UI-resultat binds separat till
oförändrade källor och artefakter. Ett korsbygge är ingen fysisk Linux- eller
Termuxkörning. Ett tidigare oförklarat fixture-timeout behålls i gransknings-
historiken; det skrivs inte om till ett godkänt prov.

Långvarig hög last, större historik, långa partitioner, disktryck, fysisk
felprovning och säker publik ekonomisk modell återstår. Den nuvarande
icke-monetära sexproducentmodellen blir inte en publik valuta, pool eller
miningmodell genom att signaturkontrollen går fortare. Ingen absolut
säkerhet eller färdigt huvudnät påstås av denna ändring.
