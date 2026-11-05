# DAGoblin: atomisk import av verifierad offentlig DAG-historik

Datum: 2026-11-01. Pågående verifiering; hela nätleveransen är inte färdig.

## Ursprunglig avsikt

En redan parad replikas CLI och Desktop ska kunna återläsa verkliga block,
skapare, transaktioner, konton och certifierad ordning från samma beständiga
källa. Importen måste bevara identiteten och hela den verifierade historiken.

## Utförande

`lan.archive_import profile=... path=...` använder en stoppad, redan
sessionsbunden replikaprofil med tom inträdesjournal. Den vanliga exklusiva
profil-leasen hindrar samtidig användning av samma profil i CLI eller Desktop.
Producent- och lättklientroller följer sina egna återställningsvägar.

Den installerade native-verifieraren återspelar först originalarkivet med
samtliga DAG-signaturer mot profilens redan signerade nätverksbindning och
sparade certifikatgräns. Därefter strömmas filen genom en separat nyckellös
Python-motor. Varje block och TX verifieras igen; originalens skapare,
föräldrar, sekvenser och noncer består. Avkodade TX-objekt och råa block
behålls inte som en växande RAM-kopia av hela historiken.
Samma kooperativa minnesreservation som vid LAN-admission tas före varje
rå payloadläsning och omsluter dess Python-avkodning och SQL-skrivning.
Saknad minnesmätning och otillräcklig lokal marginal ger
inget godkänt importresultat. Native-jobbet har sin separata processbudget.

En enda SQLite-transaktion skriver samtliga inträden, den verifierade ordningen,
certifikatgränsen och profilens signerade integritetshuvud. Fullständigt EOF,
footer och exakt filhash jämförs med native-resultatet före commit. Ändrade
data mellan de två läspassen får därmed inget publicerat importresultat.
Äldre observerad certifierad ordning måste vara ett exakt prefix av importen.

Vid diskfel, avbrott eller osäker commitkvittens blir det öppna handtaget
felmarkerat. Återöppning måste bevisa antingen det gamla tomma tillståndet
eller hela den nya signerade journalen. Det finns inget godkänt delprefix.

## Omfång

Importen startar ingen produktion. Profilens befintliga krypterade identitet
behålls. SDK-validatorns signeringstillstånd och blockstore återskapas inte;
den separata native-ledgerns finansiella transferhistorik återspelas inte av
denna DAG-import. Detta anges också i det maskinläsbara resultatet.

Den befintliga ändliga genesispolicyn med 4 095 DAG-block och 512 MiB rå
historik består. Fortsatt historiktillväxt behöver en separat versionerad
policy och separat verifiering. Inget publikt nät aktiveras av importkommandot.
