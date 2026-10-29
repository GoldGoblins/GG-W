# Verkliga block och löpande DAGoblin

## Avsikten

GG Testnät och DAGoblin ska ha samma kompakta instrumentlayout. Grafen ska
visa verkligt backendarbete: först skapas och kontrolleras blocket/förslaget,
därefter visas dess punkt och faktiska föräldralänkar. Målet i detta steg är
minst 60 verkliga lokala block/förslag per sekund. En bildruta är ingen mätning
av blockproduktion, transaktionskapacitet eller slutlighet.

Uppföljningen den 29 oktober gäller två konkreta fel: DAGoblins Start-knapp
såg ut att avbrytas, och den synliga grafen fick stora språng trots att backend
redan producerade block snabbt. Även här ska varje punkt och mätstapel komma
från riktigt arbete. Fasta ramar och andra oförändrade objekt återanvänds.

## Vad som ändrats

- DAGoblin använder samma fasta paneler som Testnät: nyckeltal, faktisk
  tidshistorik, punktgraf, producent- och förslagslistor, kontroller och faktaruta.
  Listorna kan rullas. Hela instrumentytan behöver inte rullas.
- **Starta** i DAGoblin startar åtta oberoende lokala producenter, med
  olika takt och jitter kring ett sammanlagt mål på **64 förslag/s**.
  Varje faktiskt förslag väljer mellan en och sju kända föräldrar. Antalet
  förslag per observation varierar; skärmen skapar ingen slumpad extratrafik.
  Signaturer och föräldrar kontrolleras
  före publicering. Paus behåller sessionen; Stoppa avslutar egna arbetare.
- Testnäts Hardhat-konfiguration använder **10 ms intervall** med automine.
  Det är ett mål på 100 lokala block/s, inte en uppmätt garanti. Hela sekunders
  Ethereum-tidsstämplar får delas av flera block; hastigheten mäts med datorns
  monotona klocka, inte genom att dividera dessa tidsstämplar.
- En separat, synlighetsstyrd observertråd läser riktiga lokala headers.
  Målet är 75 läsningar/s för marginal över 60. Windowsväntan använder
  Pythons högupplösta vila utan att ändra systemets timerinställning.
  Konton, wallets och den normala fullständiga statusen läses inte 75 gånger/s.
- Snabba observationer har en egen UI-kanal. De byter inte ut det normala
  statusobjektet eller wallet-listorna. Testnäts höjd, mättider, blockgraf och
  felstatus följer den snabba kanalen; övriga uppgifter behåller sin vanliga
  statusväg. Mätstaplar, listplatser och nyckeltalsfält återanvänds.
- RPC-staplar är uppmätta lästider. Transaktions- och funktionsteststaplar
  tillkommer när just sådant arbete faktiskt utförs. Programmet skickar inga
  påhittade transaktioner eller automatiska funktionstester för att fylla grafen.

## Start, observerns ägare och grafens rörelse

Startfelet fanns i sammanslagningen av UI-status: en äldre telemetripatch med
**STOPPED** och tomt sessions-ID kunde skriva över den lyckade startens nya
**RUNNING**-session. Då såg programmet stoppat ut även om producenten hade
startat. Den normala startresponsen etablerar nu den nya sessionen och släpper
den gamla patchen. Observationer från en annan session får inte skriva över
den. Verklig backendstart, flera automatiska signerade vågor, upprepade
statusläsningar och explicit Stoppa kontrolleras också genom den riktiga
asynkrona desktop-servicevägen i ett isolerat test.

GG har flera samtidiga OmniSurface-ytor, bland annat arbetsyta och wallet.
Tidigare kunde en dold ytas initiering eller stängning välja tom observersida
för alla. Den synliga nätverkssidan föll då tillbaka till den långsammare
fullständiga statusläsningen. Varje yta har nu ett eget observerintresse.
En dold eller förstörd wallet-yta släpper bara sitt eget intresse; den kan
inte stänga av den synliga nätverksytans snabba observationer. En enda begränsad
observertråd används fortfarande. När ingen nätverksyta visas pausas läsningen.

GG Testnät och DAGoblin behåller nu högst **128 verkligt observerade poster**
med sina verkliga föräldralänkar. Den tidigare ändringen använde fortfarande
48 poster och olika rörelse för äldre och nyare punkter. Det kunde lämna ett
långt tomt glapp mellan dem trots att grafens ytterpunkter nådde båda kanterna.
Det räckte alltså inte att kontrollera grafens sammanlagda bredd.

Den nya grafen använder fler riktiga poster och en gemensam, kort förflyttning
för hela det rullande fönstret. Ett nytt block får en begränsad entrérörelse;
en punkt skapas först efter att blockets faktiska identitet observerats.
Punkter och föräldralänkar återanvänds. Kontrollen mäter även mellanrummen
och fördelningen av synliga verkliga punkter under fortsatt blockproduktion.
Den fyller aldrig ett saknat block med en syntetisk punkt eller mellanlänk.
De senaste 24 verkliga punkterna har en begränsad entrérörelse på 420 ms.
Deras verkliga länkar följer samma ändpunkter och ger den rörliga blixten vid
grafens huvud. Äldre punkter har fasta lokala koordinater medan en gemensam
förflyttning rullar historiken. Nya observationer stjäl inte tangentbordsfokus.

**Stoppa** har en separat avbrottsväg för de två ägda lokala motorerna.
Knappen fungerar även när den vanliga arbetskön är upptagen. EVM-processens
avbrott väntar inte på RPC-låset; en avgränsad arbetare slutför sedan städningen.
DAGoblin får sin avbrottssignal direkt, även för en ägd LAN-peer under parning.
Städningen är bunden till samma motor som fick avbrottet. Upprepade klick skapar inte en växande
kö. UI visar **Stoppar…** under städningen; stoppad status följer backend.

Backendens observationstakt och skärmens bildfrekvens är separata mått.
Den snabba kanalen ska hålla graf och mätstaplar aktuella utan en växande kö;
flera verkliga observationer kan fortfarande behöva visas under samma bildruta.
Att ändra en rörelses längd bevisar inte att nya block eller RPC-anrop skapats.

## Sanningskedjan

1. Den ägda EVM-processen skapar en riktig header, eller DAGoblin skapar ett
   signerat förslag som passerar lokal admission.
2. Backend kontrollerar identitet, format och verkliga föräldrareferenser.
3. En begränsad observation skickas till UI. Endast senaste meddelandet kan
   vänta på GUI-tråden; någon växande bildrutekö byggs inte upp.
4. Grafen visar hash, höjd/rang, producent och länkar från denna observation.
   Animationen får bara flytta/färga dessa befintliga objekt.

De två snabba motorernas grafer behåller högst 128 hämtade poster.
Den generiska, långsammare Comet-historiken behåller sin gräns på 48.
Läsbudgeten är fortfarande högst åtta headers per observation; längre historik
innebär inte att alla headers hämtas om vid varje uppdatering.
DAG-visningen använder verklig lokal mottagningsordning för rullningen,
producentbanor och glesa rangetiketter; synligt/hämtat och **DELVY** visas.
Flera verkliga block kan observeras i samma bildruta, särskilt när produktionen
överstiger skärmens uppdateringsfrekvens. Varje visad punkt är fortfarande ett
individuellt observerat block/förslag. Saknade block ersätts aldrig med
syntetiska punkter eller hoppande föräldralänkar.

Äldre statusmeddelanden och fel från en annan session får inte skriva över
en nyare observation. Ett observerfel markerar tidigare data som gamla och
blockerar Testnäts överföringskontroller. Ett gammalt cache-svar får inte
återställa frisk status; en nyare verifierad observation krävs.

## Resursgränser

DAGoblin behåller högst 4 096 poster inklusive genesis, 8 MiB debiterad
wire-data, åtta tillståndsrötter och 32 uppmätta jobb. En livekörning kan vara
aktiv per motor. Producenterna har egna avbrytbara väntetider; missade
körperioder köas inte för senare ikappkörning.
Vid kvotstopp sparas den befintliga sessionen och stopporsaken visas.
Ingen automatisk tömning eller omstart döljer gränsen. Med standardtakten
räcker postkvoten ungefär en minut; en ny session kräver Stoppa/Starta.

Observern pausas när nätverkssidan döljs eller fönstret minimeras. Den startar
ingen nod. En upptagen RPC-lane hoppas över. Lokala producenter fortsätter
inom sin uttryckligen startade, begränsade session tills paus/stopp/kvot.
Grafens geometriinspektion är avstängd i drift och påslagen i geometritester;
en full nodskanning vid varje animerad koordinatändring hör inte till drift.
Punktläget skapar inga dolda textkontroller per block. Detaljrutan byggs först
när den öppnas. En kvarvarande punkts vertikala läge beräknas från dess egen
höjd, vilket undviker övergående rörelse till grannblockets position när
fönstret flyttas. Befintliga noder och föräldra–barn-länkar behåller sina objekt.

Hardhats tidigare verifierade processgränser behålls: en ägd process,
512 MiB och 300 sekunders förbrukad CPU-tid på Windows. Detta är nodgränser,
inte en garanti för hela programmets RAM. Alla testidentiteter är disponibla;
ingen riktig wallet, seed eller produktionsnod används.

## Mätningar och begränsningar

Följande prestandatal kommer från den föregående leveransens separata,
ägda tester den 29 oktober 2026. De är inte nya prestandamätningar av
uppföljningen med Start-, observerägar- och svansrättelserna.

En ägd DAG-körning skapade och signaturkontrollerade **768 tomma
förslag på 12,0014 s**, cirka **63,99 förslag/s**. Alla åtta uppmätta
femsekundersfönster efter uppstart visade 64,0. RAM ökade cirka 3,77 MiB
under körningen och cirka 19,05 MiB när 4 096-postergränsen fylldes.
Efter Stoppa återstod inga egna producenttrådar.

Separata riktiga Hardhat-prov har överstigit 60 block/s och 60 faktiska
RPC-observationer/s. Ett avgränsat prov med 64 unika DEV-överföringar gav över
400 bekräftade API-anrop/s, med kontroll av kvitto och inkludering i det
kanoniska lokala blocket. Det är ett kort lokalt prov, inte en uthållig
nätverkskapacitet eller distribuerad slutlighet. Det fullständiga funktionstestet
mäts separat; ingen uppgift om 60 fullständiga funktionstester/s lämnas.

En separat synlig Direct3D11-körning av hela Testnät-instrumentytan, 970×620,
uppmätte cirka **64,0 bildrutor/s** på det ordinarie AMD-kortet. Under samma
8,06 sekunder kom **604 verkliga RPC-headers**, cirka **74,92 avläsningar/s**.
604 unika uppmätta lästider nådde GUI:t. Blockhöjdens verkliga förändring
motsvarade **74,74 block/s**. Meddelanden sammanfördes till cirka
44 UI-paket/s; ett paket kan innehålla flera individuella verkliga block och
mätvärden. Varken paketantal eller bildrutor räknas som blockproduktion.
Vyn innehöll konton, fem riktiga testtransaktioner och fyra funktionstestkontroller.
Ramar och fasta UI-objekt behölls. Detta är ett mätresultat i en ägd testvy,
inte en garanti för hela GG-programmets bildfrekvens eller alla maskiner.

DAGoblin är fortfarande en lokal förslags-DAG med **noll kanoniskt
finaliserade block**, fyra trådar och en dator. Den har ingen P2P-transport
eller implementerad checkpointkonsensus. Tomma förslag/s är inte TX/s.
Faktisk grafisk bildfrekvens måste dessutom mätas separat från backendtakten.

Regressionerna kontrollerar verkliga headers och föräldralänkar genom hela
backend/observer/grafkedjan, konstant topologi under enbart animation,
cacheordning vid fel och återhämtning, sessionsbyte, paus/minimering,
kvotstopp, signaturer, konfliktregler, begränsad kö och avslutade arbetare.
Uppföljningens tester omfattar dessutom gammal STOPPED-patch följd av riktig
Start, flera samtidiga ytors observerintresse samt den verkliga grafsvansens
utbredning i både kedje- och DAG-läge. Mätresultat ska knytas till den kod
som faktiskt körts; en tidigare bildfrekvens ersätter inte ett nytt prov.

[Protokollets lokala gränser](gg-parallel-dag.md) ·
[Forskningsspåret DAGoblin](research/dagoblin/README.md) ·
[Gemensamma UI-färger](gg-ui-colors64.md)
