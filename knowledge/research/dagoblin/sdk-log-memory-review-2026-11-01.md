# DAGoblin: minnesfel i SDK:ns mempoolloggning

## Ursprunglig avsikt och observerat fel

Granska vårt verkliga nät och dess beroenden före nästa push och fysiska prov.
Tidigare prov med 5 000 TX och rena native-prov med 50 000 TX räckte inte för
att visa att hela SDK-kedjan klarar det största tillåtna TX-antalet per block.

Ett nytt ägt fyrnodsprov med 50 000 riktiga signerade TX stoppade före första
DAG-certifikatet. Batchen accepterades till mempoolen men en SDK-process
slutade svara medan andra bytte runda. Provet underkändes och upprepades med
offentliga räknare och begränsad diagnostik. Ingen fysisk enhet eller
operatörsprocess användes. Ingen genomströmnings- eller huvudnätsberedskap
kan härledas från detta prov.

En funktionstack från den exakta disponibla SDK-processen visade kedjan
`runtime.throw → runtime.sysUsedOS → mallocgcLarge → slicebytetostring →
fmt.Sprintf → types.Tx.String → mempool.(*Reactor).Receive`.
Diagnostiken läste enbart funktionsnamn; inga variabler, argument, nycklar
eller minnesdumpar sparades. Debuggerns tillfälliga paus var ett separat
diagnostiskt prov, aldrig ett godkänt acceptansprov.

## Rotorsak och ändring

Den pinnade CometBFT-koden anropade `ntx.String()` direkt i två logggrenar
för dubbla eller avvisade mempooltransaktioner. Det gör hela batchen till
hextext innan loggern anropas, även med en logger som kastar bort alla rader.
En stor laglig batch kräver då stora ytterligare strängallokeringar. Det
fångade minnesfelet låg i denna formattering under nodens befintliga
512 MiB-gräns. Det var inte ett negativt signaturbeslut.

Endast dessa två loggargument ändras till `ntx.Hash()`. Transaktionskropp,
signaturer, konsensus, utbud, noncer och blockgiltighet ändras inte. Hashen
kräver begränsad resultatlagring och loggen innehåller inte hela TX-kroppen.
Processernas befintliga minnes-/CPU-gränser och acceptansprovets tidsgräns
behålls.

Efter loggändringen fortsatte alla fyra SDK-processerna arbeta, men de korta
väntetiderna gav fortfarande upprepade rundbyten under validering av den
största batchen. DAG-lägets övre väntetider för proposal/prevote/precommit
justeras därför till 30/15/10 sekunder med ändliga ökningar per runda.
En färdig ärlig quorum går vidare direkt; detta är inte en extra fast väntan
för varje block. En dålig eller saknad proposer kan däremot ge längre
återhämtningstid, vilket måste ingå i fortsatt fel-/uthållighetsacceptans.

## Leverantörskod och byggintegritet

SDK-versionen ligger kvar på v0.40.0. Detta är en lokalt granskad ändring,
inte ett påstående att en ny officiell SDK-release används. Originalets
fullständiga Go-modul-ZIP verifieras med Go:s h1-algoritm mot den befintliga
go.sum-posten. De två exakta förekomsterna och källfilens hash måste stämma.
Även den härledda filen och hela härledda modulen binds med egna hashar.

Go tillåter inte compiler-overlay av filer i GOMODCACHE. Därför härleds en
separat verifierad SDK-kopia från originaldistributörens modul-ZIP och väljs
endast i byggets alternativa modfil. Projektets go.mod/go.sum och den
ursprungliga modulcachen ändras inte. Saknade, extra, ändrade eller länkade
filer i den härledda cachen stoppar bygget. Byggrutinen, receptet och dess
kontrollvärden ingår i källfingeravtrycken och byggkvittona. Native-/WASM-
valideringen kräver samma deklarerade recept. Leverantörslicenser bevaras.

## Verifiering och kvarstående arbete

Riktade tester kontrollerar att ändrad originalkod, fel antal förekomster
och fel slutresultat inte kan byggas med receptet. Det stora fyrnodsprovet
ska därefter köras utan debugger och med samma resursgränser, inklusive
undanhållen källa, skadade chunkar, exakt korrekt återhämtning och omstart.
Slutliga resultat binds i etappens verifieringskvitto. Ett misslyckat större
prov får inte döljas av att tidigare mindre regressionsprov passerar.

Det ursprungliga 90-sekundersprovet med 50 000 TX passerade inte efter dessa
ändringar. En separat längre observation under samma minnes-/CPU-tak
passerade inte heller och en SDK-process avslutades med felkod 2. Den längre
observationen räknas inte som det ursprungliga acceptansprovet. Det finns
alltså ytterligare resurs-/processproblem i det största nätfallet. Loggfelet
är en verifierad konkret allokeringsorsak, men ändringen är ingen visad
fullständig lösning på maximal SDK-last. Fallet kvarstår som publiceringshinder.

Gränserna för historik och rådata kvarstår. Uthålligt kapacitetsmål, fysisk
fel-/uthållighetsacceptans, offentligt medlemskap, monetära regler,
mining/pooler och oberoende granskning återstår. Ingen Git-push eller publik
aktivering görs genom denna lokala ändring.
