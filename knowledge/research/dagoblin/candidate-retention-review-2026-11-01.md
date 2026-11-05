# DAGoblin: begränsad kandidatcache med deterministisk konsensus

## Avsikt och fynd

En överbelastande peer eller en serie övergivna förslag ska inte permanent
tömma nodens lagring. Samtidigt ska alla korrekta validatorer exekvera samma
beslutade block till samma tillstånd, oavsett vilka kandidater de tidigare sett.

Den tidigare native-lagringen bevarade förberedda manifest och payloads även
när de aldrig valdes. Den gemensamma ändliga lagringsbudgeten kunde därför
förbrukas av kandidater. En första kvotmodell som avvisade giltiga inkommande
förslag vid lokal kvotgräns stred dessutom mot CometBFT:s determinismkrav.
Den modellen ersattes före leverans och godkänd verifiering.

## Beslut och faktisk mekanism

Committad payload, dess historiska manifest och dess bevisindex bevaras.
Endast den **icke committade kandidatcachen** får ersättas eller rensas.
En förberedelse är ingen slutlighets- eller permanent tillgänglighetskvittens.

Den privata native-implementationen begränsar kandidatcachen till 128 manifest
och 96 MiB logiska värdebytes. Den reserverar dessutom utrymme för en hel
32 MiB-payloadbatch, ett manifest, 128 payloadobjekt och ett manifestobjekt.
De befintliga totala gränserna på 640 MiB och 8192 objekt per objektsort
finns kvar. Lagringskvoter är lokala resurser, inte nya tokenregler.

`PrepareProposal` får vid kandidattryck välja ett tomt, giltigt förslag.
`ProcessProposal` verifierar hela blocket deterministiskt. Om dess cache är
full ersätts äldre icke committade cacheposter atomiskt med den nya, validerade
payloaden. Ny payload synkas före Accept. Skillnader i tidigare ankomstordning
får därmed inte ensamma orsaka Accept på en validator och Reject på en annan.
Faktiskt disk-/skrivfel gör den lokala noden otillgänglig och stoppar vidare
lagringskvittenser; det är inget nytt protokollbesked om ett giltigt block.

CometBFT:s betrodda konsensusväg lagrar det beslutade blocket före
`FinalizeBlock`. Den callbacken levererar hela blockets data, även om en äldre
lokal cachepost har ersatts. Applikationen återexekverar och synkar dess
payload och kan då rensa återstående förlorande kandidater. Detta ändrar
varken committad höjd, publikt bevisindex, kontotillstånd eller signerad
native-historik. Dessa väljs tillsammans först i `Commit`, i samma synkrona
atomiska batch som exakta metadata och eventuella kvarvarande cacheborttagningar.

Källans signerade Python-journal för producentgrenar är en separat datakälla.
Denna ändring raderar inte ägarens signerade historik eller nollställer nonces.

## Återställning och granskning

RAM-indexet innehåller bara publika objektnamn och storlekar. Vid återöppning
kontrolleras databasen, varje vald originalpayload återspelas kryptografiskt,
och det historiska bevisindexet jämförs exakt. Därefter härleds vilka objekt
som är committade respektive endast kandidater. Ingen permissiv reparation,
ny ägaridentitet, automatisk historiktrunkering eller ny nonce används.

Ett skrivfel före Sync lämnar tidigare data. Ett förlorat svar efter faktisk
Sync kan lämna den nya batchen. Båda fallen spärrar nya kvittenser tills noden
återöppnats och verifierat det verkliga utfallet. Ett avbrott efter payload-Sync
men före `Commit` återställer fortfarande den äldre committade höjden;
CometBFT kan återspela det redan lagrade beslutade blocket.

Det finns riktade native-prov för 128 riktiga signerade kandidater, olika
cachehistorik på två validatorer, ersatt men senare beslutad payload, delad
wire mellan manifest, oförändrade historiska kontobevis och ordningsbevis,
befintlig läsare under rensning samt fel före/efter faktisk Sync vid
cacheersättning, finalisering och commit. Ogiltig TX inuti ett i övrigt signerat
block, fel höjd och äldre urval får inte auktorisera någon rensning.

Ett separat prov fyller bytekvoten med verkliga signerade 5000-TX-kandidater,
ersätter cachen genom en giltig inkommande proposal och återexekverar därefter
en äldre, faktiskt borttagen payload som beslutat block. Det är ett ändligt
lokalt prov, inte en full historikåterställning eller kapacitetsmätning.
Exakta slutresultat och oförändrad källkod måste styrkas av körkvittensen.

## Primärkällor och slutsatser

CometBFT 0.40 kräver samma `ProcessProposal`-besked från samma committade
tillstånd och block. Dokumentet förklarar också återexekvering av kasserade
kandidattillstånd och ordningen lagrat block, `FinalizeBlock`, `Commit`.
Vår slutsats är att den lokala kandidatcachen måste vara ersättningsbar,
medan committad tillgänglighet och applikationstillstånd har starkare krav.
[ABCI++-krav för använd versionslinje](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md).

GoLevelDB dokumenterar batchvisa skrivningar och konsistenta, pinnade
databasläsningar. Rensning, räknare och val hör därför till samma batch;
en pågående läsare använder sin tidigare konsistenta databasvy.
[GoLevelDB API](https://pkg.go.dev/github.com/syndtr/goleveldb/leveldb).
Källorna kontrollerades 2026-11-01.

## Kvarvarande krav och antaganden

ABCI-vägen är en betrodd intern del av den ägda CometBFT-processen, ingen
öppen fjärrstyrd rätt att finalisera. Antagandet om lagrat beslutat block
kommer från CometBFT:s återställningsprotokoll. Denna cache är inget separat
datatillgänglighetscertifikat och tillför ingen tolerans utöver dess quorum-
och nätverksantaganden.

Gränserna avser logiska databasvärden. Fysisk diskförbrukning påverkas även
av nycklar, WAL, pinnade läsningar och LevelDB-kompaktering. Diskfullt och
lagringsfel ska stoppa kvittenser; omedelbar fysisk frigöring intygas inte.

Detta är inte pruning av committad historik. Prototypens 4095-postergräns
och 512 MiB exekveringsgräns kvarstår. Maximal historikåterställning,
adversariellt undanhållande och alternativa payloadkällor, äldre oförenliga
ägargrenar, fysisk fel-/uthållighetsacceptans, monetära regler, publikt
medlemskap, mining/pooler, mållast och oberoende granskning återstår.
