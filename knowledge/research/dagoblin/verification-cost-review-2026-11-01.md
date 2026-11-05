# DAGoblin: uppmätt verifieringskostnad och begränsat nyckelcache

## Ursprunglig avsikt och fynd

Optimera riktiga signerade transaktioner och behåll exakt samma säkerhetsregler.
Den beständiga metadatarepresentationen är verifierad separat. Nästa mätning
av den verkliga native-exekveringen visar att kurv-/signaturarbete dominerar
CPU-profilen. Samma producentnyckel kontrollerades på nytt för varje TX.

Den isolerade arbetslasten återspelar samma fyra offentliga signerade block
med totalt 5 015 transaktioner, varav ett block har 5 000 TX. Varje iteration
skapar en ny kandidat från samma tomma bas och verifierar/exekverar alla TX.
Det är beräkningskostnad för upprepad återspelning, inte nya unika användar-TX,
SDK-finalitet, nättrafik eller uppmätt kapacitet på flera fysiska enheter.
Fixturen innehåller endast disponibla offentliga testdata.

Basprovet på Windows/AMD Ryzen 7 7735HS med GOMAXPROCS=2 gav tre körningar
kring 626–633 ms per arbetslast, cirka 7 916–8 010 återspelade TX/s. Loggar,
CPU-profiler och källversioner sparas i den privata mätningsetappen. Senare
resultat jämförs som observerade prov, utan garanti om samma hastighet under
andra belastningar eller på Linux/Termux. Allokerade byte per operation är
kumulativa allokeringar, inte uppmätt peak-RAM.

Efter ändringen och avslutade bygg-/regressionsjobb gav tre nya prov
482–542 ms, cirka 9 252–10 403 återspelade TX/s. Medianen var cirka 526 ms
mot 628 ms före ändringen: cirka 16 procent kortare observerad körtid.
Tre sekventiella prov är ingen statistisk prestandagaranti. Ett tidigare
prov som överlappade regressionstester är sparat separat och används inte
för dessa slutsiffror. Nätets genomströmning eller slutlig finalitet har
inte mätts i detta prov.

## Beslut och ändring

Ett gemensamt native-/WASM-cache behåller högst 256 offentliga nycklar som
redan klarat den oförändrade kontrollen av kanonisk kodning, icke-identitet och
primär undergrupp. Nyckeln kopieras till en ägd 32-byte-array före kontroll och
lagring. Cachet innehåller inga privata data, signaturer, meddelanden eller
negativa valideringsresultat. FIFO-utkastning påverkar endast kostnaden.

Dyra cachemissar kontrolleras utanför cachelåset. Samtidiga träffar/insättningar
skyddas av ett eget litet mutex; dubbla samtidiga kontroller får inte skapa
extra poster. Cachet är lokalt och ingår inte i konsensustillstånd eller hashar.

Varje transaktion måste fortfarande ha korrekt signaturpunkt och kanonisk
skalär samt klara full Ed25519-verifiering för sitt aktuella meddelande.
Ingen verifiering av en tidigare signatur återanvänds. CometBFT:s röstregler,
noncer, kontobalanser, utbudsregler och exekveringsordning ändras inte.

## Verifiering och begränsningar

Riktade tester passerar över cachegränsen med separata giltiga testnycklar,
ändrar anroparens byte efter en träff och provar felaktiga storlekar,
identitet/torsion, samtidiga anrop, ändrat meddelande, ändrad signaturpunkt
och felaktig skalär. Tidigare externa signaturvektorer och alla historik-,
återhämtnings-, SDK- och UI-prov ska därefter passera på samma källversion.
Byggen och faktiskt körda WASM-artefakter binds till verifieringskvittot.

Detta är ingen ny kryptografisk algoritm eller bevisad huvudnätsberedskap.
Målet 5 000 TX/block vid hundratals block/s är fortfarande inte uppnått.
Nätöverföring, ytterligare signaturkostnad, parsning, ordningskontroller,
diskpolicy, medlemskap, monetär modell, mining/pooler och oberoende acceptans
återstår. Ingen fysisk provstart, bootstrap, Git-push eller appomstart utförs
genom denna lokala optimering.
