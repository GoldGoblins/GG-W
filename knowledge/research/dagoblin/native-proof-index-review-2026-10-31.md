# Historiska DAG-bevis utan konsensuslås

Datum: 2026-10-31. Omfattning: native SDK, härlett offentligt index och lokala
regressioner. Ingen fysisk Linux-/Termuxkörning eller publik nätverksaktivering.

## Ursprunglig avsikt

Samma verkliga nätverks- och kontoinformation ska kunna verifieras från CLI och
visas korrekt i Desktop. En långsam telefon eller en bevisfråga ska inte hålla
snabbare noders produktion eller konsensuslåset. Alla nödvändiga kodändringar
samlas innan nästa gemensamma fysiska acceptansprov och Git-push.

## Fynd

Historiska native-bevis återläste tidigare fulla manifest och signerade
transaktioner under applikationens läslås och lagrets mutex. Den separata
TCP-kön begränsade anrop men undanröjde inte denna inre låskoppling. Ett
kontobevis kunde därför orsaka historisk exekvering inne i konsensusarbetet.

## Ändring och gränser

Ett härlett LevelDB-index lagrar varje kanoniskt ordningslöv en gång och sex
kontolöv per checkpoint. Ingen full ordningslista kopieras för varje rot.
Indexets tillägg, val av checkpoint och native-historik skrivs i samma
synkrona atomiska batch. Förberedda men inte valda förslag läggs inte i indexet.
En native-höjd som behåller DAG-roten skapar inga nya indexposter.

Frågan kopierar sitt bestämda native-tillstånd under ett kort läslås och
släpper sedan applikationslåset. Lagrets mutex används endast när en
LevelDB-snapshot tas och läsarens livstid registreras. Läsningar, trädberäkning
och beviskonstruktion sker utanför dessa lås. Ett samtidighetsstopp begränsar
arbetet till fyra indexläsare; ytterligare anrop får ett fel i stället för en
obegränsad väntkö. Ogiltiga identifierare och sidmarkörer avvisas före
indexläsningen. Avbrutna frågekontexter kontrolleras under läsningen.

Varje svar kontrollerar exakt commitment, kontoadresser, saldo-/noncegränser,
bevarad testsupply, ordning, tillåtna producenter, sammanhängande sekvenser,
TX-summor och båda Merkle-rötterna. Indexet har en separat gräns på 16 MiB,
högst 4 095 ordningslöv och högst 4 096 små kontosnapshots. Det innehåller
ingen exekverbar payload och ersätter inte datatillgänglighet eller signaturer.

Samma granskning hittade att Python-controllern höll sitt arbetslås under
externa bevisfrågor och SDK-verifiering. Den vägen har nu en separat, begränsad
loopbackanslutning med tre sekunders timeout. Ägandet kontrolleras mot det
fångade processobjektet och porten. Controllerlåset hålls bara under korta
kontroller; stopp, byte av native-process eller fel under arbetet gör att
svaret avvisas. Konsensusarbetets befintliga anslutning återanvänds inte.

Vid omstart spelas samtliga ursprungliga signerade payloads fortfarande upp.
Det befintliga indexet måste därefter vara exakt lika med den härledda
historiken. Saknat eller ändrat versionsmärkt index ger stopp, ingen tyst
reparation. Ett äldre lager utan index får ett härlett index först efter
lyckad full verifierad uppspelning. Migrationen ändrar inga nycklar, konton,
native-höjder eller befintliga historikbytes.

Stängning stoppar nya läsare och väntar på redan registrerade snapshots innan
databasen stängs. Ett skrivfel låser vidare användning, även om det verkliga
synkrona skrivandet hann slutföras innan felreturen. Återstart läser det enda
faktiskt beständiga utfallet för både native-historik och bevisindex.

## Verifiering och avgränsning

125 Go-tester inklusive underfall passerade utan hoppade tester i den riktade
körningen. Dessa omfattar historiska konto-/block-/sidbevis efter omstart,
originalpayload som krävs vid återställning, blockerad bevisläsning samtidigt
med riktig Finalize/Commit, stängning med aktiva läsare, samtidighetsgräns,
avbrott, ogiltiga frågor, korrupta index, självomräknade falska kontorötter,
äldre lagermigration samt fel före och efter beständigt commit-resultat.

25 riktade Python-policy-/transporttester passerade. Nya fall blockerar
avsiktligt RPC respektive SDK-verifierare och kontrollerar att arbetslåset
förblir ledigt. De provar också processbyte, egen anslutning, storleksgräns,
anslutningsstängning och avvisning av felaktiga bevisväljare före RPC.

Ett prov producerar och validerar 4 095 individuellt signerade block och
transaktioner över 32 checkpoints. Exakt 4 095 ordningsposter och en giltig
sista sida med 31 medlemsbevis kontrolleras. Indexet ligger under 2 MiB för
just detta prov. Det är ett gräns-/korrekthetsprov, ingen uthållig kapacitets-
eller maximal payloadmätning. Den breda Python-/UI-verifieringen, nya native-
och WASM-artefakter och processproven för replika/lättklient kontrolleras
separat mot fryst källkod före intern slutmarkering av denna etapp.

## Kvarvarande krav

Kandidatinsamling och pruning, grenåterhämtning vid equivocation, beständig
spridning av certifierade konfliktbevis, adversariell datatillgänglighet och
maximal payloadåterställning återstår. Den offentliga monetära modellen,
mining/pooler, medlemskap, fysisk uthållighet, kapacitetsmålet och oberoende
säkerhetsacceptans är inte uppfyllda av denna ändring. Befintliga sex
DAG-konton är fortfarande producentägda icke-finansiella testkonton.
