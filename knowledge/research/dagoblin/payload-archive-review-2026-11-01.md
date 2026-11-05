# DAGoblin: beständig rådata och begränsat blockcache

## Ursprunglig avsikt och omfattning

Noden ska fortsätta med sin egen kapacitet, behålla verklig verifierbar historik
och visa samma skapare och kontotillstånd i CLI och Desktop. Denna ändring
minskar dubbel lagring i Python-processens RAM. Hela leveranskontraktet är
fortfarande ofärdigt; den här granskningen är ingen huvudnätsacceptans.

## Fynd

Beständiga LAN-noder behöll både rådata och hela avkodade transaktionslistor
för varje block i RAM. Journalen hade redan samma rådata på disk. Förhandsvyn,
producenternas kausala kedjor och jämförelsen mot certifierade kontorötter
använder redan fullt verifierade metadata och sex kontodeltan per block.

PAGE och GET kunde dessutom samla flera stora block före sändning. Det gav
onödig tillfällig minnesåtgång, särskilt vid återhämtning på svagare enheter.

## Beslut och implementation

- Endast beständiga, producentägda LAN-sessioner använder arkivläsaren. Den
  ansluts före full verifierad journalåterspelning och före lokala signers.
- Efter full signatur-, transaktions-, föräldra- och noncekontroll släpps
  avkodade transaktionsobjekt. Högst 128 block och 16 MiB rådata behålls i
  cache. Cachegränsen minskas även efter nodens uppmätta minnesutrymme.
- Rådata, signaturer och historik raderas aldrig ur journalen. Skapare, rank,
  föräldrar, producentsekvens, nonces, grenkarantän och kontodeltan behålls.
- Ett härlett index pekar på journalposition, exakt storlek och rådatadigest.
  Det byggs från den signerade journalen vid öppning och uppdateras först efter
  lyckad synkron transaktion. Ingen databaseschemamigrering behövs.
- En arkivläsning kontrollerar typ, storlek och digest i lagringen, följt av
  jämförelse med motorns tidigare fullt verifierade rådatadigest. Saknad,
  ändrad, stängd eller utbytt källa får inte leverera en påhittad post.
- Diskläsning sker utanför motorns lås. Högst två samtidiga arkivläsningar
  tillåts per motor. Journalens eget databaslås skyddar dess anslutning;
  läsning och synkron skrivning på den anslutningen kan därför serialiseras.
- PAGE och GET materialiserar högst en sida om 2 MiB, eller ett ensamt större
  block inom nodens befintliga blockgräns. Minneskredit reserveras före
  materialisering och hålls tills förfrågan avslutats.
- Kontorötter, förhandsvy, checkpointval och exakt rekonstruktion av en redan
  förberedd checkpoint fungerar även när rådata har lämnat cachen.
- Historiska poster räknas fortfarande som lagrad historik. RAM-underlaget
  använder cache och metadata; det är en försiktig budgetmodell, ingen direkt
  mätning av operativsystemets faktiska residenta minne.

## Verifiering

Nio nya testfall använder riktiga signerade block och tillfälliga krypterade
nodprofiler. De omfattar 35 000 olika signerade transaktioner i sju block,
cachegränser för byte och antal, exakt journalhämtning efter återöppning,
fortsättning vid nonce 35 000, autentiserad TCP-överföring av ett gammalt block,
begränsade stora sidor, checkpointrekonstruktion, samtidiga läsare, ändrad
rådata, minnesbrist före diskhämtning samt grenkarantän och fortsatt ärlig
producent efter återspelning.

Den samlade Python/UI-suiten och de riktiga SDK-processproven registreras i
det privata testkvittot för `payload-archive-v1`. Processprovet för undanhållen
rådata tvingar samtliga tre Python-motorer att använda kall journaldata:
originalägaren undanhåller blocket, skadade SDK-chunkar avvisas och en annan
ägare återställer det exakta blocket från en verklig certifierad SDK-process.
CLI och offscreen-QML jämför samma observerade fält. Operatörens app påverkas
inte. Go/WASM-källan är oförändrad från föregående verifierade byggversion;
återanvändning av dess byggartefakter kräver identisk källfingeravtryckning.

## Kvarstående gränser och antaganden

Detta är **inte obegränsad historik eller generell beskärning**. Gränserna
4 095 DAG-block och 512 MiB historisk rådata kvarstår. Python behåller
historiska blockmetadata och mängden verifierade transaktionsidentifierare.
SDK-motorn behåller fortfarande hela sin exekverade rådata och ordningslista
i RAM. Dess historikrötter och kopieringsarbete behöver en separat ändring
innan långvarig storskalig drift är möjlig.

Läsning har ändliga storleks- och samtidighetsgränser men ingen garanti mot
ett operativsystem eller en lagringsenhet som hänger i en systemanrop.
En fullständigt återställd äldre giltig diskbild kräver fortfarande ett
externt betrott ankare för att upptäckas. Journalens kontrollsummor ersätter
inte full protokollverifiering vid start.

Maximal historikåterhämtning, längre partitioner, fysisk uthållighet,
kapacitetsmålet, offentligt medlemskap, monetära regler, mining/pooler och
oberoende säkerhetsacceptans återstår. Ingen Git-push, appomstart,
enhetsuppdatering eller ny fysisk nätkörning ingår i denna lokala etapp.
