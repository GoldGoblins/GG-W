# DAGoblin: producentkontext, återläsning och nätverksbindning

Datum: 2026-11-01. Förpubliceringsgranskning av den uttryckliga segmenterade
modellen. Befintlig fysisk LAN-session och Desktop-process aktiveras inte.

## Ursprunglig avsikt

CLI:s riktiga nod- och kontotillstånd ska vara samma källa som Desktop visar.
Långsammare noder ska kunna återhämta sig och fortsätta utan att byta
producentnyckel, återställa sekvens/nonce eller uppfinna block i gränssnittet.
Kod och säkerhetsgranskning ska vara sammanhängande före nästa gemensamma
publicering och fysiska acceptansprov.

## Fakta och konstaterat fel

Den ursprungliga segmenterade härledningen räknade bort `network_id` för
att undvika en cirkel med den tänkta framtida LAN-sessionens hash. Ett
verkligt regressionsprov visade följden: samma producentnycklar, starttid,
roller och initialkonton kunde få samma kedje-ID trots olika nätverks-ID.
Ett originalsignerat startblock med riktiga individuellt signerade TX
accepterades då i den andra nätkontexten. Felet reproducerades separat i
Python-admission och native-exekveringskärnan. De ursprungliga misslyckade
proven sparas med sin dåvarande kod, tillsammans med tidigare godkända
SDK-prov. De skrivs inte om till aktuella godkända resultat.

Detta är belägg för felaktig nätverksseparering i vår ännu opublicerade
icke-finansiella modell. Det är inte ett påstående om stulna pengar,
angrepp på ett externt nät eller ett bevis för hela systemets säkerhet.

## Research, slutsats och beslut

[EIP-155](https://eips.ethereum.org/EIPS/eip-155) binder transaktioners
signeringsunderlag till ett kedje-ID för att skydda mot återanvändning
mellan olika Ethereumkedjor. [EIP-712](https://eips.ethereum.org/EIPS/eip-712)
beskriver separata signeringsdomäner och ett kedjefält. Vår kod använder
inte dessa Ethereumformat eller deras ECDSA-kod. Egen slutsats: vårt
signerade `chain_id` måste också härledas från den faktiska nätkontexten.

Den uttryckliga källan v2/genesis v4 binder nu nätverks-ID, producenter,
roller, konton, starttid och exekverings-/historikpolicy till hela SHA-256-
härledningen av kedje-ID:t. Den nya domänen använder alla 64 hextecken;
den förkortade äldre kedjesträngen används endast i privata hjälpvyer för
att återanvända äldre formkontroller. Den används inte i nya signerade
block, TX eller publika commitments.

Native och Python provar både återanvändning av hela startblocket och
försök att lägga gamla signerade TX i ett korrekt omsignerat nytt yttre
block. Tidigare privata, obundna v4-källor accepteras inte tyst och får
inte nya identiteter genom en implicit omskrivning. Äldre publicerade
source-v1/genesis-v1–v3 ändrar inte sitt format.

Beslut för kommande LAN v5: nätkontexten måste bindas före offentlig
genesis, från den signerade uppsättningens ägare, roster och kommitté.
Den kan inte samtidigt definieras som hashen av ett färdigt hölje som
innehåller den redan härledda genesisen. Ingen v5-förhandling aktiveras av
denna komponent; den kvarvarande integrationen måste följa detta krav.

## Producentmotorn och återläsningen

Den nya Python-ingången konstruerar uttryckligen en ny källa v2, eller
kör den ägda SDK-verifieraren och spelar sedan upp originalarkivets aktiva
svans mot en härledd tom epochbas. Den andra filpassagen hashar samtidigt
samtliga byte och måste nå samma fullständiga filslut som native-kvittensen.
Ett externt `verified`-fält ersätter inget av arbetet.

Global producentsekvens, nonce och rank fortsätter från basen. Första
egna blocket i en ny epoch kräver segmentgränsen som direkt förälder;
senare block kräver den egna föregångaren. Förhandsval och SDK-vald
ordning startar vid de globala basvärdena. Lokal exekvering räknar om
konton, nonce, payloadbyte, rank och ordningsrot mot det valda tillståndet.
Skaparnyckel och globalt ordningsindex förblir bundna till rätt producent.

En segmentgräns är ingen signerad producentproposition. Den annonseras
inte som payload eller räknas som ett nytt block. Grafens geometri använder
små rankavstånd från epochbasen, medan global rank och producentsekvens
exporteras exakt som decimalsträngar. Det stora heltalsprovet är en
uttrycklig form-/serialiseringsvektor, inte återspelning av så många block.
Historisk återläsning nollställer inte konton men rensar nya trafikmått.

Standardåterläsningen är en nyckellös arkivvy med begränsad payloadcache
och högst 4 095 aktiva filpositioner. Kalla payloadläsningar kontrollerar
filidentitet och ursprunglig wirehash. Vyn kan inte börja signera eller
ta emot färsk trafik innan en riktig beständig journal har bundits.

Ett uttryckligt RAM-prov får hålla högst 16 MiB råpayload för att prova
producentfortsättning. Detta är en gräns för råbyte, inte ett uppmätt tak
för processens totala minne. Det är inte beständig NodeProfile-drift eller
bevis på återstart av en produktionssignerare. Ingen nodjournal återställs,
byts ut eller migreras av arkivvyn.

## Prov, begränsningar och nästa steg

Riktade prov täcker riktiga 5 000 signerade TX, nyckel-/rollbindning,
sekvens/nonce, direkt gränsförälder, ordnings- och skaparändringar,
räknarprecision, oförändrad offentlig genesis och nekad återställning av
en redan aktiv motor. Ett separat faktiskt SDK-processprov kräver att
Python-genererade block efter återläsning och två segmentgränser väljs
av fyra riktiga SDK-processer. Aktuella kvittenser och tidigare
misslyckanden sparas separat i den privata komponentgranskningen.

Efter nätverkskorrigeringen passerade 562 Go-prov, inklusive samtliga
tidigare 557. Windows amd64, Linux amd64/arm64, Android arm64 och WASM
byggdes på nytt. Det färska SDK-provet använde 17 processinstanser på en
Windowsvärd: fyra initiala noder och avgränsade återstarter, inte 17
oberoende operatörer. Totalt valdes fem riktiga DAG-block, två segment-
gränser och 15 002 signerade TX. Av dessa skapade den återlästa Python-
motorn 5 001 TX. Den fortsatte med rätt nonce, global sekvens, gräns-
förälder och precheck efter ytterligare en återläsning. Fyra stoppade
SDK-lager exporterade först identiska arkiv; ett nytt arkiv efter andra
gränsen återlästes också. Råstorleken för Python-blocket med 5 000 TX
var 2 670 611 byte. Detta är en filstorlek, inte uppmätt nätkapacitet.

50 riktade Python-prov samt verklig native-verifiering följd av
fil-/avbrottsprov passerade. Ändring eller trunkering efter native-
framgång, avbrott efter första aktiva admission och utbyte av en kall
payloadfil gav ingen partiellt godkänd motor. Standardvyn nekade både
signeraranslutning och färsk trafik; RAM-budgeten kunde inte utvidgas
genom en stor återläsning.

I den färska binären saknades en separat symbol för kedjehärlednings-
metoden. Den observationen sparades, och den verkliga anropande
`validateSegmentedSource`-funktionen importerades i Ghidra 12.1.4:
1 131 byte och 241 instruktioner. Den dekompilerades under begränsad
resursbudget och jämförs med Go-disassembly och källprov. Go:s register-
ABI och hela binärens referenser återskapades inte. Detta är statiskt
granskningsstöd för den aktuella binären, inte en säkerhetsgaranti.

Återstår: signerad LAN v5-förhandling, atomisk NodeProfile-import och
beständig producentaktivering, samma kontounderlag i Desktop, nätbaserad
arkivhämtning och lagringsbudget. Målkapacitet, strömförlustbeständighet,
monetär modell, mining/pooler och fysisk Linux-/Termux-acceptans är
fortfarande öppna krav. Ingen Git-push, bootstrapöverföring, Desktop-
omstart eller publik nätaktivering ingår i denna komponentkvittens.
