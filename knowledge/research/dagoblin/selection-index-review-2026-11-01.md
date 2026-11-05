# DAGoblin: beständigt index för valda objekt

## Ursprunglig avsikt och fynd

Historikens tillväxt ska inte tvinga varje nod att behålla en växande lista
av alla gamla objekt i RAM. Riktiga valda block och deras ursprungliga ägare
ska fortfarande kunna återhämtas och visas korrekt i CLI och Desktop.
Signaturer, faktisk exekvering och beständighet får inte ersättas av cachetal.

Store behöll tidigare en `canonicalObjects`-karta med nyckel och storlek för
varje vald rådatapost och varje valt manifest. Även öppningen lade först
alla sådana nycklar i en RAM-karta. Den historiska kartan har nu tagits bort.

## Genomförande och gränser

Ett separat härlett index, version 1, lagrar exakt medlemskap och byteantal
för valda r/- och m/-objekt. Det använder varken Bloomfilter eller annan
probabilistisk klassificering. Indexmarkörer och valda räknare skrivs i samma
synkrona atomiska batch som native-historiken, det publika bevisindexet och
vald metadatarot. Förberedda men ännu inte valda payloads får ingen markör.
Räknarna i RAM publiceras först efter lyckad Sync.

Vanlig drift behåller bara det begränsade kandidatcachet i RAM. Vid öppning
av ett versionsmärkt index klassificeras redan valda objekt direkt genom
diskindexet. Endast väntande objekt läggs i kandidatcachet, med gränskontroll
under insättningen. Dess oberoende kataloggränser är 8 192 rådatanycklar och
129 manifestnycklar. Det ändrar inte den tidigare striktare normala
kandidatkvoten om 128 manifest eller rådatans/finaliseringens bytekrediter.
Antal nycklar är en strukturell gräns, inte ett uppmätt RAM-byteantal.

Den tidigare gamla lagringsversionen utan markörer kan tillfälligt behålla
sin gamla, begränsade klassificeringskarta under migreringen. Den publicerar
inget medlemskap förrän full signerad återspelning och atomisk migrering
lyckats. Detta är inte en ny obegränsad migrationsväg.

## Återöppning, integritet och felutfall

Öppning kontrollerar markörernas kanoniska format, nyckeltyper, storlekar,
refererade objekt och exakta räknare. Därefter jämförs medlemskapet med varje
verkligt valt manifest och block ur den fullt signerade återspelningen.
En rad som falskt markerar en väntande kandidat kan alltså inte bli auktoritet
genom att bara få korrekta summor i metadatahuvudet.

Saknade, ändrade, extra eller okända versionsmärkta indexdata stoppar öppning.
De repareras inte tyst. En äldre version utan index får sina rader först
efter verifierad originalhistorik, i samma atomiska batch som övrig eventuell
indexmigrering. Vid förlorat Sync-slutförande behålls gamla RAM-räknare och
fortsatt skrivning stoppas. Återöppning fastställer exakt gammalt eller nytt
verkligt diskutfall utan återställda identiteter eller omskrivna noncer.

Liksom andra härledda metadata autentiseras gamla markörer vid åtkomst och
fullt vid öppning; varje nytt block gör ingen fysisk genomsökning av hela
disken. Ett känt lagrat objekt som försvunnit ur både det verifierade indexet
och kandidatcachet ger lokal otillgänglighet, inte godkänd frånvaro.

## Läsningar och lås

En payload-läsning tar först en begränsad LevelDB-snapshot och släpper
storelåset. Markörläsning och rådata-I/O görs sedan utanför konsensus-, store-
och cachelåsen. Samma tidigare gräns om två payloadläsare gäller. Close
invaktar dessa läsare innan databasen stängs, och avbrott får inte publicera
payloadbytes.

Medlemskapet kontrolleras före det befintliga hotcachet. Redan cachade bytes
kan därför inte kringgå ett skadat index eller göra väntande data till valda
data. En förfrågan om en verklig väntande kandidat ger inget lokalt lagringsfel;
skada i en markör för ett valt objekt låser däremot lokal metadataotillgänglighet.

## Verifierat komponentomfång

Riktade prov använder verkligt signerade block och temporära riktiga databaser.
129 commits och återöppning bevarar exakt markerat medlemskap; RAM-katalogen
innehåller bara en uttryckligen förberedd kandidat. Ett tomt valt SDK-block
tar bort dess förlorande preparation utan att duplicera historiska markörer.

Negativa prov ändrar saknade, kompensationsräknade, felkodade, felstorleksatta
och extra markörer samt okänd version och motstridiga gamla versionsflaggor.
Kompensationsräknade falska medlemskap måste avvisas efter full återspelning.
Logiska indexbytes jämförs före och efter misslyckad öppning för att upptäcka
tyst reparation. Commit och migrering provas före faktisk Sync och efter
faktisk Sync med förlorat slutförandebesked.

En avsiktligt pausad markörläsning genom den verkliga SDK-klienten ska kunna
överlappa en ny riktig commit. Separat provas att Close dränerar en avbruten
SDK-läsning. Första nya Commit-provet jämförde felaktigt även ändringar från
den tidigare payloadförberedelsen; den underkända körningen är bevarad.
Jämförelsen ligger nu vid rätt transaktionsgräns, utan sänkta produktionskrav.

Slutliga testantal, artefakter och SDK-/UI-felprov binds separat till samma
oförändrade källversion. Ingen fysisk Linux-/Termuxkörning följer av ett
korsbygge eller lokalt Windows-prov.

## Kvarstående krav

Den historiska objektstorlekskartan i RAM är borttagen. Full återspelning,
andra öppnings-/migrationsstrukturer och klientvyer har fortfarande arbete
som växer med historiken. Native-ledgern skriver fortfarande om sitt fasta
fönster om högst 256 stateposter. Gränserna 4 095 block, 512 MiB rådata och
befintliga disk-/indexkrediter ändras inte här.

Lagrings-/retentionspolicy före borttagna ändliga gränser, lång partition,
disktryck, fysisk fel-/uthållighetsacceptans, verkligt kapacitetsmål, offentlig
ekonomi/mining/pooler/medlemskap och oberoende säkerhetsacceptans återstår.
Tidigare oförklarad tidsgräns i Go-verktygets fixturförberedelse står kvar i
granskningshistoriken. Ingen Git-push, appomstart, bootstrap eller publik
aktivering ingår i denna lokala etapp.
