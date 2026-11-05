# DAGoblin: genesisbunden exekveringspolicy

## Ursprunglig avsikt

Nätverket behöver uthållig historik och återhämtning utan att ändra ägare,
noncer eller vad fullnod och lättklient faktiskt har verifierat. Den tidigare
gränsmätningen visade att dagens ändliga protokoll stannar efter 217 verkliga
5 000-TX-block. En större lokal cache löser inte den konsensusgränsen.

## Fynd och implementerat beslut

Dagens gränser är regler för giltig exekvering och bevis, inte enbart lokala
resursbudgetar. Nya icke-finansiella testsessioner använder därför
`gg.parallel-dag.genesis.v3` och en explicit `execution_policy` som ingår i
genesisbytes, genesis-hash, signerad LAN-session, nätverksidentitet och den
native genesisens DAG-källa. Det offentliga omslaget har motsvarande v3.

Policyn anger blockets storlek, antal TX, föräldrar, rang och sekvens;
checkpointens råa/encodade storlek och blockantal; historikens block-/bytegräns;
full signerad genesisåterspelning och det icke-finansiella transaktionsläget.
Python och den gemensamma native/WASM-koden godtar endast exakt den policy
som deras faktiska exekveringsregler stöder. Ett ändrat fält blir inte godkänt
genom att avsändaren räknar om sin genesis-hash.

Äldre v2-genesis importeras och exporteras med sina ursprungliga bytes och
regler. Den får inte ett nytt policyfält vid återöppning. Ett policyfält som
läggs till i v2, en v3 utan policy, fel omslagsversion, okända profiler och
typkonverterade gränsvärden avvisas. Ursprungligt manuellt tomt v1-labb består.
Go-avkodningen skiljer uttryckligen på utelämnat fält och JSON-null för den
äldre genesisen; båda runtimes ska avvisa samma otillåtna äldre utökning.

Reglernas numeriska värden ändras inte: 4 095 historiska block, 512 MiB rå
historik, 32 MiB rå block-/checkpointpayload, 48 MiB encodad checkpoint,
128 block per checkpoint och högst 50 000 TX per block. Lokal RAM, spool,
kö- och diskkredit är separata budgetar och ingår inte i denna konsensuspolicy.

## Verifiering och begränsning

Negativa prov muterar varje policyfält och räknar om genesis-hash. Andra fall
provar saknade/extra fält, null, bool/float/sträng i stället för heltal,
versionsblandning och att en senare caller-mutation inte ändrar ägd policy.
Verkliga signerade TX och äldre native regressionsfall ska fortfarande passera.
Samlad verifiering binds separat till fryst källversion och faktiska artefakter.

WASM-fingeravtrycket omfattar uttryckligen den nya gemensamma policykällan.
Förkontrollen fångade att Desktopens separata källista först saknade filen;
den vägrade då att använda artefakten. Bygg- och runtime-listan omfattar nu
samma fil, vilket också kontrolleras av det befintliga bygggrafprovet.
Ingen gammal binär eller tidigare maskinkodsgranskning får utges för att
verifiera den nya native-versionen.

Detta gör policybytet explicit och förhindrar tyst blandning av regler. Det
inför inte ett beständigt obegränsat arkiv, pruning, snapshot-tillit, offentlig
medlemskapspolicy, emission, miningbelöning eller poolutbetalningar. Det
bevisar inte målhastighet, fysisk acceptans eller full huvudnätsberedskap.

## Nästa beroende

En ny arkiv-/retentionsmodell måste ange hur originaldata behålls, hur en nod
med lokalt resursstopp återhämtas, hur bootstrap verifieras och vad den visar
som historiskt verifierat. Den får en egen genesisbunden policy och behöver
exekverings-, bevis-, krasstålighets- och nätverksprov innan den kan användas.
Den nuvarande ändliga policyn får inte ommärkas till en färdig sådan modell.
