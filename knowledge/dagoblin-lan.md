# DAGoblin på tre egna LAN-enheter

Första målet är en Windows-dator, en Linux-dator och en Androidtelefon med
Termux på samma privata nät. VPS och huvudnät ingår inte i detta steg.
Samma headless-transport används av Desktop och terminalpaketen.

## Samma nod i CLI och Desktop

En redan startad GG-CLI-nod publicerar nu sin offentliga LAN-status lokalt för
samma inloggade användare. När Desktop inte äger en egen LAN-peer visar
**CRYPTO → NÄTVERK → DAGoblin** CLI-nodens faktiska graf, verifierade block och
TX, testkonton, mätningar och peerstatus. Ingen extra nod startas. Vyn märks
**Visar CLI-noden**; start, stopp och nodinställningar görs i det CLI som äger
noden. Privata nycklar, mnemonic, lösenord och walletfiler ingår aldrig i den
delade nodstatusen. DAG-testkontonas saldon är en lokal förhandsvy och är inte
ett påstående om kanonisk finalitet eller en publik wallets saldo.

CLI och Desktop måste använda samma operativsystemsanvändare och samma
`XDG_DATA_HOME` för denna lokala läsvy. Det krävs ingen extra nätverksport.
Status uppdateras av den vanliga CLI-observationen, normalt varje sekund.
Efter fem sekunder utan en ny lokal observation markeras data som gamla.
En avslutad process eller flera samtidigt aktiva CLI-källor väljs aldrig
tyst som en ny levande nod. En Desktop-peer som användaren själv har startat
behåller sin egen datakälla och styrning.

Anslutning och historik visas separat: en godkänd parning betyder inte att en
peer fortfarande svarar. Varje peer får en aktuell kontaktstatus och tiden
sedan dess senaste fullständiga autentiserade utbyte. Kontakten blir gammal
efter 15 sekunder och frånkopplad efter 45 sekunder utan nytt bekräftat utbyte.
TCP-byte, lokalt signaturverifierade DAG-TX och gemensam provkvittens är
separata mått. Testnät och huvudnät måste senare tillföra sina egna faktiska
nätverksobservationer till samma typ av vy; privat LAN aktiverar dem inte.

## Producenter och blockens avsändare

Producentnamnen hämtas från sessionens signerade roster och dess exakta
producentindex. Exempelvis visas **Windows · 1**, **Linux · 2** och
**Termux · 1**, med **egen** på den aktuella nodens två producenter. Samma
identitet används i producentlistan, senaste block, blockets tillgänglighets-
text, tooltip och detaljvy. Namnen är de som valdes vid parningen; de är inte
en fristående attestering av operativsystem eller fysisk hårdvara. Okända
mappningar visas som okända och gissas aldrig från ett löpnummer.

En producentnyckel hör till exakt en nod i den signerade sessionen. Nod- och
producentnycklar måste vara unika när sessionen skapas och installeras.
Varje block har en signerande producent. Andra noder verifierar och lagrar
kopior av samma block utan att överta dess skaparidentitet eller nodens
kontrollnyckel. Producentnamn är inte en lista över verifierande noder.

En deltagares avslutade produktion visas som **Lokal del klar**. Det betyder
inte att koordinatorn har bekräftat gemensam blockmängd och tillstånd.
Den gemensamma nätkvittensen redovisas separat och kräver fortfarande
autentiserad, run-bunden evidens från samtliga tre före provets deadline.

## Transport vid ojämn fördröjning

Den 31 oktober visade de fysiska proven fel under PREPARE och BEGIN mot
Linux. Linuxunderlaget rapporterade TCP-omsändningar och svarstider upp till
1,8 sekunder. Källkodens tidigare gräns på en sekund per fullständigt
meddelande kunde därför avbryta ett giltigt autentiseringsutbyte.

Den uppdaterade profilen tillåter högst tre sekunder per meddelande och åtta
sekunder per anslutning, alltid begränsat av provets tidigare gemensamma
arbetsdeadline. Socketar fortsätter att kontrollera avbrott med korta
pollintervall. En RPC med förlorad kvittens skickas inte om automatiskt.
De två andra peersens blockutbyten har var sin fast, ägd arbetsloop så att en
långsam peer inte blockerar den andra. En ren TCP-kontroll som stänger utan
att skicka något bokförs som en väntad stängning; en avbruten eller felaktig
protokollram är fortfarande ett fel.

Standardknappen startar ett 10-sekundersprov med **1 TX/block och 250 ms**.
Högre belastning väljs uttryckligen i LAN-panelen efter en fungerande baslinje.
De fysiska omproven nådde produktion men inte gemensam kvittens: 140 lokala
block/TX vid 250 ms och 36 vid 1000 ms. Ett stopp tog 1,68 sekunder av den
tidigare fasta tvåsekundersreserven för små block. Provet reserverar nu
högst halva den signerade totaltiden, begränsat till 30 sekunder, för stopp
och synkning även vid låg belastning. Nya matchande statusbevis kontrolleras
innan en pollpaus får förbruka den återstående tiden. Den ursprungliga
deadlinen och beviskraven för nätkvittens förlängs eller försvagas inte.
Regressionsproven omfattar verklig signerad autentisering över en injicerad
1,8-sekunderslucka och tre separata lokala processer. De ersätter inte det
nya fysiska provet efter att alla tre apparater har uppdaterats och startats
om av användaren. Den bakomliggande orsaken i Wi-Fi, router eller drivrutin
är fortfarande inte fastställd av dessa kodtester.

## Vad som överförs

Varje peer skapar två egna tillfälliga producentnycklar och en separat
transportidentitet i sitt RAM. En signerad publik inbjudan beskriver peerens
adress och publika nycklar. Koordinatorn väljer exakt tre inbjudningar och
skapar en signerad session med sex producenter och gemensam publik genesis.
Varje peer har bara sina egna två signeringsnycklar. De andra producenternas
och kontonas privata nycklar överförs inte.

Peertrafiken använder signerad ömsesidig challenge, sessionsdomän och
sekvenskontroller. Inventering och begäran av saknade föräldrar är begränsade
med fasta frame-, byte-, orphan- och sessionskvoter. Normal dataframe är
högst 64 KiB; den större publika sessionsfilen är högst 256 KiB. En sådan
begränsning är inte ett bevis mot alla nätverksattacker.

Det ursprungliga förslags-DAG-läget överför **verkliga tomma signerade förslag**.
Ett separat uttryckligt DAG-testläge beskrivs nedan. Finansiella transaktioner
mellan peers är avstängda: de lokala förhandsrötterna är ännu inte gemensamma
slutliga checkpoints. Grafen visar verkliga signerade
förslag och deras verkliga föräldrar; mottagningsordningen är lokal.
Kanonisk finalitet är noll. Ed25519 är inte kvantsäkert. Trafikens signaturer
ger inte krypterad innehållssekretess.

Ett separat valbart **GG-LAN(TEST)**-läge överför riktiga signerade
testtokenöverföringar. Alla tre peers måste först ha valt `allow_test_tokens=true`.
Koordinatorn ordnar överföringarna och signerar en hashkedja av kvitton;
alla peers kontrollerar signaturer, exakta heltalssaldon, nonce och samma
tillståndsrot. Varje peer behåller sin egen signerare. Detta är en uttryckligt
koordinatorordnad testledger med en fast testtilldelning, inte DAG-konsensus
eller pengar som kan tas ut eller användas på ett publikt nätverk.

## DAGoblin med testtransaktioner i blocken

Användarens mål är DAGoblin på tre verkliga enheter, tusentals transaktioner
per block och flera hundra block per sekund, med samma levande graf som visar
backendens faktiska arbete. Det är ett prestandamål, inte ett uppmätt resultat.
Exempelvis motsvarar 1 000 TX/block och 200 block/s 200 000 TX/s. Signering,
verifiering, transport, köer och minnesbehov måste mätas på varje plattform.

Det nya valbara testprotokollet lägger individuellt signerade, icke-finansiella
testtransaktioner i DAG-blockens payload. Varje peer behåller sina två egna
producent-/testkontosignerare i RAM. Gemensam publik genesis ger sex
producentägda testkonton och ett oföränderligt kontrollpunktsankare.
En producents nästa block refererar dess föregående block; producentsekvens,
transaktionsnonce och sammanlagd debitering kontrolleras. Mottagna testbelopp
höjer inte avsändarens tillåtna provvolym utöver den egna ursprungliga
tilldelningen. Detta är en avgränsad testmodell, inte allmän finansiell
exekvering eller kanonisk DAG-finalitet. Signerad equivokering ska ge ett
synligt fel, inte döljas som framgångsrik samsyn.

Alla tre måste uttryckligen välja `allow_dag_transactions=true` före ny
parning. Det nya invite-/sessionsformatet kräver uppdaterad kod på alla tre
apparaterna; en gammal körande process uppdateras inte av ett källpaket.
Windows skapar och delar en ny publik bootstrap. Klientexempel:

```sh
python gg-cli.py --foreground --command "lan.start label=Termux allow_dag_transactions=true auto_produce=false" --bootstrap-file gg-lan-bootstrap.json
```

Linux använder `python3` och `label=Linux`. På koordinatorn används följande
kommandon i samma ägda interaktiva CLI-session, eller motsvarande kontroller
i desktopens LAN-dialog:

```text
lan.session_create distribute=true enable_dag_transactions=true
lan.dag_stress_start duration_ms=10000 transactions_per_block=16 interval_ms=100
lan.dag_stress_stop
```

Belastningsprovet har bestämd längd, explicita deltagarval och ändliga
resursbudgetar. Det får inte adoptera eller stoppa en annan manuellt startad
producentkörning. UI läser tillåtna intervall och blockstorlekar från backend;
den första profilens begränsningar är program-/protokollgränser, inte ett
uppmätt hårdvarutak. Kvotstopp och storleksfel redovisas uttryckligen.

### Hårdvarutest och individuella resurstak

LAN-panelen har ett totalreglage och separata tak för CPU, GPU, RAM och nätverk
på den egna noden. Reglagen ändrar nodens DAG-arbete, inte operativsystemets
globala inställningar eller de andra apparaternas inställningar. Texten under
varje reglage visar teoretiskt relativt behov vid den aktuella flaskhalsen.
Kapaciteterna räknas först om till samma arbetslast i TX/s. Exempel: CPU
6 000 TX/s och nätverk 10 000 TX/s med nätverkstaket 10 % ger ett gemensamt
teoretiskt tak på 1 000 TX/s och ett relativt CPU-behov på cirka 16,7 %.
Samma regel gäller när CPU, RAM eller en aktiv GPU-backend blir flaskhals.
Totalreglaget anger andelen av detta gemensamma tak. Procent av uppmätt
DAG-kapacitet är inte samma sak som operativsystemets totala CPU-mätare.

Det uttryckligt startade hårdvarutestet använder en separat disponibel DAG
med verklig signering och verifiering. RAM mäts med ett kopieringsprov och en
separat budget för arbetsminne. När tre peers är parade mäts nätverket med
ett ändligt, autentiserat dubbelriktat LAN-prov mot de två andra. Utan detta
anges operativsystemets länkhastighet som en teoretisk uppskattning, eller
okänd kapacitet om uppgift saknas. Ett misslyckat länktest ersätts inte med
ett optimistiskt nätverkstal. Testets största faktiskt uppmätta blockstorlek
visas separat. Hårdvarutestet är en kort kalibrering; resurstaken gäller den
anslutna nodens DAG-körning.

Den nuvarande kryptografiska DAG-backenden kör på CPU. GPU-reglaget är
inaktivt tills en faktisk GPU-backend finns; bildrendering räknas inte som
DAG-beräkning och ingen GPU-prestanda hittas på.

I samma interaktiva CLI-process kan motsvarande funktioner användas så här:

```text
lan.hardware_test_start duration_ms=10000 max_transactions_per_block=50000
lan.status
lan.resources {"budget":{"overall":100,"cpu":100,"gpu":100,"ram":50,"network":10}}
lan.hardware_test_stop
```

Den större testprofilen tillåter upp till 50 000 TX/block, 1–600 sekunders
gemensam provbudget och `interval_ms=0` för automatisk takt. Varje block och
TX verifieras fortfarande. Större block fragmenteras i signerade frames på
högst 64 KiB och återmonteras med kontrollerad storlek, ordning och
transportdigest före DAG-verifiering. Blockgränsen är högst 32 MiB och
sänks av minnesbudgeten; sessioner och transport har fortsatt ändliga
skyddskvoter. Ingen av dessa gränser är ett uppmätt hårdvarutak. Ändra
blockstorlek och provlängd efter faktiskt uppmätt arbete, inte efter det
teoretiska maximivärdet.

Mätvärdena visar block/s, faktisk genomsnittlig TX/block och TX/s. Ett
teoretiskt reglagetak eller ett lokalt antaget block är inte en gemensam
nätkvittens. Ett lokalt transporttest har skickat ett verkligt block med
5 000 TX mellan tre separata processer, som verifierade samma blockmängd
och tillstånd utan nya transportfel. Detta ersätter inte ett nytt prov på
de tre fysiska enheterna.

Grafens block, föräldralänkar, lokalt verifierade DAG-TX och mättider kommer
från antagna DAG-block. Den separata kvittoledgerns räknare fyller aldrig
DAG-grafen. Ett nätverksbekräftat resultat kräver autentiserade svar med samma
blockmängd, räknare och tillstånd på alla tre, utan protokollfel. Lokal
validering och gemensamt bekräftad genomströmning redovisas var för sig.

Det fysiska kvittocirkelprovet den 30 oktober 2026 avslutades med 18 signerade
överföringar, sex hela varv och bekräftad gemensam kvittokedja. Ett separat
visuellt DAG-prov skapade 435 signerade tomma blockförslag från Windowsnodens
två egna producenter och visade faktiska länkar och mätstaplar innan paus.
Inget av dessa prov verifierar den nya transaktionsvägens fysiska kapacitet
eller det framtida prestandamålet.

## Uppstart

Packa upp plattformens källpaket och kör dess uttryckliga bootstrap enligt
[terminalens README](../support/gg-cli/README.md). Ingen nod startas av en
vanlig statusläsning. Den uppdaterade transporten måste återprovas på den
fysiska Termuxtelefonen; en tidigare lyckad anslutning är inte ett godkänt
tokencirkelprov för denna version.

Windows är koordinator. I Desktop öppnas DAGoblin och LAN-inställningen.
Starta parning och spara den publika bootstrapfilen till Linux och telefonen.
Välj före start **Tillåt privata GG-LAN-testtokens** om tokenprovet ska köras.
Filen innehåller koordinatorns publika identitet och endpoint, inga privata
nycklar. Nycklar lever bara under processen: en omstart kräver ny parning.

På Linux med full GG-W Desktop öppnas samma DAGoblin → LAN-dialog.
Ange nodnamn, välj **Tillåt privata GG-LAN-testtokens** om provet ska köras
och klicka **Anslut med publik bootstrap…**. Läs filen som Windows sparade.
Starta ingen extra koordinator på Linux. Appen annonserar sin signerade
inbjudan till Windows och visar den anslutna peerens graf i Desktop.

Telefonen kör sin egen foregroundprocess med bootstrapfilen bredvid
`gg-cli.py`. Exempel från GG-CLI-mappen i Termux:

```sh
python gg-cli.py --foreground --command "lan.start label=Termux allow_test_tokens=true auto_produce=false" --bootstrap-file gg-lan-bootstrap.json
```

Linux CLI är ett valfritt alternativ med `python3` och `label=Linux`.
`--invite-out` behövs inte för automatisk annonsering. Om en publik inbjudan
ändå exporteras måste filnamnet vara nytt: export skriver aldrig över en
befintlig fil. Detta är inte ett kommando för lösenord eller privata nycklar.

Deras lokala IPv4 väljs genom operativsystemets route till koordinatorn;
ingen manuell IP-inmatning behövs på dessa enheter. Kontrollera kandidaternas
namn i Windows innan den gemensamma trepeersessionen skapas. Enheten skickar
sin signerade publika inbjudan till koordinatorn i bootstrapfilen; koordinatorn
kontrollerar även den annonserade endpointen före kandidatvisning. En kandidat
ansluts inte automatiskt till en ny session.

När alla tre signerade inbjudningar tillåter testtokens kan Windows skapa
sessionen med testledgern. I samma interaktiva koordinator-CLI används:

```text
lan.start label=Windows allow_test_tokens=true auto_produce=false
lan.export_bootstrap path=gg-lan-bootstrap.json
lan.status
lan.session_create distribute=true enable_test_tokens=true
lan.circle_start duration_ms=10000 batch=1 amount_atomic=1000000
```

De andra klienterna startas med bootstrapfilen innan sessionen skapas.
Kontrollera deras namn i `lan.status`. I Desktop finns motsvarande
cirkelknapp och en saldorad per peer i LAN-dialogen. Börja direkt efter ny
parning med batch 1 i
10 sekunder. Desktop har val för batch 1–16 och längd 1–60 sekunder;
höj batchen först efter ett godkänt gemensamt prov. `lan.circle_stop`
avbryter provet, medan `lan.stop` eller Ctrl+C stänger hela den egna peeren.
Ett prov har en gemensam arbetsbudget på högst 60 sekunder, inklusive
första och sista kvittosynkronisering och nätväntan, samt en fast kvittokvot.
Därefter har enbart avstängningsmeddelanden en separat gemensam budget på
en sekund. Om arbetsbudgeten tar slut före alla tre bekräftat samma kedja
visas ett delvis genomfört prov med `TIME_BUDGET`. Mängden är
exakta atomiska testenheter: 1 000 000 atomer motsvarar en GG-LAN(TEST).
Belopp går aldrig genom binära flyttal.

Koordinatorn begär bara den överenskomna cirkelöverföringen av den egna
signeraren på respektive apparat. Signerade batcher och kvitton skickas över
den autentiserade transporten. Ett godkänt varv kräver att alla tre har
bekräftat samma kvittokedja. Visad TX/s bygger på faktiskt kvitterade
testöverföringar och uppmätt tid, med transportens resursgränser kvar.
Delvis genomförda prov, kvotstopp och saknad synk ska redovisas uttryckligen.

Det första observerade provet på faktisk Windowsdator, Linuxdator och Termuxtelefon
registrerade 16 signerade testöverföringar men avslutades med fel före ett
komplett varv. Koordinatorns saldon var Windows 984, Termux 1016 och Linux
1000 GG-LAN(TEST) vid den observationen, inte den senare sessionens aktuella
saldon. Detta är ett partiellt resultat med noll kompletta varv,
inte ett godkänt fysisk-enhetsprov. Efter transportuppdateringen ska alla tre
egna processer stoppas, uppdateras, startas om och paras på nytt innan provet
upprepas. Ett källkodspaket ändrar aldrig automatiskt en redan körande nod.

Automatisk förslagsproduktion hålls avstängd under ny parning och tokenprov
(`auto_produce=false`). Befintliga sessions-, frame- och transportkrediter
är ändliga och höjs inte. Prototypen ska provas i en ny session; kvotstopp
hanteras här med helt ny parning i stället för höjda gränser. Ett senare förslagsprov
kan startas uttryckligen med Producera lokalt eller `lan.produce`.

Desktop visar den aktiva LAN-peerens graf, verkliga peerstatus och egna
producenter. **Stoppa** avbryter även under parning och belastning; städningen
görs utanför UI-tråden. Ctrl+C avslutar terminalprocessens egna trådar och
socketar. Ett fristående CLI-kommando styr inte en annan process.

## Godkänt enhetsprov

Ett lokalt prov med tre separata processer ersätter inte dessa kontroller:

1. Alla tre fysiska enheter visar samma sessionsdomän och sex producenter.
2. Varje enhet signerar bara för sina egna två producenter.
3. Förslag från alla tre enheter tas emot och verifieras hos de andra två.
4. Gemensamma förslag har identiska hashvärden och föräldrareferenser.
5. Avbrott eller frånkoppling visas som verkligt tillstånd; återanslutning
   inom samma session reparerar saknade föräldrar inom kvoten.
6. Stoppa/Ctrl+C fungerar under trafik och lämnar inga egna arbetare kvar.

Appen anger inte automatiskt att fysiska värdar har verifierats. Ett stängt
brandväggshål, ett isolerat gäst-Wi-Fi eller en sovande telefon kan hindra
trafik trots samma SSID. Ändra nät-/brandväggsinställningar först när ett
konkret anslutningsfel visar att det behövs.

[Nästa steg och publik beredskap](dagoblin-launch-readiness.md)
