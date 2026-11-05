# Gemensamt LAN-ankare och beständig validatorägare

Detta är nästa lokala, opublicerade kodlager efter
[DAG-konsensusbindningen](dag-consensus-binding-review-2026-10-31.md).
Hela leveranskontraktet är fortfarande ofärdigt. Ingen fysisk uppdatering,
Git-publicering eller omstart av den aktiva Desktop-appen ingår i proven.

## Avsikt och tidigare lucka

En fristående testkontroller kunde tidigare skapa en ny lokal fyrkommitté för
samma DAG-källa. Den var därför ingen gemensam auktoritet för LAN-nätet.
Validatorernas nycklar levde dessutom i kontrollörens RAM. Ett SDK-certifikat
från den prototypen fick inte räknas som hela LAN-grafens finalitet.

Det nya lagret binder en uttryckligt vald kommitté till den signerade
LAN-sessionen och ger varje validator en egen skyddad profil och nodprocess.
Producent-, replika- och validatorroller skiljs åt; en anslutning till LAN
skapar ingen röst.

## Implementerade regler

LAN-session v4 innehåller fyra validatorinbjudningar med separata offentliga
nycklar för validator, P2P-nod och testkonto. Varje inbjudan har ägarbevis
från dessa tre nycklar och från den rosterbundna LAN-ägarens transportnyckel.
Nyckelrollerna måste vara åtskilda. Adresserna är privata IPv4-adresser och
måste motsvara den registrerade LAN-ägaren. Ändrade nycklar, okänd ägare,
fel endpoint, dubbel medlem eller ogiltigt ägarbevis avvisas före installation.
Visningsnamn stödjer UTF-8 och är signerade data, inte hårdvaruattestering.

Alla deltagare härleder exakt samma native-genesis v3 ur den verifierade
sessionen. Sessionens nätidentitet omfattar kommittén; native-genesis omfattar
den identiteten, DAG-källan och kommittén. Därmed finns ingen cirkulär
hashdefinition och ingen lokal nyckelgenerator väljer en ny kommitté under
återstart. En redan installerad session eller bunden validatorprofil byter
inte ankare tyst. Detta är en fast privat testkommitté med fyra lika viktade
validatorer och SDK-kvorum om tre, inte publik Sybilresistens eller governance.

`ValidatorProfile` skyddar en validators tre privata nycklar med befintlig
Windows-DPAPI respektive den explicita scrypt/AES-GCM-kontexten på POSIX.
Ingen hemlig nyckelfil, CLI-parameter eller logg skapas. Profilen använder
privat katalog, verklig exklusiv ägarlåsning, strikt SQLite-schema och signerad
metadata. Skrivarens synkrona commit sker före kvittens. Fel före skrivning
eller ett förlorat svar efter genomförd commit låser fortsatt användning tills
den faktiska beständiga posten har öppnats igen.

Profilen binds till en enda verifierad LAN-genesis innan nodstart. Startavsikt
sparas före signeraren lämnas till ett barn. Native-bootstrap v2 kräver ett
uttryckligt val mellan första start och återstart. Vid återstart får saknad
genesis/databas/signeringstillstånd inte bli en ny tom signerare. Native-koden
kontrollerar den egna P2P-nyckeln och porten mot medlemslistan och härleder
de andra tre peers direkt ur samma lista. Egen peerlista tillåts inte.

`OwnedValidator` äger en profil och en verifierad native-barnprocess. RPC
stannar på ägd loopback; P2P använder medlemslistans privata adress. SDK:ns
ABCI-peerfilter tillåter registrerade adresser och autentiserade nodidentiteter.
Alla fyra processer kan vara lokala i ett prov, men det gör dem inte till fyra
oberoende operatörer eller maskiner. Start och stopp är uttryckliga, ingen
automatisk återstart införs, och en stoppad LAN-ägare stänger sina barn.
Stopp kontrollerar den faktiska processhandtagets avslutning.

Kontrollern verifierar certifikat med samma native-SDK-regler som tidigare.
Dess senaste verifierade publika certifikat sparas i profilens signerade
metadata före publicering av kontovyn. Vid ny kontroller verifieras det igen
med SDK:n. En lägre nåbar höjd får inte backa gränsen. Två olika SDK-giltiga
certifikat på samma höjd låser fortsatt drift och felet sparas. Ogiltiga
RPC-påståenden får inte skapa detta fel. Förlorat broadcast-svar ger okänt
utfall med samma lokalt beräknade transaktionsidentitet, utan automatisk retry
eller påhittad finalitet.

## Verifierad evidens

83 Go-testfall inklusive underfall passerade utan överhoppningar. De omfattar
den tidigare ledgern och DAG-exekveringen samt den nya medlemskapspolicyn,
fyra ägarbevis, bootstrapbindning, peerfilter och en faktisk signerad Python-LAN
v4-genesis. V1-/v2-regressionerna finns kvar. 20 nya Python-prov passerade för
ankare, profiler och kontrollpolicy. Där ingår verklig DPAPI-lagring, verklig
portabel lösenordskryptering, främmande profilkopia, fel lösenord, exklusiv
ägare, ändrad metadata och skrivfel. Kontrollpolicyns negativa certifikatfall
använder en mockad verifierargräns; de ersätter inte kryptografiproven.

Ett separat verkligt Windowsprov körde fyra skyddade profiler och fyra native-
processer på en fysisk värd. Under samma installerade LAN-ankare certifierades
ett verkligt block med 5 000 individuellt signerade transaktioner. Den parade
replikan hade bara genesis i sin DAG-historik; WASM verifierade ändå konto-
och blockbevis mot dess eget LAN-ankare. Det exporterade beviset var 13 123 byte
och WASM:s linjära minne var 20 447 232 byte i provet. Dessa tal är ingen
telefonmätning eller genomströmningsgaranti.

Alla native-kontrollrar och samtliga LAN-ägare stängdes därefter. Båda typerna
av profil öppnades igen från skyddad disk. Samma LAN-session, producenthistorik,
validator-/nod-/kontonycklar, SDK-signeringstillstånd, DAG-checkpoint och
certifierad nedre gräns återkom. Saknad native-signeringstillståndsfil avvisades
utan återskapande. Stopp av LAN-ägaren avslutade dess verkliga barnprocesser.

Windows-/Linux-/Android-kandidater och WASM är kompilerade med den pinnade
verktygskedjan och utan modulhämtning. Linux och Android har här bara
kompilerats, inte körts på de fysiska målen.

## Återstående arbete

Kommandon/projektion för dessa validatorprofiler har därefter lagts till i
[CLI-/Desktop-granskningen](cli-validator-review-2026-10-31.md).
Ingen ny native-kommitté startar utan uttryckligt val i appen.
Checkpointval från LAN-historik, certifierad paginering/catchup och
automatisk sann visning av respektive blocks finalitet återstår. En genuin
DAG-lättklientroll och dess begränsade dataflöde återstår också; ett lyckat
WASM-medlemskapsprov gör inte fullreplikan till en färdig lättklient.

Återställning av en hel äldre giltig profil/diskavbild kräver fortfarande
extern förankring. Epoker, validatorbyte, offentlig medlemskaps-/Sybilpolicy,
pruning och insamling av ocommittade kandidater är inte klara. Maximal historiks
återhämtningstid och fysisk P2P-latens är inte verifierade av det lilla
återstartsprovet. Den tidigare smådemons P2P-budgetar är inte ett bevis för
drift på den uppmätta ojämna Wi-Fi-länken. Dessa är kvarstående driftkrav.

Monetär huvudnätsmodell, mining och poolutbetalningar är ofärdiga. DAG-arbetet
är fortfarande producentägda icke-finansiella testtransaktioner, separat från
native-ledgerns fasta testtillgång. Målet 5 000 TX/block vid hundratals block/s
är fortfarande ouppnått. Samlad fysisk acceptans, offentlig driftsättning och
huvudnätsberedskap kan inte härledas från dessa lokala prov.
