# Generella konton i den versionerade native-applikationen

## Ursprunglig avsikt

Ett riktigt konto ska kunna finansieras och användas utan att vara ett av
laboratoriets fyra validatorägda startkonton. Kontoägaren signerar sina
betalningar. CLI och Desktop ska senare visa samma certifierade konto och
tydligt skilja på ett befintligt konto och bevisad frånvaro.

## Faktiska protokollgränser

Den nya native-vägen kräver genesis `gg.native.genesis.v6`, finansiell source-v4,
policy-v3, finansiellt commitment-v4, native state-v5 och native commitment-v5.
Äldre genesis och source-v1/v2/v3 behåller sina kodningar och regler. Ingen
befintlig session migreras eller återställs automatiskt.

Genesis beskriver 1–128 sorterade, unika och positiva initiala allokeringar,
vars summa måste vara exakt det privata testutbudet. Den anger också ett
maximalt kontoantal. Maximal total och genesisankare binds i kontoträdets
regler efter att genesis har kodats, så inget cirkulärt hashberoende införs.
Den äldre fyrakontolistan är `null` i det nya formatet; den är inte listan
över alla tillåtna eller finansierade adresser. Finansiering är skild från
de fyra validatorernas röstmedlemskap. Sex producenter och fyra validatorer
är fortfarande den uttryckliga privata laboratorierostern.

Ett nytt konto uppstår genom en finansierad och ordnad betalning till en giltig
kontonyckel. En ny peer får inget saldo eller rösträtt. Kända producent-, nod-,
ägar- och röstnycklar får inte förväxlas med betalningsnycklar. Varje indata
kontrolleras fortfarande med den befintliga kontosignaturprofilen. En giltig
signatur från ett ofinansierat konto ger inget saldo. Producentens signatur
kan inte ersätta avsändarens kontosignatur.

## Exekvering, bevis och lagring

Det publika nya tillståndet innehåller en kompakt kontorot med autentiserat
kontoantal, höjd och totalsaldo. Metadata ingår i både det finansiella och
native commitment som SDK:s AppHash binder. Hela kontolistan skickas inte
med varje tillstånd. Den ordnade kontokärnan bevarar totalen och avsändarens
nonce. Kontogräns, fel nonce och otillräckligt saldo får deterministiska utfall;
övriga giltiga betalningar kan fortsätta. Nya sammanfattningar och kvitton
har version 2; äldre kvittensregler utvidgas inte till det nya utfallet.

Nya nåbara kontonoder, den exakta signerade journalen, kvittensmetadata och
auktoritativt huvud skrivs i samma synkrona LevelDB-batch. Därefter släpps
den privata nodgrafen. Historiska rötter läses genom en livstidskontrollerad
läsare med högst 512 cacheposter. Kontobevis delar den befintliga begränsningen
på samtidiga bevisläsningar och håller inte applikationslåset under disk-IO.

Kall start återspelar de ursprungliga signaturerna och betalningarna. Ett
separat privat diskindex räknar och verifierar den exakt återhärledda mängden
kontonoder. Saknade, skadade och extra indexnoder avvisas. Ett cacheuppslag
ersätter inte kontrollen av den öppnade nodens hash och förväntade metadata.
Streamingarkiv använder också begränsad cache och temporärt diskindex.
Arkivåterställning skapar inga signeringsnycklar eller rösträtter.

Den nya konto-API:n kan ge historiskt medlemskap eller verifierad frånvaro.
Native och den gemensamma WASM-koden kräver ett separat förväntat konto i
verifieringsanropet, utöver det betrodda genesisankaret och SDK-certifikatet.
Webbpolicyn binder samma begärda adress till klientens betrodda värde. Detta
behövs eftersom en korrekt frånvaroväg kan täcka flera saknade adresser:
verifierad frånvaro måste fortfarande avse rätt plånbok. Ny nonce kodas som
exakt decimalsträng även i webbutdata. Frånvaro visas med `exists: false`.

## Fynd från egna prov

Det första större native-provet finansierar 5 000 olika mottagare genom riktiga
kontosignaturer och producentoriginal. Det går genom ABCI:s CheckTx,
PrepareProposal, ProcessProposal, FinalizeBlock och Commit, följt av tom
SDK-höjd, cut, ett fördröjt original, historiska kontobevis och kall replay.
Detta är applikationsprov; signerade SDK-headerfixturer är inte ett levande
konsensusnät eller en nätkapacitetsmätning.

Felprov kontrollerar båda sidor om den atomiska skrivgränsen: fel före skrivning
och ett faktiskt genomfört synkront skrivsteg vars svar därefter tappas.
Återstart väljer den verkligt sparade historiken. Dessa prov påstår inte att
ett fysiskt strömavbrott har injicerats mitt i hårdvarans skrivning.

Ett nytt prov hittade att producentvyer jämförde pekare till den nya metadata-
strukturen i stället för dess värden. En kopierad men identisk rot kunde då
inte välja sitt sparade föräldrabevis. Jämförelsen använder nu metadata-
innehåll. Ett särskilt regressionsprov kräver att upprepade tomma höjder
behåller rätt producentvittne utan att förbruka extra vyplatser. Det röda
provet och dess källkod behålls i den privata granskningshistoriken.

Ytterligare prov omfattar förfalskade kontobevis, oberoende initiala
allokeringar, finansiering följd av en egen signatur från det nya kontot,
full arkivåterläsning och icke röstande SDK-återställning. Alla antal måste
knytas till respektive källversion och körningsrapport; underfall och samma
prov på flera system ska inte summeras som oberoende försök.

## Vad som återstår

Native- och WASM-byggnader, gamla och nya bevisvektorer och aktuell regression
måste verifieras mot den slutliga koden. Detta dokument ersätter inga resultat.
Python-/CLI-session, skyddade självständiga kontoprofiler, uttrycklig
signeringsavsikt och den korrekta Desktop-vyn måste därefter integreras och
provas genom verkliga SDK-processer. Den vanliga befintliga CLI-vägen får
inte börja annonsera den nya versionen innan dessa delar är sammanhängande.

Det fasta testutbudet innebär ingen beslutad publik emission, avgiftsmodell,
mining eller poolbokföring. Publikt medlemskap, Sybilskydd, målkapacitet,
oberoende säkerhetsacceptans och fysisk Windows/Linux/Termux-acceptans är
fortsatta leveranskrav. Ingen publik nätaktivering eller Git-publicering
godkänns av dessa lokala komponentprov.
