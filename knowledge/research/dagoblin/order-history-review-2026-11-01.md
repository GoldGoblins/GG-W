# DAGoblin: beständig verifierad ordning och stegvis klientåterhämtning

## Ursprunglig avsikt och fynd

En långsam eller omstartad nod ska fortsätta från sin verifierade historik och
utföra arbetet i sin egen takt. Den ska inte påverka andra producenters
framsteg eller visa certifierad lokal exekvering innan rådata har verifierats.

Tidigare började både den egna SDK-kontrollern och fullreplikans ordnings-
hämtning från sida noll när en ny DAG-rot blev certifierad. Efter omstart
hämtades samtliga gamla ordningsbevis igen. Även en nod som väntade på saknad
rådata kunde upprepa en redan verifierad ordningshämtning.

## Beslut och genomförande

Den SDK-verifierade ordningen har nu ett separat append-cache. Gamla löv
behålls som en oföränderlig följd. Vid en ny certifierad rot hämtas den sista
berörda 32-lövssidan och nya sidor. Överlappande löv måste vara identiska.
Nya löv läggs till en kopierad Merkle-frontier och den sammanlagda roten
jämförs med den nya certifierade roten. En ändring långt bak i en återanvänd
prefix upptäcks därmed även om den ändrade sidan aldrig hämtas på nytt.

Varje bascertifikat och hämtad sida verifieras fortfarande av SDK:n innan
informationen får användas. Klassen som återanvänder ordningen är ingen
quorumverifierare. Förkortad ordning, omskriven prefix, dubbla blockhashar,
fel producentsekvens, fel transaktionsantal och fel rot avvisas utan att det
gamla cachet ändras. Oförändrad ordning behöver inga nya sidförfrågningar.

Ett korrekt verifierat ordningscache är endast hämtauktoritet. Det är inte
bevis för att rådata finns lokalt eller att transaktionerna har exekverats.
Fulla roller måste fortfarande hämta, signaturkontrollera, beständigt skriva
och exekvera rådata samt jämföra konto- och ordningsrötter före lokala
medlemskap eller kontopåståenden i CLI och Desktop.

## Beständig lagring och återöppning

Nodprofilens schema 3 tillför tabellen `orders`. Endast nya ordningslöv
skrivs. De och deras ursprungliga offentliga SDK-certifikat binds av samma
synkrona SQLite-transaktion och signerade integritetshuvud. Det finns högst
4 095 löv, högst 512 byte per löv och högst 2 MiB lövdata i denna version.
Rådatans journal och dess räknare är separata och ändras inte av cachet.

Öppning kontrollerar exakt schema, sammanhängande index, kanonisk kodning,
hashar, storlekar, producentsekvenser, transaktionsantal och hela Merkle-roten.
Detta är fortfarande lokal lagringsintegritet. Innan en återöppnad cache får
användas kontrolleras dess certifikat igen av SDK-verifieraren under den
oförändrade signerade sessionsankringen. En lokalt signerad cache ersätter
aldrig ett giltigt SDK-certifikat.

Befintliga schema 1 och 2 får endast en tom ny tabell genom atomisk
migrering; den tillverkar ingen verifierad historik. Vid förlorat
slutförandebesked låses den öppnade profilen tills återöppning. Det faktiska
diskutfallet återspelas då exakt, utan att identitet eller historik nollställs.
Saknade eller ändrade versionsmärkta cacheposter repareras inte tyst.

Två SDK-kontroller på samma ägarnod kan ligga olika långt fram. En äldre
korrekt prefix får inte skriva över en nyare cache. Oförändrad ordning ger
inte en ny skrivning för varje tom SDK-höjd. Lättklienter får inte lagra den
globala ordningen; de behåller sitt tidigare begränsade bevisscope.

## Verifiering

Riktade tester använder riktiga signerade DAG-block, tillfälliga krypterade
profiler och verkliga synkrona databastransaktioner. De provar varje prefix
genom 129 block mot den tidigare fulla Merkle-beräkningen, fulla och delvisa
sidgränser, flera överhoppade checkpoints, prefixomskrivning utanför den
hämtade sidan, avbrott, storleks-/typfel, cacheåteröppning, förlorat Sync-
slutförande och ljusa rollers lagringsgräns. SDK-gränsen är uttryckligen
mockad i de rena policy-/lagringstester som använder strukturella certifikat.

Separat acceptans med fyra verkliga SDK-processer och autentiserad LAN-
transport verifierar de riktiga certifikaten och sidorna. Efter återöppning
av samtliga profiler hämtar fullreplikan inga gamla ordningssidor. Efter
ytterligare ett verkligt certifierat block hämtar den endast sidan med
startindex 32 och fortsätter från 35 till 36 block och från 5 034 till
5 035 verifierade transaktioner. Lättklientens globala cache är tom.

De befintliga proven för ett undanhållet 5 000-TX-block, skadade SDK-chunkar,
producentkarantän, fortsättande ärlig producent och återöppnade profiler
passerar också. Slutliga testantal och oförändrade källor binds i etappens
privata verifieringskvitto. Denna etapp ändrar ingen Go/WASM-källa; tidigare
bygg- och testbevis återanvänds först efter kontroll av identiska källor och
artefakter. Operatörens app påverkas inte.

## Kvarstående arbete

Detta tar bort upprepade gamla bevisnedladdningar och gör den verifierade
ordningen beständig. Det gör inte hela exekveringsvägen konstant eller
obegränsad. Klienten materialiserar fortfarande fulla lövlistor och vissa
metadata vid uppdatering, och SDK-motorn kopierar fortfarande sina fulla
historiska register. Rådata och signaturer återspelas fullt vid start.

Gränserna 4 095 DAG-block och 512 MiB rådata kvarstår. SDK:ns beständiga
exekveringsmetadata, lagringspolicy, maximal nätåterhämtning, långa
partitioner, fysisk fel-/uthållighetsacceptans, kapacitetsmålet, monetära
regler, mining/pooler, offentligt medlemskap och oberoende acceptans återstår.
Ingen Git-push, appomstart, enhetsuppdatering eller publik aktivering görs
genom denna lokala etapp.
