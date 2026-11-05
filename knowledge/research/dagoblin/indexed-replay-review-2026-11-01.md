# DAGoblin: strömmande återöppning av indexerad historik

## Ursprunglig avsikt och fynd

En nod ska bevara sin verkliga identitet, sina ägare och sin validerade historik
vid omstart. Historiktillväxt ska kunna hanteras inom resursbudgeten. Ett lokalt
index får aldrig ersätta kontrollen av originalblock, transaktioner och signaturer.

Den tidigare återöppningen behöll hela manifestkedjan, en lista över alla
checkpoint-snapshots, ett förväntat publikt index och mängden besökta metadatanoder
i RAM. De strukturerna används fortfarande av den befintliga äldre migrerings-
vägen. Redan fullt indexerade databaser använder nu en separat strömmande väg.

## Genomförande och beviskedja

Store öppnas först med samma strikta kontroll av samtliga nycklar, kanoniska
värden, storlekar, referenser och exakta indexräknare. Återspelningen håller
storelåset medan noden ännu inte publicerats; den är ingen konkurrerande
bakgrundssynk av en redan körande ledger.

Manifestkedjan läses bakåt till exakt den väntade genesisroten. Checkpointnumret
måste minska med ett i varje steg, vilket även stoppar cykler och hopp. De
begränsade manifestposterna läggs i ett tillfälligt diskbaserat arbetsindex.
De läses sedan framåt, kontrolleras igen och används för verklig exekvering.
Varje ursprunglig payload, blocksignatur och individuell TX-signatur verifieras.
Kanoniskt manifest, noncer, saldon och slutåtagande måste stämma exakt.

Summan av råa payloadbytes kontrolleras före varje ytterligare base64-kopia.
Ett skadat manifest kan därför inte hålla 128 maximala payloadkopior i RAM.
Denna kontroll används även av den äldre migreringsvägen.

Efter varje signerad exekvering jämförs den exakta kontosnapshoten med dess
publika post. Nya ordningslöv, hashreferenser och fullständiga Merkle-delträd
kontrolleras när de skapas. Ett vänsterdelträd läses först efter att det
kontrollerats från tidigare signerade löv. Den inledande exakta nyckelräkningen,
de unika sekventiella nycklarna och slutliga bytesumman hindrar extra eller
saknade publika poster från att döljas av matchande toppvärden.

Valda manifest och payloadmarkörer jämförs under samma passage. Metadatanoder
kontrolleras mot sina verkliga lagrade bytes varje gång de nybildas. Exakt
historisk deduplicering sker i arbetsindexet på disk. En separat RAM-mängd
innehåller bara den aktuella batchens nya noder, med en explicit gräns.
Den slutliga metadataroten, antalet unika noder och deras byteantal måste
stämma. Ingen versionerad korruption repareras eller skrivs över.

## Resurser, krasch och städning

Arbetsindexet använder 1 MiB skrivbuffert, 1 MiB blockcache och högst åtta
öppna cachefiler. LevelDB kan hålla två skrivbuffertar samtidigt. Detta är
konfigurerade delbudgetar, inte ett påstående om processens totala RSS.
Arbetsindexet har dessutom egna fasta gränser för logiska bytes och antal
poster. Logisk bytegräns är inte en fysisk diskgräns under LSM-kompaktering.

Produktionsvägen har en enda reserverad arbetskatalog per nodprofil. Den
innehåller en publik ägarmarkör och tillfälliga manifest-/besöksmarkörer,
aldrig privata nycklar. Efter en processkrasch kan samma profils övergivna
arbetsdata kastas innan en ny full återspelning startar. Den kan inte bli
exekveringsauktoritet eller skapa allt fler kataloger vid upprepade omstarter.

En levande arbetsdatabas skyddas av sitt verkliga OS-fillås. Städningen av
övergiven arbetsdata kräver den reserverade absoluta sökvägen, rätt ägarmarkör,
vanliga kataloger och ett tillgängligt fillås. Okända kataloginnehåll och
länkar avvisas. En avbruten tom katalog eller ensam delvis skriven första
ägarmarkör kan tas bort med exakta icke-rekursiva operationer. Kanoniska
databasens innehåll skrivs inte av denna återspelningsväg.

Läs-, skriv-, kvot-, lås- eller städningsfel stoppar öppning. Den skrivbara
prefixen publiceras först när hela kontrollen och städningen lyckats. Noden
kan inte rapportera en färdig återhämtning om arbetsdata inte kunde avslutas.

## Verifiering och praktiska gränser

Den tidigare fulla återspelningen och hela förväntade indexet finns kvar som
oberoende referens i proven. Verkligt signerade prefix jämförs vid genesis,
ett block och längre historik. Konton, noncer, ordning, metadata, åtaganden,
efterföljande commit och oförändrade kanoniska databasrader måste matcha.

Felprov avbryter arbetslagringens skapande, skrivning, läsning, deduplicering
och stängning. Andra prov ändrar giltigt kodade ordningsposter, delträd och
äldre kontosnapshots med kompenserade byteantal. Sådana index måste avvisas
efter signerad återspelning även när den syntaktiska förkontrollen godkänt dem.

Ett större separat arbetsmängdsprov använder publika hashmarkörer, driver
LevelDB förbi skrivbufferten till verkliga tabellfiler och kontrollerar exakt
återläsning samt en RAM-budget. Markörerna är inte transaktioner. Observerad
Go-heapförändring påverkas av GC och är ingen mätning av fysisk nätkapacitet.
Slutliga native-, SDK-, WASM- och UI-resultat binds separat till samma källor.

Den äldre migreringsvägen behåller sin tidigare atomiska Sync och sina
begränsade historikstrukturer. Detta gör inte all äldre migrering minnesoberoende.
Gränserna 4 095 block, 512 MiB payload, kontoantal, allokering och konsensus-
medlemskap består. Större eller obegränsad historik, uthållig målkapacitet,
fysiska felprov och publik ekonomisk modell är fortfarande egna återstående krav.

## Primärkällor

Budgetarna och fillåset har kontrollerats mot den faktiskt pinnade lokala
GoLevelDB-koden. Publika referenser finns i projektets
[options.go](https://github.com/syndtr/goleveldb/blob/master/leveldb/opt/options.go)
och [file_storage.go](https://github.com/syndtr/goleveldb/blob/master/leveldb/storage/file_storage.go).
Go dokumenterar separat [MkdirTemp och städningsansvar](https://pkg.go.dev/os#MkdirTemp).
Dokumentationens allmänna API-kontrakt ersätter inte egna krasch-, integritets-
och resursprov mot den pinnade implementationen.
