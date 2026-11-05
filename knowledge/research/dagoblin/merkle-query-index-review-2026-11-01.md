# DAGoblin: historiska bevis utan helhistorikläsning per fråga

## Ursprunglig avsikt och fynd

En nod ska kunna återhämta och kontrollera riktiga block i sin egen takt utan
att dess förfrågningar blir ett globalt produktionshinder. SDK:ns tidigare
bevisfrågor läste hela blockordningen och byggde dess Merkle-träd även för
ett enda kontobevis. Den kostnaden växte med all tidigare historik.

Den nya produktionsvägen läser kontosnapshoten för begärd committad rot,
slår upp en blockhash direkt till dess ordningsplats och läser endast de
delträd som behövs för beviset. Själva blockrådatan läses inte av bevisfrågan.
Full signatur- och transaktionsverifiering vid startup kvarstår.

## Beständigt index och identiska bevis

Indexversion 2 tillför en direkt referens från blockhash till ordningsindex
och hashvärden för kompletta, justerade Merkle-delträd. Varje sådan nod
lagras en gång. Ett ofullständigt högerdelträd räknas fram för just det
historiska antalet löv, med samma dubblering av udda sista noder som tidigare.
Framtida kompletta delträd får inte användas för en äldre historikrot.

Kontobevis kräver en kontosnapshot med de sex DAG-kontona. Ett blockbevis
behöver blockreferens, ordningslöv och ett antal delträdsrötter som växer
logaritmiskt med historiklängden. En ordningssida innehåller fortfarande högst
32 löv och återanvänder gemensamma delträd under samma fråga.

Rötter, AppHash-bindning, offentliga bevisformat och verifierarens
säkerhetskontroller ändras inte. Servern verifierar också sina genererade
bevis mot den begärda roten innan de lämnas ut. Tester jämför byte för byte
mot den tidigare kompletta trädbaserade metoden, även vid äldre udda gränser.

## Atomisk commit och migrering

Ordningslöv, blockreferenser, färdiga delträd, kontosnapshot, vald historik och
indexhuvud skriver i samma synkrona atomiska commit. Förberedda eller senare
bortkastade kandidater får inga offentliga indexposter.

Indexversion 1 accepteras för uppgradering först efter att dess befintliga
poster har jämförts exakt med full verifierad återspelning av ursprungliga
signerade block och transaktioner. De nya härledda posterna och
versionsmarkören tillförs sedan atomiskt. Ursprunglig blockrådata,
kontotillstånd, identitet, historik och rötter behålls.

Vid förlorat slutförandebesked låses den öppnade lagringen som felaktig tills
den återöppnats och verifierats. Diskutfallet ska vara antingen en komplett
äldre indexversion eller en komplett ny. En saknad, omkodad eller ändrad post
i ett befintligt versionsmärkt index ska ge fel, även om den kunde beräknas
igen. Ingen tyst reparation från ett självkonsekvent men felaktigt index görs.

## Isolering och begränsningar

Databasvyn fångas under det korta lagringslåset. Diskläsning, hashing och
bevisproduktion sker därefter utanför både SDK-appens och lagringens lås.
Högst fyra offentliga läsare tillåts samtidigt, utan en obegränsad kö.
En fråga har dessutom en hård gräns på 256 små indexläsningar. Avbrott
kontrolleras under arbetet och före återlämning. Close väntar in redan
pinnade läsare och släpper deras databasvyer.

Prov genom den riktiga SDK-klientfabriken pausar en historikläsning medan en
ny commit slutförs. Den pausade frågan ska därefter ge ett korrekt bevis för
sin ursprungliga rot. Inga lås hålls över väntan på den långsamma läsningen.

Den äldre interna helhistorikläsaren finns kvar som manuell kontroll och
testorakel. Den används inte av de tre offentliga DAG-bevisändpunkterna.
Startkontroll, full ordningsvalidering vid commit och motorns metadata-
kopiering är fortfarande linjära i den ändliga historiken. Även Python-
replikans fullständiga ordningshämtning behöver fortsatt arbete.

## Verifieringens omfattning

Nya fall jämför alla historiska prefix från 0 till 129 signerade block och
alla deras ordningssidor med den gamla metoden. Övriga fall provar index-v1-
migrering före och efter faktisk Sync, förlorat slutförandebesked, saknad
ursprunglig rådata, felaktiga delträdsrötter och referenser, avbrott,
läsarkvoter, Close och verklig SDK-klientisolering.

Det befintliga provet med 4 095 faktiskt signerade block mäter också antal
indexläsningar för konto-, block- och ordningssidefrågor. Det ska kräva högst
1, 32 respektive 128 läsningar och passa i befintlig svarsstorlek. Slutliga
testantal och faktiska läsmätningar registreras i etappens privata kvitto.
De bevisar denna lagrings- och frågeväg, inte nätverkets blockkapacitet.

## Kvarstående arbete

Gränserna 4 095 DAG-block och 512 MiB historisk rådata kvarstår. Innan de kan
tas bort behövs beständiga metadata-/ordningsstrukturer, skalbar klient-
återhämtning och en verifierad policy för lagringsutrymme. Maximala
nätåterhämtningsfall, långa partitioner, fysisk fel-/uthållighetsacceptans,
kapacitetsmål, medlemskap, monetära regler, mining/pooler och oberoende
säkerhetsacceptans är fortfarande öppna delar av leveranskontraktet.

Ingen Git-push, appomstart, enhetsuppdatering eller publik nätaktivering görs
genom denna lokala etapp. Byggen för andra operativsystem ersätter inga
fysiska tester på Linux eller Android.
