# DAGoblin: statisk verktygs- och kostnadsgranskning

Granskad 2026-10-29. Uppdraget är att undersöka fungerande offentlig DAG-kod och
de faktiska kostnaderna innan GG föreslår en egen arkitektur. Den här delen
ändrar ingen appkod, startar ingen nätverksnod och använder inga användarnycklar.

## Källversion och faktisk omfattning

Kaspa-underlaget är den officiella källutgåvan
[rusty-kaspa v2.1.0](https://github.com/kaspanet/rusty-kaspa/releases/tag/v2.1.0),
publicerad 2026-09-22, med commit
`01b532e8b553523216471682649693af92f0fd16`. Samma lokala arkiv används av den
övriga Kaspa-granskningen; inget extra klonat repo eller releaseprogram hämtades.
Proveniens finns i `.runtime/dagoblin-research/kaspa/source-provenance.json`.

Den här genomgången indexerar **15 namngivna Rust-filer, 302 372 byte och
6 862 rader**, och granskar de kritiska funktionskropparna nedan manuellt.
Det betyder inte att varje rad eller hela repot är granskad. Funktions- och
referensinventeringen är lexikal, inte en typupplöst Rust-AST eller en fullständig
anropsgraf. Generiska metoder, makron och villkorlig kompilering kan inte säkert
bindas av detta index. Workspace-manifestet innehåller 68 medlemmar.

Källkodens närvaro i en release bevisar inte ensam att varje framtida regel är
aktiverad på mainnet. Aktivering, nätverksparametrar och den separata DK-grenen
måste läsas tillsammans med den andra Kaspa-granskningen.

## Vad koden faktiskt gör och var kostnaden finns

**1. Kaspa har redan en flerstegspipeline med parallella delar.**
`HeaderProcessor::validate_header` börjar med isolerade kontroller, inklusive
PoW mot deklarerad svårighet, kontrollerar föräldrar, bygger GHOSTDAG-kontext
och gör därefter ytterligare kontextkontroller. Oberoende uppgifter kan köras
i en trådpool; beroende uppgifter släpps när sina föregångare är färdiga.
Fullständiga block går vidare till body-kontroller och får status
`StatusUTXOPendingVerification` före den senare tillståndsverifieringen.
Ett godkänt block-body eller en kontrollerad signatur är alltså inte hela
tillståndsmaskinens slutliga beslut.
[Header-pipelinen](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/pipeline/header_processor/processor.rs#L255),
[body-pipelinen](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/pipeline/body_processor/processor.rs#L178).

**2. Antalet föräldrar har en verklig kvadratisk delkostnad.**
`check_parents_incest` provar ordnade par av olika föräldrar med
`is_dag_ancestor_of`. Det ger upp till `P × (P−1)` anrop: 240 vid 16 föräldrar,
42 vid sju, före eventuella tidiga avbrott. Det är en räknad kodkostnad, inte
ett uppmätt hastighetsförhållande. Kaspa-koden anger själv att gränsen 16
motverkar kvadratiskt växande föräldrareferenser. För 10-BPS-konfigurationen
ger tabellen `k=124` och mergesetgräns 248; simnet har en separat höjning till
64 föräldrar. Att ändra dessa gränser påverkar även inkludering, liveness och
säkerhetsantaganden. Sju föräldrar i GG:s labb är ingen visad ersättning för
Kaspas säkerhetsanalys.
[Parkontrollen](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/pipeline/header_processor/pre_ghostdag_validation.rs#L85),
[BPS-parametrarna](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/core/src/config/bps.rs#L35).

**3. Det billiga intervaltestet är inte hela reachability-algoritmen.**
En kedjeförfader kan avgöras genom två intervalljämförelser. En allmän
DAG-fråga provar först detta och söker därefter binärt i ett future-covering-set.
Källan anger `O(log |future_covering_set|)` för frågan. Store-/cacheuppslag och
underhållet av indexet tillkommer. Reindexering räknar delträd och propagerar
intervall med BFS och tillfälliga kartor; indexet gör inte all insättning och
allt underhåll konstant. Detta är en viktig skillnad mot att hävda att hela
blockvalideringen består av två jämförelser.
[Förfadersfrågan](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/processes/reachability/inquirer.rs#L174),
[reindexeringen](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/processes/reachability/reindex.rs#L108).

**4. GHOSTDAG har deterministisk ordning och anticone-arbete.**
Vald förälder är maximum enligt blue-work och hashordning. Mergeset-kandidater
färgas med k-gränser, ancestry-frågor och uppslag längs vald-förälderkedjan.
Sorteringen använder redan cachade nycklar. En ny GG-lösning behöver jämföras
mot detta befintliga arbete; ”parallellism” eller ”cache” är inte i sig en ny
upptäckt. Lämpliga mätpunkter är ancestry-anrop, store-träffar/missar,
mergesetstorlek, kandidater och reindexeringstid per giltigt respektive
avvisat block.
[GHOSTDAG](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/processes/ghostdag/protocol.rs#L99),
[ordningen](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/processes/ghostdag/ordering.rs#L39).

**5. Tillståndet har fortfarande samordnade steg.**
Virtual-processorn samlar väntande meddelanden, kör `resolve_virtual` och
uppdaterar en samordnad virtual-state-vy. Inuti finns parallella transaktions-
och MuHash-kontroller, men mergeset-ordning, konfliktbehandling och sammansättning
av UTXO-diffar behövs fortfarande. DB-batcher och lås skyddar publicerat
tillstånd. Fler maskiner eller trådar kan hjälpa oberoende arbete; de tar inte
automatiskt bort dessa beroenden. Ingen CPU-profil eller genomströmningsmätning
av en Kaspa-nod genomfördes här.
[Virtual-worker](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/pipeline/virtual_processor/processor.rs#L252),
[UTXO-arbetet](https://github.com/kaspanet/rusty-kaspa/blob/01b532e8b553523216471682649693af92f0fd16/consensus/src/pipeline/virtual_processor/utxo_validation.rs#L106).

## Verktyg som faktiskt kontrollerades

| Verktyg | Observerat | Användning i denna granskning |
|---|---|---|
| GG RESEARCH inventory | Ghidra 12.1.4 och REA 6.0.0 rapporterar READY | Installerad kapacitet, inte ett bevis att en ny analys lyckas |
| Rust / Cargo | 1.99.1, installerade | Rust kompilerade en egen minimal ABI-fixtur utan Cargo-beroenden eller nätverk |
| LLVM via rustc | LLVM-IR och x86-64-assembler emitterade | Två unsigned jämförelser, AND och retur i den egna predikatfixturen |
| MSVC dumpbin | 14.44.35229.0 | PE-export och sex maskininstruktioner lästes statiskt |
| Ghidra | 12.1.4, faktiskt headless-anrop | Den egna fixturens export dekompilerades i AppContainer |
| rg / Git | Installerade | Källreferenser respektive verktygsinventering; Git användes inte för en extra klon |
| LLVM objdump/nm, GNU objdump/nm, fristående clang | Inte på den undersökta PATH:en | Ingen användning eller installation påstås |

Cargo.lock gav bland annat Rayon 1.10.0, RocksDB 0.24.0,
librocksdb-sys 0.17.3+10.4.2 och secp256k1 0.29.1. Manifestets versionsintervall
är inte samma sak som dessa låsta paketversioner. Inga upstream-buildscripts
eller upstream-binärer kördes.

## Faktiskt Ghidra-prov och dess gränser

Den installerade generella GG-pipelinen har bredare standardbudgetar än denna
uppgift: 300 sekunder, 1 GiB per sandboxprocess, 1,5 GiB sandboxjobb och en
workerbudget på 2 GiB. Javaheapens 512 MiB är inte JVM:ens totala minne.
Därför kördes inte ett generellt jobb med dessa standardgränser.

En separat, tillfällig Python-worker lade i stället samma befintliga AppContainer
innanför ett verifierat Windows-jobb: slutligen **480 MiB sammanlagt och per
process, 60 sekunder CPU och högst fyra processer**. Ghidra fick 192 MiB heap,
96 MiB metaspace, 24 MiB kodcache och 55 sekunders anropsgräns. Den ordinarie
AppContainern behöll noll capabilities; ingen breakaway eller vanlig full-trust
fallback användes. Den analyserade DLL-filen kördes aldrig.

Fixturen är 405 byte egen Rust-källkod, byggd till en 2 KiB PE-DLL utan
startpunkt eller externa Cargo-beroenden. Predikatet motsvarar jämförelserna i
den pinnade `Interval::contains`; det är **ingen Kaspa-releasebinär** och ingen
kompilering av hela reachability-modulen. Ghidra fick explicit skapa endast
den kända exportfunktionen och kördes utan generell autoanalys.

Den lyckade körningen tog **18,527 sekunder** och hade **437,8 MiB** rapporterad
maximal job commit. Ghidra återgav:

```c
return param_4 <= param_2 && param_1 <= param_3;
```

Det stämmer med både emitterad LLVM-IR och dumpbins maskinkod. Det visar att
den avgränsade statiska dekompileringsvägen fungerar och återfinner detta
predikat; det mäter inte Kaspas transaktionshastighet eller bevisar hela
kompilatorns korrekthet.

Misslyckanden är bevarade i rapporterna: `.runtime` i projektsökvägen avvisades
av Ghidras namngivningsregler; en generell PE-autoanalys tog slut på native
JVM-minne; en import utan autoanalys hade ännu ingen skapad funktion. För
autoanalysprovet var jobbgränsen konfigurerad till 512 MiB men Windows
rapporterade 517,6 MiB peak commit. Det anges uttryckligen i stället för att
beskrivas som ett uppmätt tak på 512. Den slutliga gränsen sänktes till 480 MiB.
Ingen större minnesbudget eller installation användes för att få PASS.

## Slutsatser och återstående frågor

**Praktiskt belagt:** originalkoden har redan strukturerad parallellism,
specialiserad reachability, parametergränser, cache och samordnad UTXO-verifiering.
Det lilla predikatet blev sex maskininstruktioner och dekompilerades under den
striktare budgeten. Kostnaden för indexunderhåll, konflikter, lagring och nätverk
försvinner inte för att den innersta jämförelsen är billig.

**Tekniska förslag att pröva, inte bevisade förbättringar:** GG bör separera
header/signatur/innehållskontroll från konfliktordning och publicerat tillstånd,
mäta varje fas, debitera avvisade peer-paket och mäta cache-/reindexkostnader.
Jämför genomförda, unika och slutligt accepterade transaktioner under samma
arbetslast; förslag/s är ett annat mått.

**Öppet:** full Rust-typupplöst anropsgraf, profilering på representativ DAG,
autentiserad analys av en faktisk Kaspa-releasebinär, adversariella belastningar
och mätning på oberoende maskiner. Ingen fullständig reverse engineering av
Kaspa, DAGKNIGHT, Solana eller Lightning påstås här.

Återläsbara rapporter och kommandon finns under
`.runtime/dagoblin-research/tooling/`: `probe-result.json`, `compile.txt`,
`interval_fixture.ll`, `interval_fixture.s`, `dumpbin.txt`,
`source-cost-inventory.json` samt de uttryckligt märkta felproven. Källversion,
filintegritet, avgränsningar och faktiskt exitresultat följer med. Dessa
original utgör underlag; förekomst av ett verktyg räknas aldrig som utförd analys.
