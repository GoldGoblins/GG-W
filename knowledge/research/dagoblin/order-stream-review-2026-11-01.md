# DAGoblin: strömmande ordningskontroll före beständig förberedelse

## Ursprunglig avsikt

Minska historikens tillfälliga minneskostnad utan att acceptera andra block,
hoppa över kontroller eller höja dagens ändliga historik- och diskgränser.

## Fynd och ändring

Förberedelse av en redan exekverad kandidat byggde tidigare en full lövlista
och alla nivåer i Merkle-trädet för att kontrollera dess ordningsrot. Kontroll
av att en vald kandidats prefix överensstämmer med föregående val gjorde
samma materialisering igen.

Dessa två kontroller läser nu de autentiserade historiklöven i ordning och
bygger den befintliga append-frontiern med högst 64 toppar. Varje begärt löv
kontrolleras fortfarande: sammanhängande index, exakt indexnyckel och exakt
antal. Saknad eller ändrad diskmetadata ger fel. En komplett kontroll avvisar
även extra löv. Prefixet måste ha samma rot som det föregående verifierade
valet. Ägande, payload, signaturer, konton och den synkrona beständiga
förberedelsen behåller sina separata kontroller.

Ingen gammal kontrollrot återanvänds som bevis för nytt innehåll. Protokoll,
hashdomäner, udda-nod-dubblering, signerade bytes och certifikat ändras inte.
En skrivskyddad bevisvy får fortfarande inte förberedas som exekverad kandidat.

## Verifierat komponentomfång

En separat referens behåller den tidigare fulla läsningen och Merkle-
beräkningen. Den nya kontrollen jämförs också med en oberoende ägd lövlista
för varje prefix till 129 och vid större gränser genom 4 095 löv. Felprov
omfattar saknat löv, extra löv, omnumrering, fel indexnyckel, saknad och ändrad
disknod, ogiltigt prefix och avbruten besöksfunktion. Historikens rot får
inte ändras under läsningen.

I ett isolerat allokeringsprov med 4 095 löv gav den tidigare vägen 4 133 312
allokerade byte och strömvägen 3 898 656 byte. Detta mäter total allokering
för just kontrollanropet, inte topp-RAM, fysisk I/O eller nätkapacitet.
Samlad regression, färska artefakter och faktiska SDK-/UI-felprov binds i
etappens separata verifieringskvitto.

## Kvarstående krav

Arbetet är fortfarande linjärt i det kontrollerade prefixet. Commit-vägen,
vissa klientvägar och startup/migrering materialiserar fortfarande full
ordning eller metadata. Full signerad payload återspelas vid öppning. Detta
är därför inte lösningen på obegränsad historik eller målet 5 000 TX/block
vid hundratals block/s.

4 095-blocksgränsen, 512 MiB-gränsen, offentlig ekonomisk modell, mining,
pooler, medlemskap, fysisk partition-/disktrycks-/uthållighetsacceptans och
oberoende säkerhetsacceptans kvarstår. Ingen Git-push, appomstart, fysisk
uppdatering eller publik aktivering ingår i denna lokala etapp.
