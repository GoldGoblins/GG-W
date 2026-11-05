# Producentgrenar, karantän och verifierad återhämtning

Datum: 2026-10-31. Omfattning: det befintliga producentägda, icke-finansiella
privata DAG-formatet. Ingen publik aktivering eller fysisk enhetsuppdatering.

## Ursprunglig avsikt och verifierade fynd

En felande producent ska inte stoppa andra producenters oberoende arbete.
Riktig payload, nonce, ägarskap och certifierad ordning ska återges korrekt.
Motorn tog tidigare endast den först mottagna grenen. En annan signerad gren
spärrade all lokal produktion och det andra råblocket gick förlorat. I den
stora vägen sattes spärren dessutom innan alla individuella TX-signaturer
kontrollerats. Replikan kunde därför inte återhämta den gren SDK faktiskt valt.

Två nya riktade tester reproducerade felen före ändringen. De ursprungliga
globala stoppkraven ersätts bara för nya fullt verifierade producentgrenar;
äldre sparade globala fel utan tillräcklig payload lämnas spärrade.

## Implementation och regler

Alla LAN-payloads använder samma verifieringsväg. Varje kandidats föräldrar,
producentkedja, individuella TX, nonce, beloppsgräns och signatur kontrolleras.
En kompakt kausal vy och logaritmiska författaranknytningsuppslag hindrar att
ett kandidatblock blandar två oförenliga grenar i sitt föräldrahistorik.

Båda giltiga grenarna sparas som ursprungliga signerade journalposter före
publicering. Karantänen härleds från dessa poster efter återstart och gäller
den specifika producenten. Övriga producenter fortsätter. Producentens högsta
observerade sekvens och nonce sänks aldrig. En förfalskad TX inuti ett korrekt
signerat block räcker inte för karantän: båda blockens fulla payload måste
ha klarat verifieringen.

Oavgjorda grenar exekveras inte samtidigt i kontoförhandsvyn. Vyn börjar vid
SDK:s verifierade prefix och lägger till ett kompatibelt, förälderslutet urval
av övriga kandidater. Karantänens övriga grenar räknas som konflikter. Cachade
kontodeltan gör att förhandsvyn inte återverifierar alla transaktioner. Samma
transaktionskropp i flera grenar ökar inte den unika TX-räknaren flera gånger.
Förslag, lokal förhandsvy och kanoniskt medlemskap förblir skilda begrepp.

Ny lokal produktion länkar sin egen kedja direkt och använder bara certifierade
huvuden från andra producenter. Den väntar inte på att dessa ska producera
nya block. Detta undviker nya osäkra korsreferenser. En äldre egen signerad
gren som ännu är oförenlig med valt prefix väntar; den omsigneras inte med
återanvänd nonce. Om dess beroende blir certifierat kan samma signerare
fortsätta från sin redan bevarade nonce. En irreversibelt förkastad gammal
egen gren får ingen påhittad automatisk återställning.

En full replika eller validator behöver nu den faktiska payloaden innan den
publicerar komplett kanoniskt medlemskap. Saknade block hämtas i certifierad
ordning genom riktig autentiserad GET, med högst en återhämtningsarbetare per
nod, 32 nya poster och åtta sekunders budget per omgång. Partiellt hämtade
poster sparas och återanvänds vid nästa omgång. Mottagningen har samma fulla
signaturkontroll och synkrona journal som vanlig trafik.

Före antagning av medlemskap kontrolleras verkliga blockfält och föräldrar,
ordningsrot, TX-summa, hela kontoexekveringen och kontorot mot SDK-tillståndet.
Detta ersätter inte SDK:s kvorumkontroll: bara den befintliga verifierade
controller-/bevisvägen får mata denna interna exekveringsgrind. En giltig äldre
prefixobservation får inte skriva tillbaka ett äldre valt prefix.

Ytterligare obestämda grenvarianter begränsas till två per producent/sekvens
och efter karantän åtta kandidater respektive 64 MiB per producent. Hashar från
ett komplett SDK-verifierat ordningsbevis kan hämtas även om en tidigare
oavgjord kvot är fylld. Detta ger inget medlemskapsbesked före payloadkontroll.
Vid uppspelning av den signerade journalen gäller fortfarande alla protokoll-,
signatur- och globala lagringsgränser, men en gammal giltigt sparad tredje
SDK-vald variant kastas inte bort av en lokal mottagningskvot.

Skrivfel före/efter commit och fel vid RAM-publicering efter beständig skrivning
ger inget falskt lyckat besked. En inkonsekvent RAM-publicering stoppar mer
arbete tills ägd verifierad journal spelats upp igen. Nycklar och identitet
återanvänds genom riktig profilåteröppning, utan ny identitet eller nollställd
sekvens.

Producentlistan visar den signerade nodetiketten tillsammans med karantän
eller väntan på gren. Grafen markerar endast de block som faktiskt har
SDK-verifierat medlemskap. Andra autentiska grenar kan finnas i grafen utan
att utge sig för att vara kanoniska.

## Provning och avgränsning

Riktade prov använder riktiga signerade transaktioner, olika ankomstordningar,
felaktiga TX-signaturer, djupa författarkedjor, oförenliga föräldrar, ändrade
Merklerötter, noncegränser, kvoter, lagringsfel och profilåteröppning. Den rena
exekveringsfixturen provar rötter, utan att fabricera ett SDK-certifikat.

Ett separat processprov startar fyra riktiga SDK-barn och tre ägda LAN-profiler
på en Windows-värd. En replika får först två andra signerade varianter och
hämtar därefter den verkligt SDK-certifierade tredje varianten med 5 000 TX.
Fulla kontorötter verifieras, den delade transaktionen dubbelräknas inte och
båda forensiska grenar samt vald payload överlever omstart. En annan lokal
producent fortsätter, certifierar nya block och behåller rätt nonce efter
profilåteröppning. Det är avsiktlig felinjektion med disponibla testnycklar,
inte ett observerat angrepp eller ett uppmätt kapacitetsmål.

Bred regression, normala replika-/lättklientflöden, certifierade konfliktprov,
riktig QML och de granskade källpaketen kontrolleras separat mot fryst kod.
Linux-/Androidbinärer är fortfarande kompilerade, inte fysiskt körda här.

## Återstående leveranskrav

Global ingress-/arbetsbudget och framdrift efter avvisade sidposter, säker
kandidatinsamling/pruning, maximal payloadåterställning och adversariellt
undanhållande kräver fortsatt arbete. Karantänkvoten är ingen lösning på all
nätverksöverbelastning eller på den ändliga sessionens historikgränser.
Permanent förkastade äldre egna signeringsgrenar behöver en uttrycklig
ägaråterhämtningspolicy utan nonceåterbruk.

Fysisk uthållighet, avtalad mållast, publik medlemskapspolicy, monetär modell,
mining/pooler och oberoende säkerhetsacceptans återstår. Ingen mainnetberedskap,
uthållig 200 block/s-kapacitet, Git-push eller ny bootstrapcykel intygas här.
