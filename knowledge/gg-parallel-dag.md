# GG:s parallella förslags-DAG

Utvecklingsspåret heter **DAGoblin**. [Forskningsunderlaget](research/dagoblin/README.md)
skiljer denna prototyp från kandidatens framtida publika nättransport, adaptiva
reglering och checkpointkonsensus. Namnet innebär ingen ny slutlighetsgaranti.

[Löpande körning och verklig blockvisualisering](gg-network-live.md) beskriver
desktopstarten: åtta oberoende producenter med olika takt och jitter kring
målkapaciteten 64 tomma signerade förslag/s, paus/stopp och ett synligt
kvotstopp. Varje förslag väljer en till sju kända föräldrar. Manuella
protokollprov nedan finns kvar. [LAN-provet](dagoblin-lan.md) har i stället
tre parade peers med två egna producenter vardera. Det ursprungliga
LAN-läget överför bara tomma förslag; ett nytt uttryckligt testläge lägger
signerade, icke-finansiella testtransaktioner i själva DAG-blocken. Det kräver
nytt gemensamt testgenesisformat, separat deltagarval och ny parning på alla
tre enheter; det aktiverar inte finansiell exekvering eller slutlighet.
Den levande grafhistoriken behåller högst 128 verkliga förslag och deras
faktiska föräldrareferenser. Stoppa har en separat avbrottsväg som fungerar
även när den vanliga UI-arbetskön är upptagen.

## Ursprunglig avsikt

Användaren vill ha verkliga parallella block, flera föräldrareferenser och
korsande länkar. Fem–sju alternativ ska kunna knyta ihop parallellt arbete.
En avsändare ska förbereda sina egna transaktioner så att även telefoner kan
delta utan att hela arbetsbördan koncentreras till en central maskin.
20–300 samtidiga block och tusentals transaktioner per block är mål att pröva,
inte uppmätta egenskaper hos den nuvarande testmiljön.

## Fynd och valt första steg

Kaspa använder både en DAG och särskilda regler för att ordna parallella
block och konflikter. Godtyckligt många länkar ger inte samma konsensus.
Narwhal-arbetet skiljer spridning och kausal datahistorik från det protokoll
som bestämmer gemensam ordning och slutlighet. Den separationen används här
som arkitekturprincip; GG implementerar varken GHOSTDAG eller Narwhal/Tusk.

`backend/gg_parallel_dag.py` är därför en **separat experimentmotor**.
Hardhat och CometBFT behåller sina faktiska kedjeregler. Den nya motorn skapar
och kontrollerar riktiga signerade förslag med flera föräldrar. Dess
exekveringsresultat är en lokal förhandsberäkning. All publik status anger
`EXPLICIT_CHECKPOINT_REQUIRED` och `canonical_finalized: 0`.

## Manuella lokala protokollprov

- Fyra avgränsade producenttrådar börjar varje uttryckligt begärd omgång vid
  samma barriär. De skapar 24 förslag som standard, inte en sekventiell kedja.
  Flera förslag från samma producent kan ha samma rang.
- Fyra tillfälliga producentidentiteter och 512 separata testkonton skapas i
  RAM. PyCryptodomes Ed25519 används genom projektets befintliga adapter.
  Inga riktiga wallets, tillgångar, nätverksanslutningar eller filer används.
- Varje standardförslag innehåller åtta faktiskt signerade testtransaktioner.
  Producenten kontrollerar belopp och nonce mot en oföränderlig lokal
  förhandsrot och bifogar ett Merklemedlemskapsbevis för avsändarkontot.
- En separat admissionväg upprepar kontrollen av kedje-/sessionsdomän, kända
  föräldrar, rang, payloadrot, kontobevis och alla signaturer.
- Första omgångens förslag har den verkliga genesisankaren som förälder.
  Följande omgångar kan referera upp till sju redan antagna frontiertoppar.
  Länkar skapas aldrig till framtida, okända eller syntetiska block.
- En verifierarkopia kan ta emot samma publika signerade förslag utan
  producent- eller kontonycklar. Det är en provbar lokal verifieringsgräns;
  den tillför i sig varken fjärranslutning, peerautentisering eller decentralisering.
  Den separata privata LAN-transporten kan importera publik genesis och
  verifiera samma tomma förslag från tre signerande peers.
- Förhandsberäkningen sorterar hela den avgränsade DAG:en efter `(rang, hash)`
  och exekverar exakta heltalsbelopp från genesis. Samma avsändarnonce får
  användas en gång. Dubbletter exekveras en gång; syskonkonflikter avvisas.
  En sent observerad gren kan ändra den **oslutliga** förhandsberäkningen.

Merklebeviset visar medlemskap i en känd lokal tillståndsrot. Det är inte ett
SNARK/STARK-bevis för godtycklig transaktionsexekvering. Andra deltagare måste
fortfarande kontrollera signaturer, data och konflikter.

## Hårda gränser och överbelastning

| Gräns | Nuvarande värde |
|---|---:|
| Producenter | manuellt 4; löpande standard 8, högst 16; LAN 6 fördelade på tre peers |
| Förslag per uttrycklig omgång | högst 32 |
| Transaktioner per förslag | högst 128 |
| Transaktioner totalt per omgång | högst 512 |
| Verkliga föräldrar per förslag | högst 7 |
| Kanoniskt wire-förslag | högst 256 KiB |
| Debiterade bytes per session | högst 8 MiB |
| Bytes per fast producentidentitet | högst 2 MiB |
| Antagna poster inklusive genesis | högst 4 096 |
| Admissionsförsök | högst 4 096 |
| Historiska lokala förhandsrötter | högst 8 |
| Hämtade grafposter / föräldralänkar | högst 128 / 896; visningen kan vara en markerad delvy |

Storlek, identitet, schema, föräldrar och payloadrot kontrolleras före dyr
signaturverifiering. Även felaktig trafik debiterar sessionens begränsade
arbets- och bytebudget. Dubbletter återanvänder tidigare verifiering.
Manuella omgångar har ingen dold kö. Den uttryckligen startade livekörningen
har avbrytbara väntetider, oberoende producenter och samma hårda sessionsbudget.

Detta begränsar lokal resursförbrukning. Det bevisar inte tillgänglighet under
en verklig internetattack. Telefonens eget arbete eliminerar inte mottagarens
bandbredd, minne, signaturkontroller eller konflikthantering. Före en öppen
peertransport behövs bland annat autentiserade admissionidentiteter,
Sybil-/kvotregler, datatillgänglighet och verifierad gemensam ordning.
En angripare som bara uppger någon annans peerindex får inte betraktas som
autentiserad. Privat LAN använder i stället parade signerande identiteter;
detta är inte ett öppet permissionless antagningssystem.

## API och mätdefinitioner

`start()`, `build_wave(blocks=24, transactions_per_block=8)`, `snapshot()` och
`stop()` är ändliga synkrona anrop. `snapshot()` gör ingen I/O.
`start_live(blocks=8, transactions_per_block=0, interval_ms=125)` startar
begränsad löpande körning; `stop_live()` pausar och behåller historiken.
`start_async_live(..., producer_count=8)` startar de oberoende producenterna.
Desktopåtgärden `dag_start` och CLI `dag.live_start` väljer detta läge.
Instansens `start()` och terminalkommandot `dag.start` startar fortfarande
bara en uttrycklig manuell session.
Instanser av `ParallelDag` har även `admit(raw_bytes, producer_index)`,
`reconcile()` och `fork_verifier()` för isolerade protokolltester.

Grafen använder `MULTIPARENT_DAG` med verkliga `parent_hashes`, rang,
producentsekvens och `signature_verified`. `certificate_verified` är alltid
falskt. Ingen grafisk markör får framställa dessa signaturer som ett
konsensuscertifikat.

`last_wave` mäter producentarbete och oberoende verifiering separat.
`proposal_bps` / `tx_validation_rate` avser det lokala admissionsfönstret,
inklusive eventuella pauser mellan omgångar. De är inte nätverkets
genomströmning eller slutligt bekräftade transaktioner per sekund. TTF lämnas
okänd. Bildfrekvens är en helt separat renderingsmätning.

## Verifiering och kvarstående arbete

`tests/test_gg_parallel_dag.py` kör verkliga 24-förslagsomgångar, 192 signerade
transaktioner per omgång och en andra omgång med sju föräldrar per förslag.
En nyckellös lokal verifierare får samma resultat även i annan leveransordning.
Tester omfattar dubbelspendering i syskon, sena grenar, dubbletter, ändrade
signaturer/bevis, kedjereplay, okända föräldrar, rang, nonce, bool-/beloppsfel,
resurskvoter, stopp under arbete och frånvaro av kvarvarande arbetartrådar.

Ett första prov med två omgångar gav 384 lokalt förhandsaccepterade
testtransaktioner, noll konflikter och 168 synliga verkliga föräldralänkar.
Producentintervallen överlappade på fyra trådar. Tiderna är ett lokalt prov,
inte en jämförelse med ett publikt Kaspa-/Solana-/Lightning-nätverk.

Kvar är ett specificerat och verifierat protokoll för gemensamma checkpoints,
oberoende noder över verkliga länkar, tillgänglig data, återhämtning/pruning,
Sybilskydd och uppmätt beteende på telefon. Tusentals transaktioner per block
och 200–300 samtidiga block är ännu inte implementerade eller verifierade.
Att släppa Python-/kryptonyckelreferenser vid stopp är inte ett löfte om
fysisk överskrivning av alla tidigare RAM-kopior.

Primärkällor:
[Kaspa GHOSTDAG-protokollkod](https://github.com/kaspanet/rusty-kaspa/blob/master/consensus/src/processes/ghostdag/protocol.rs),
[Narwhal och Tusk, originalartikel](https://arxiv.org/abs/2105.11827),
[författarnas implementation](https://github.com/facebookresearch/narwhal).
