# DAGoblin: fullreplikans bevisflöde och riktig lättklient

Denna etapp kompletterar automatisk checkpoint och lokalt grafmedlemskap.
Verifieringen gäller ett privat LAN och ägda lokala SDK-processer. Publikt
testnät, mainnet och kapacitetsmålet är fortfarande inte färdiga.

## Ursprunglig avsikt

En långsammare apparat ska kunna följa sitt konto och äkta nätaktivitet i
sin egen takt. CLI äger noden, och Desktop återger samma verifierade källa.
En mobil behöver inte vara producent, global fullvalidator eller obligatorisk
konsensusväljare för att se ett korrekt saldo eller bevisade block.

## Fakta och implementation

`ProofExchange` använder befintliga signerade, autentiserade LAN-anslutningar
och samma begränsade fragmenttransport som DAG-payloads. Begäran tillåter
endast certifikat, ordningssida, konto- eller blockmedlemskap för den redan
förankrade nätidentiteten. Den accepterar ingen URL, filväg, signeringsåtgärd,
privat nyckel eller godtycklig RPC-metod. Svar har högst 256 KiB transportdata.
SDK-genesis och varje bevis måste matcha den signerade installerade sessionen.

TCP-hanteraren läser cache eller köar arbete och väntar inte på SDK/RPC eller
beständig skrivning. Bevisarbete och observation har separata ägda arbetare.
Kön har högst 32 väntande begäranden, svarscachen högst 64 poster/8 MiB och
certifikatcachen högst 64 poster. För stora, ändrade, ofullständiga eller
omordnade fragment avvisas. Resursreglagens pausläge pausar bevisarbetet.
Stopp av LAN-noden avbryter anslutningarna och avslutar även dessa arbetare.

Mottagaren kör den befintliga native SDK-verifieraren själv. En autentiserad
avsändares försäkran räcker inte. Komplett ordning kräver samtliga sidor under
en enda certifierad kontext; kontobeviset måste gälla nodens egna konto.
Certifikatet och höjdgolvet sparas synkront i nodens signerade profil innan
publicering. Äldre certifikat kan inte ersätta golvet. SDK-verifierad konflikt
på samma höjd sparar ett beständigt fel i stället för att byta tillstånd.
Ogiltig SDK-data når inte den beständiga fel-/golvskrivningen.

Profilformatets tidigare metadata och identiteter bevaras. Den nya
certifikatposten är valfri och omfattas av samma signerade integritetshuvud.
Äldre profiler behöver ingen ny identitet eller tyst rekonstruktion. En hel
äldre giltig diskavbild kräver fortfarande extern förankring för att upptäckas.

## Roller och visning

Fullreplikan hämtar och verifierar globala DAG-payloads. Den kan nu också
verifiera certifikat och hela blockordningen utan egna validatornycklar och
markera exakt vilka lokalt tillgängliga block som har kanoniska medlemsbevis.

`node_role=light` är en uttrycklig ny roll med signerad invite v6. Den kräver
DAG-val och signerad konsensusgenesis, startar ingen payloadgossip, ansluter
inga producentnycklar till motorn och äger ingen konsensusvalidator. En
koordinator får inte registrera en lättklient som obligatorisk validator.
Även den beständiga profilen avvisar global DAG-/tokenhistorik i denna roll.
Invitens två befintliga kontoplatser och krypterade kontonycklar finns kvar;
reserverade platser innebär inte aktiv produktion eller rösträtt.

Lättklienten hämtar certifikat, den senaste ordningssidan om högst 32 löv och
medlemsbevis för sina två egna testkonton. Den hämtar ingen obligatorisk global
payloadhistorik och påstår inte lokal exekvering av alla transaktioner.
Desktop visar dessa som verifierade blockbevis med kanonisk position, skapare
och TX-antal. Föräldralänkar och payloads som inte hämtats fabriceras inte.
Den globala certifierade DAG-roten visas separat från noll lokalt validerade
globala TX. Konto- och verifieringskälla följer samma CLI-observation till UI.

CLI-sammanfattningen rapporterar nu faktisk kanonisk räknare, lättklientroll,
bevisstatus och bevisade egna testkonton. Tidigare var dess kanoniska räknare
hårdkodad till noll även när backend hade verifierat medlemskap. UI skiljer
SDK-verifierat konto från lokal förhandsvy och behåller skrivskydd för en
observerad CLI-nod. Den befintliga parnings-/bootstrapöverföringen ändras inte.
Färdig verifiering har en egen telemetrirevision: Desktop uppdateras även om
det sista beviset färdigbehandlas efter sista nätverksläsningen och ingen ny
trafik därefter anländer.
Den breda grafkörningen hittade också ett faktiskt glapp vid snabb inmatning:
nya punkters slumpade ingångsrörelse kunde dra intilliggande punkter åt
motsatta håll. Vid hög takt begränsas nu varje horisontell rörelse till
0,75 punktavstånd. Grafens befintliga avståndskontroll behålls oförändrad.

## Verifiering

Riktade tester omfattar riktig autentiserad fragmenttransport, strikt
begäransschema, begränsad kö under blockerad SDK-fråga, oförändrat
beständigt golv efter ogiltigt bevis, misslyckad sparning före publicering,
återstart, rollförbud, falsk validatorregistrering och faktisk Qt/QML.

Två separata processprov använder fyra riktiga SDK-processer och tre ägda
LAN-profiler på en fysisk Windows-värd. Ett prov har fullreplika, det andra
lättklient. Båda certifierar 35 block med 5 034 TX, varav ett block innehåller
5 000 TX som faktiskt krediterar observatörens första testkonto med 5 000
atomer. Kontobeviset visar saldo 1 000 005 000 och nonce noll. Observatören
har inga egna validatorprofiler eller obligatoriska röster.

Fullreplikan verifierar alla 5 034 globala TX och alla 35 kanoniska medlemskap.
Lättklienten har endast genesis i sin lokala motor, noll globala TX
validerade, noll payloadposter i profilen och tre bevisade poster från den
sista sidan. I det lokala provet läste den cirka 354 kB applikations-TCP-data,
inklusive autentisering och bevis, medan bara det enskilda stora blockets
payload var cirka 2,46 MB. Detta är ett prov på begränsat dataflöde, inte
ett uthålligt hastighetsresultat eller utlovad trafikmängd för andra körningar.

Alla LAN-/validatorprofiler stängs och öppnas igen. Samma konto, roll,
saldo och certifikatgolv verifieras på nytt. Faktiska publika observationer
från båda processproven matas därefter till riktig QML offscreen och jämförs
med CLI-sammanfattningen. Operatörens app och fysiska enheter påverkas inte.
Linux-/Androidartefakter är fortfarande kompilerade, inte fysiskt körda här.

## Upptäckt kvarvarande arbete

Historiska native-bevisfrågor kan fortfarande läsa och återexekvera payload-
historik inne i validatorns frågeväg. Den begränsade kön och den frikopplade
TCP-hanteraren löser inte hela isoleringen från konsensusarbete. Nästa
ändring behöver en verifierbar offentlig läsmodell/index och arbete utanför
konsensuslåset; ondsinnad frågelast och maximal historik måste provas.

Grenåterhämtning vid equivocation, beständig spridning av konfliktbevis mellan
controllers, kandidatinsamling/pruning och adversariell datatillgänglighet
återstår. Monetär huvudnätsmodell, mining/pooler, publik medlemskapspolicy,
uthållig fysisk kapacitet och oberoende säkerhetsacceptans är fortsatt öppna.
Detta är fortfarande producentägda icke-finansiella DAG-testkonton och
separata native-testtillgångar. Ingen gemensam Git-push, appomstart eller ny
fysisk bootstrapcykel görs under denna interna etapp.
