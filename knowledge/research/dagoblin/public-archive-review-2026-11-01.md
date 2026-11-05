# DAGoblin: portabelt arkiv för originalens signerade DAG-historik

## Ursprunglig avsikt

Historik ska kunna behållas och återhämtas med begränsat arbetsminne utan att
förlora ägare, noncer, valda rötter eller verifiering. Ett arkiv ersätter inte
konsensus, en privat nyckelbackup eller en definierad policy för fortsatt tillväxt.

## Implementerad komponent

Native-kommandona `archive-export` och `archive-verify` arbetar med offentliga
data. Anroparen lämnar en separat pinnad native genesis och vid behov sin
beständiga certifikathöjd/blockidentitet. Filens egen header får inte välja
tillitsrot eller sänka den lokala certifikatgränsen.

Export öppnar en redan indexerad offentlig DAG-databas skrivskyddat med
LevelDB:s riktiga filspärr. En aktiv skrivare ska blockera exporten. Utdata och
arbetslager måste ligga utanför källprofilen. Export skapar en ny fil exklusivt
och skriver aldrig över en befintlig fil. En avbruten fil är inte ett godkänt
arkiv. Filen synkroniseras och stängs innan kommandot rapporterar framgång.

Arkivet har magiska bytes, en storleksbegränsad SDK-certifikatheader och sedan
den exakt valda checkpointkedjan med originalens signerade blockbytes. Varje
checkpoint har högst 128 block och 32 MiB rå payload enligt den befintliga
policyn. Manifestens wire-hashar, källbindning, tid, föregångare och sekvens
kontrolleras. Det räcker inte att blockkroppar ser likadana ut.

Databasen och det portabla arkivet använder samma funktion för full signerad
manifeståterspelning. Alla block-/TX-signaturer, parent-/producentregler,
noncer och belopp exekveras på nytt. Slutligt konto-, ordnings- och
manifeståtagande måste vara exakt samma som i det pinnade SDK-certifikatet.

Endast avkodade, verifierade SDK-headerfält kopieras till exporten. Godtyckliga
okända tillägg i en indataheaders råa JSON följer inte med. Kommandot läser
inga signerfrön, nyckelvalv eller privata validatorfiler.

En footer kontrollerar faktiska föregående bytes och verkliga räknare. Den är
inte en tillitsrot; en angripares omräknade footer kan inte ersätta signaturer
eller SDK:s valda rötter. Resultatet innehåller både innehållssumman före
footern och SHA-256 för samtliga faktiska arkivbytes inklusive footern.
Trunkering, fel fragmenttyp/storlek och data efter sista footer avvisas.

Granskningen fångade dessutom en typallokeringsrisk i den tidigare native
JSON-vägen: en stor lista med tomma TX-objekt kunde allokeras före den
befintliga antalskontrollen. DAG-block och batcher begränsar nu liststorlek
och objektfält i den befintliga strömmande namnkontrollen före typavkodning.
Gränserna följer redan tillåtna TX-/batchstorlekar; generella läsarens tidigare
regler består. Negativa prov använder flera miljoner element inom den råa
bytegränsen och kontrollerar verklig allokering, inte bara sista felkoden.

Desktop och CLI förkontrollerar också den fasta kanoniska LAN TX-v2-strukturen
före `json.loads`. Den kontrollen använder en begränsad stack utan att skapa
TX-listor eller kopiera strängtoken. Den tillåter protokollets föräldra- och
TX-listor men avvisar överdrivet antal element, objekt, fält och nästling.
Den äldre manuella TX-v1-modellens vittnesstrukturer berörs inte. Ordinarie
JSON-, kanoniserings-, domän- och samtliga signaturkontroller körs därefter.
Proven går genom riktiga LAN-inträden och kontrollerar att avkodaren inte
anropas för minnesförstärkande former; giltiga signerade block provas separat.

## Arbetslager och fel

Verifiering behåller inte alla råa block eller ett växande historikträd i RAM.
Tidigare autentiserade historiknoder läses från ett disponibelt LevelDB-lager
med begränsade nod-, byte-, write-buffer- och cachebudgetar. Varje kommando
använder ett arbetslager under en uttryckligen angiven lokal arbetsrot.

En separat riktig OS-lease tas innan arbetskatalogen kan skapas eller städas.
Det hindrar samtidiga arkivjobb från att kasta varandras pågående data.
Övergivet känt arbetsmaterial kan återtas efter krasch; okända filer, länkar
eller ägarmarkörer ska avvisas. Arbetsmaterial är aldrig beständig auktoritet.

Arkivfel får inte ändra källdatabasens kanoniska innehåll eller publicera en
färdig återspelning. Misslyckad läsning, skrivning, stängning eller städning ger
inget verifierat resultat. Originalets databas och befintliga utdata bevaras.

## Verifieringsomfång och återstående integration

Riktade prov använder riktiga signerade testblock och SDK-giltiga
certifikatfixturer. De kontrollerar ursprungliga rötter, verkliga TX-räknare,
filhash, tom genesis, omräknade footer/manifester, payload-/ordningsfel,
trunkering, gammalt certifikat, konflikter på samma höjd, skrivfel, avbrott,
konkurrerande arbetslager och återtagning av känt övergivet material.

Arkivverifieringen återspelar hela DAG-delen. Den återspelar inte den separata
native-ledgerns finansiella transferhistorik och återställer inte en BFT-nods
fullständiga SDK-blockstore. Inga nya certifikat eller privata identiteter
skapas av arkivkommandona. Ett korrekt äldre arkiv är inte automatiskt den
senaste nätverksvyn; bootstrap måste använda sin pinnade certifikatgräns.

Den befintliga ändliga policyn, 4 095 block och 512 MiB rå historik, består.
Denna komponent är under pågående samlad verifiering. Bootstrapintegration,
arkivpolicy för fortsatt tillväxt, fysisk acceptans, uthållig mållast och de
övriga slutkraven återstår. Inget publikt nät aktiveras av arkivformatet.
