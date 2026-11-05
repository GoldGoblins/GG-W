# DAGoblin: SDK-historik på disk och inkrementell ordningsrot

## Ursprunglig avsikt

Långsamma noder ska kunna återhämta riktiga block utan att stoppa snabbare
producenter. Historik, ensam skapare, konton och nonces ska vara verifierbara
även efter omstart. Den här etappen tar bort SDK-motorns dubbla RAM-historik
och en upprepad rotberäkning. Den uppfyller ännu inte hela leveranskontraktet.

## Fynd och beslut

Efter full transaktionsverifiering sparade SDK-motorn både de avkodade
transaktionerna och rådata i varje historisk RAM-post. Samma signerade rådata
fanns redan beständigt under innehållsadresserade poster i LevelDB.

Motorn behåller nu endast verifierad metadata i färdigcommittad historik.
Avkodade transaktionsobjekt släpps efter admission; aktuell förberedd rådata
finns kvar tills synkron commit lyckats. En ny immutable exekveringsvy med
arkivläsare publiceras först därefter. Den äldre vyn ändras aldrig på plats.

Vid återöppning verifieras fortfarande samtliga ursprungliga block och
transaktionssignaturer. Varje verifierad batch komprimeras i RAM före nästa
batch. Ingen snabb återställning från en obestyrkt kontosnapshot införs.
Databasschema, ursprungliga rådataposter och deras historiska digest ändras inte.

## Rådata och lås

En chunkförfrågan binds först till verklig committad blockidentitet, index,
höjd och kontorot. Förberedda, ocommittade förslag får inte använda arkivet
som en genväg till committad medlemskap. Även lagringsläsaren kräver att
rådatans digest och storlek finns i den verifierade mängden committade objekt.

Själva diskhämtningen sker efter att appens och lagringens lås släppts.
En fryst databasvy håller rätt data tillgängliga medan en ny commit eller
rensning av ocommittad cache sker. Högst två rådatahämtningar tillåts samtidigt.
Close väntar in läsarna och släpper cache och databasvyer.

Den använda LevelDB-versionens källkod och läskontrakt har granskats lokalt
och mot samma officiella revision. Databasvyn frisläpps uttryckligen. Cachen
får en egen buffertkopia innan den släpps; den förlitar sig inte på ett dolt
ägandekontrakt för bibliotekets läsbuffert.
[Databas-API](https://github.com/syndtr/goleveldb/blob/2ae1ddf74ef7020251ff1ff0fe8daac21a157761/leveldb/db.go),
[snapshot och läsning](https://github.com/syndtr/goleveldb/blob/2ae1ddf74ef7020251ff1ff0fe8daac21a157761/leveldb/db_snapshot.go).

Varje cachefyllning verifierar hela rådatans storlek och SHA-256 mot den
tidigare fullt verifierade posten. Cachen är högst 32 MiB och två block.
Läsning av följande 32-KiB-chunkar kan sedan använda samma verifierade buffert.
Det är en cachegräns, inte en garanti om hela processens residenta minne:
två samtidiga missar, bibliotekets läsbuffertar, kontrollerade kopior,
CometBFT och aktuell transaktionsverifiering har också minneskostnader.

Skadad eller saknad rådata vid en cachemiss ger fel. Giltig ursprunglig rådata
som redan finns i cache kan fortfarande levereras. Återöppning verifierar
originaljournalen och får inte reparera eller hoppa över skadad historik.
Avbrott kontrolleras före och efter diskoperationen; ett hängande systemanrop
har inte fått en påhittad hård tidsgräns.

## Identiska Merkle-rötter

En värdekopierad appendstruktur bygger nu samma ordningsrot som tidigare,
inklusive samma domänseparation och dubblering av en udda sista gren.
Systerförslag delar ingen muterbar appendstruktur. Inget rotformat eller
offentligt bevis har ändrats. Frontiern sparas inte som en betrodd snapshot;
den byggs om genom full protokollåterspelning.

Seal behöver inte längre räkna om hela ordningsträdet. Lagringens oberoende
kontroll av hela orderlistan kvarstår, så en ändrad lista eller frontier kan
inte godkännas enbart med hjälp av en cachad rot. Detta är inte ett påstående
om att hela commit- eller bevisflödet nu kostar konstant tid.

## Verifiering och begränsningar

Testerna jämför ordningsroten mot den gamla fulla beräkningen vid **varje
prefix från 0 till 4 095 block**, samt oberoende systergrenar. Beständiga prov
återöppnar 35 000 verkligt signerade transaktioner med samma rötter och
fortsätter utan nonceåteranvändning. Två verkliga 50 000-TX-block passerar
cachegränsen för byte och ger totalt 100 000 verifierade transaktioner.

Ett separat prov går genom den riktiga SDK-klientfabriken, pausar en kall
diskläsning och committar samtidigt ett nytt faktiskt transaktionsblock.
Andra fall provar kandidatisolering, skadad/saknad rådata, läsarkvoter,
avbrott, Close, historisk pinning och att förberedd rådata behålls före commit.
De slutliga testantalen, byggkvittot och processresultaten registreras i
etappens privata verifieringskvitto. Windows-proven är lokala; kompilerade
Linux/Android-mål ersätter ingen fysisk körning på de enheterna.

Gränserna **4 095 DAG-block och 512 MiB historisk rådata kvarstår**. Metadata-
kartor och orderlistor kopieras fortfarande, och offentliga historikbevis
läser och kontrollerar hela den ändliga ordningen. Detta måste ändras innan
obegränsad eller långvarigt hög skalning kan godkännas. Ingen committad
historik har beskurits eller ersatts med ett osäkert tillståndsantagande.

Maximal nätåterhämtning, längre partitioner, fysisk fel-/uthållighetsacceptans,
kapacitetsmålet, offentligt medlemskap, monetära regler, mining/pooler och
oberoende säkerhetsacceptans återstår. Ingen Git-push, appomstart,
enhetsuppdatering eller publik nätaktivering görs genom denna lokala etapp.
