# Långsam egen producent: beständiga betalningar och begränsade återförsök

## Avsikt och avgränsning

En långsam producent ska kunna återuppta sitt eget redan kontosignerade arbete,
medan övriga producenter och validatorer fortsätter. CLI och Desktop läser samma
SDK-certifierade urval och kontotillstånd. Transportkvittens betyder varken
blockurval eller lyckad betalning. Denna ändring gäller det befintliga privata
monetära SDK-nätet; den aktiverar inte publikt nät, mining, belöningar eller pengar.

## Fynd

Producentjournalen behåller redan exakta original, även efter arkivering.
Den ursprungliga insändningsvägen gjorde däremot endast ett transportförsök.
Ett QUEUED-svar kunde följas av ett avbrott eller ett SDK-avslag utan automatisk
återhämtning. Source-v2 binder dessutom originalblock till signerad epok:
en checkpoint kan göra ett ännu inte valt original inaktuellt.

Den riktiga SDK-körningen hittade också ett routningsfel: en producent försökte
bara hos den första validatorägaren. En giltig beviscache behöver inte ha en
lokal insändningsauktoritet. Ett UNAVAILABLE-svar kunde därför hindra arbete
trots att en annan ägare kunde ta emot exakt samma original. Insändningen provar
nu andra berättigade ägare inom tidsbudgeten och roterar startägare mellan
försöken, så att en ägare som tar hela timeouten inte svälter övriga.

[CometBFT:s egen dokumentation](https://github.com/cometbft/cometbft/blob/main/docs/core/using-cometbft.md)
bekräftar att mempoolacceptans och `broadcast_tx_sync` inte garanterar commit.
[Det officiella RPC-kontraktet](https://github.com/cometbft/cometbft/blob/main/rpc/openapi/openapi.yaml)
beskriver CheckTx-resultatet. Slutsatsen för vår kod är att en sådan kvittens
aldrig får avsluta producentens återhämtning som SDK-vald.

## Beslut och implementation

* Varje uttrycklig insändning startar efter beständig originalskrivning ett eget
  ändligt återförsök: högst 16 försök och 180 sekunders arbetsbudget. Nätverks-
  och native-anrop behåller sina befintliga stopp- och tidsgränser. Pågående
  synkrona native-kontroller kan avsluta efter att arbetsbudgeten löpt ut.
* Journalen söker den senaste signerade epokens återstående sekvenser i både
  aktiva original och autentiserade egna arkiv. Native-verifierat producentbevis
  och exakta egna valda block bestämmer prefixet. Kontots nonce eller saldo
  används inte för att gissa vilka original som valts.
* Kontosignaturerna kontrolleras innan ett nytt producentbevis hämtas. Om urvalet
  hunnit framåt under kontrollen trimmas bara ett exakt certifierat originalprefix.
  Annars hämtas nytt bevis i ett senare begränsat försök.
* I samma epok skickas samma original igen. Efter en checkpoint får producenten
  skapa nya producentoriginal över oförändrade kontosignerade betalningar.
  Äldre original skrivs inte över. SDK kontrollerar själv signaturer, ordning,
  nonce och medel vid monetär exekvering.
* `lan.financial_resume` återupptar en uttryckligen vald egen producent från
  journalen utan att användaren behöver lämna betalningsfilen igen. Vanlig
  `lan.resume` startar fortfarande inte produktion.
* En aktiv återhämtning förhindrar en samtidig annan insändning i samma lokala
  tjänst. Låset hålls endast under det egna försöket, inte under väntetiden.
  Det finns ingen gemensam väntan på en långsam peer. Stoppsignalen hör till
  just den körningen och kan inte återställas genom en senare start.
* UI redovisar verkligt workertillstånd, försök, återstående arbete och separat
  SDK-urval. SELECTED påstår inte att alla betalningar lyckades; kvitton och
  certifierade konton bestämmer utfallet. Utan tidigare arbete blir tillståndet
  IDLE, utan urvalspåstående. Fel och uttömda försök behåller originalen.

## Verifieringens krav

Enhetstester använder riktiga skyddade profiler, kontosignaturer,
producentsignaturer, SQLite och egna arkiv. Syntetiska SDK-kontexter är uttryckliga
policyseams och är inte finalitetsbevis. De täcker delvis valt prefix,
epokbyte, återöppnat arkiv, avbrott, konkurrens, tidsgränser och falsk ACK-status.

Den isolerade integrationskörningen använder fyra riktiga SDK-validatorer och
signerad loopbacktransport. Den ska behålla två stora egna original, välja bara
det första, stänga den långsamma producenten, låta andra producenter gå vidare
över checkpoints och kallt återuppta den kvarvarande kontosignerade batchen.
Alla monetära effekter, gamla och nya kvitton, producentidentiteter, konto-
projektioner och stängda processer ska verifieras. Körloggarna skiljer Windows,
Linux och policyseams från fysiska Termux/LAN-prov och kapacitetsmätningar.

Native-/WASM-protokollet ändras inte i denna del. Tidigare kompilerade kandidater,
deras SDK-/Go-tester och den smala Ghidra-granskningen kan bara återanvändas om
både deras exakta filer och hela native-källidentiteten fortfarande stämmer.
Ingen ny fullständig binärgranskning eller ARM64-körning påstås.

## Öppet protokoll- och kapacitetskrav

Begränsade omsigneringar löser återhämtning när producenten till slut får ett
giltigt urvalsfönster. De bevisar inte godtyckligt fördröjda original över ett
oändligt flöde av checkpoints. Det kräver separat versionshanterad protokoll-
design och bevis om det behövs vid slutkapaciteten. 5 000 verkliga TX per block
vid hundratals block per sekund är fortfarande ett mät- och acceptanskrav,
ingen uppnådd egenskap genom denna ändring. Fullständig säkerhet kan inte
garanteras genom intern granskning eller genom att inga senare ändringar önskas.
