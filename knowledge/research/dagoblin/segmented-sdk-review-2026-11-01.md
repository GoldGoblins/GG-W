# DAGoblin: SDK-beslut för segmentövergång och verifierad återstart

Datum: 2026-11-01. Lokal implementation under samlad granskning; befintliga
LAN-nät uppgraderas inte automatiskt och ingen fysisk nätverksacceptans ingår.

## Ursprunglig avsikt

En avslutad del av DAG-historiken ska få en enda konsensusbunden gräns.
Originaldata, konton, ägare och noncer ska finnas kvar och gå att verifiera
efter omstart. CLI och UI ska utgå från samma verkligt valda tillstånd.

## Beslut och konstruktion

En uttrycklig native-genesis v4 binder den separata `dag_segmented`-källan.
Native-tillstånd v3 och commitment v3 binder hela segmenttillståndet i
AppHash: aktiv rot, avslutade segments rot, senaste brytpunkt, ackumulerade
räknare samt producentnycklar, skapade huvuden, sekvenser och noncer.
Gamla genesis-/DAG-format behåller sina regler. Båda DAG-lägen samtidigt
eller ny segmentkälla under gammal genesisversion nekas.

En brytpunkt är en egen kanonisk SDK-transaktion som binder föregående
tillstånd, epoch och exakt beräknad brytpunkt. Arkivet måste skrivas, synkas
och återverifieras innan ett förslag får lämnas eller accepteras. Endast ett
lyckat atomiskt SDK-appcommit väljer den nya basen. Att förbereda ett arkiv,
en mempoolkontroll eller en misslyckad finalisering publicerar ingen övergång.

Aktiva original, manifest, vald native-historik och arkivreferenser lagras i
en separat exklusivt öppnad LevelDB. Aktiva kandidater har fasta byte-/antal-
gränser; felaktiga och tvetydiga skrivningar gör handtaget obrukbart tills
återstart fastställer exakt det gamla eller nya tillståndet. Övergångens
arkivreferens, nya manifest och borttagning av aktiv kandidatdata skrivs i
samma synkrona batch som det valda tillståndet.

Återstart återspelar hela den refererade, originalsignerade arkivkedjan från
genesis och därefter det aktiva segmentet. Även varje bevarad historisk
DAG-frågesnapshot måste motsvara ett faktiskt återspelat tillstånd. En
självkonsistent, återhashad kontobild ersätter inte originalhistorik.

Den delade native-/WASM-verifieraren kan kontrollera SDK-certifikatet och
dess segmentcommitment mot en separat låst genesis. Den hävdar uttryckligen
inte full historikåterspelning eller konto-/blockmedlemskap för detta nya
format. Den befintliga icke-finansiella transaktionsmodellen är oförändrad.

## Verifieringsomfattning och återstående arbete

Provunderlaget skiljer riktiga SDK-kryptokontroller, applikations-/lagrings-
prov och eventuella separata SDK-processkörningar. Ett signerat testcertifikat
är inte i sig en körning av fyra oberoende fysiska validatorer.

På den aktuella koden passerade 509 Go-prov, inklusive samtliga tidigare
474, samt 45 berörda Python-prov. Fyra nya native-binärer kompilerades för
Windows amd64, Linux amd64/arm64 och Android arm64, samt en ny WASM-verifierare.
Linux/Android är korskompilering, inte fysisk körmerit.

Ett separat prov körde faktiskt fyra Windows-SDK-processer och deras lokala
RPC/P2P-trafik. De valde ett identiskt originalarkiv för 5 000 signerade TX
och samma kanoniska segmentövergång. Tre fortsatte med ytterligare 5 000 TX
när den fjärde var avstängd. Den fjärde återstartade och kom ikapp. Efter
hård omstart av alla fyra återspelades arkiv och aktiv historik, och nästa
nonce accepterades: totalt 10 001 unika signerade TX, tre valda block och en
vald övergång. Alla provets ägda barnprocesser avslutades.

Den faktiska processkörningen krävde korrekta väntvillkor för SDK:s
synkstatus och för certifikatet på nästa höjd. Tidigare misslyckade
provobservationer bevaras separat. Det nya provets första 30-sekunders
certifikatväntan var kortare än de befintliga väntbudgetarna för en utebliven
proposer; den anpassades till samma 90-sekunders observationsbudget som
tidigare nätprov. Protokollbudgetar och äldre provgränser ändrades inte.
En frånvarande validator kan alltså fortfarande ge ledarbytesfördröjning.
Ingen målhastighet härleds ur att denna korrekthetskörning passerar.

Den nya WASM-byggnaden godkände fyra äldre giltiga fall, två nya signerade
segmentfall och tre certifikat från den faktiska processkörningen. Den nekade
15 äldre och 20 nya manipulationer, med separat genesis-låsning och utan
påstådd full historikåterspelning. Ett fel i provhjälparens artefaktsökväg
stoppade först körningen före något verifieringsfall; även det underlaget
bevaras som fel, inte som ett godkänt prov.

Ghidra 12.1.4 dekompilerade 3 614 byte, 663 instruktioner, ur den faktiskt
byggda Windows-binärens segmenterade SDK-commit. Go:s egen disassembler
bekräftar anropet till den atomiska lagringsfunktionen. Detta är en begränsad
funktionsskiva utan rekonstruerad Go-register-ABI, refererad kod eller globala
data. Det ersätter inte källgranskning, felprov eller ett fullständigt
säkerhetsbevis. Negativa symlänkvägar saknar fortfarande faktisk körmerit på
denna Windowsvärd, där testkontot inte får skapa symlänkar.

Python-/CLI-producentens nya versionsförhandling och observering, UI:s
motsvarande bevisomfång, ny segmentbunden konto-/blockbevisning, arkivhämtning,
diskbudget, katalogbeständighet vid strömförlust och samlad fysisk acceptans
återstår före aktivering på apparaterna. Kapacitetsmål, offentlig ekonomi,
mining/pooler och huvudnätsberedskap är inte bevisade av dessa ändringar.
Producentnoncerna har fortfarande den icke-finansiella testmodellens
allokeringsgräns. Segmenterad historik inför ingen obegränsad monetär modell.
