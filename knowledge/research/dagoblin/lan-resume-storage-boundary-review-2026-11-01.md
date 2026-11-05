# DAGoblin: återupptagen LAN-hämtning och historikens lagringsgräns

## Ursprunglig avsikt

Långsamma och tillfälligt frånkopplade noder ska kunna återhämta verkliga data
i sin egen takt. CLI och Desktop får visa antagna block och validerade TX
först när informationskällan verkligen har kontrollerat dem. Delvis mottagna
bytes är varken historik, ett kontosaldo eller finalitet.

## Fynd och beslut

SDK-payloadhämtningen kunde redan fortsätta från en sparad offset. Vanlig
autentiserad LAN-GET tappade däremot sina fragment vid anslutningsavbrott.
Den använder nu ett separat begränsat cache för overifierade prefix på disk.
Blockformat, ägare, TX-signaturer, noncer, certifikat och antagningsregler ändras
inte. Inga nya nycklar eller ersättningstransaktioner skapas vid omsändning.

Den större lagringsgränsen löser inte sig själv genom lägre RAM-användning.
Ett faktiskt uppmätt block med 5 000 TX är 2 464 461 råa bytes. Med lika stora
block skulle 512 MiB rymma 217 block, cirka 1,09 sekunder vid arbetsmålet
200 block/s. Detta är planeringsaritmetik, inte uppnådd nätkapacitet.
Kopior, base64, index och lagringsförstärkning tillkommer.

## Protokoll och tillitsgräns

Första GET behåller sitt vanliga format. Om ett verkligt prefix finns kan en
senare begäran ange hash, totalstorlek, wire-SHA och nästa offset. Varje
anslutning autentiseras på nytt. Servern jämför beskrivningen med sina verkliga
bytes och börjar annars om från noll. Fragment måste följa exakt ordning,
storlek och blockidentitet. Endast fullständiga fragmentpositioner eller
exakt slutposition får återupptas.

Mottagaren läser och hashkontrollerar de faktiskt lagrade bytesen på nytt.
Den kräver dessutom ett korrekt autentiserat yttre END och stänger socketen
innan den vanliga resursstyrda block-/TX-kontrollen körs. Ett fullständigt
prefix efter ett felaktigt END får därför inte publiceras. En senare korrekt
anslutning kan bekräfta slutpositionen utan att skicka samma payload igen.

En verifierad wire-hash ersätter aldrig signatur- eller exekveringskontrollen.
Nya data går genom oförändrad antagning. Exakt redan antagna bytes kan som
tidigare identifieras som dubblett utan att räknas som nya validerade TX.
Kända signatur-/hashfel kastar det berörda cacheobjektet. Tillfälligt saknade
föräldrar eller lokalt resursstopp gör inte prefixet till antagen historik.

Äldre peers kan avvisa ett nytt resume-fält. Om den autentiserade anslutningen
stängs före något svar på en sådan begäran utelämnas fältet vid nästa begäran.
Det är en kostnads-/kompatibilitetsfallback, ingen säkerhetsnedgradering och
inget bevis om motpartens version. Ingen obegränsad automatisk retry införs.

## Resurser, samtidighet och stopp

Varje peer har högst åtta prefix och 64 MiB deklarerad diskkredit. Två
LAN-peers ger högst sexton prefix och 128 MiB för detta cache. Det är en
delbudget; SDK-hämtning, journal, native-lagring och process-RAM har egna
budgetar. Tillfälliga filer innehåller offentliga blockbytes, aldrig signers.
De är inte en del av den beständiga profilen eller dess validerade journal.

En peer får inte ta en annan peers reserverade utrymme. Egen inaktiv cache
kan kastas inom budgeten. Varje peer har ett eget avbrytbart requestlån.
Läsning, skrivning och stängning håller inte det gemensamma cachelåset.
Utgångskontrollen körs i den befintliga peer-lanen och gäller dess egna filer;
en långsam stängning ska inte bli en annan peers diskoperation.

Diskkrediten behålls tills det verkliga filhandtaget har stängts. Misslyckad
stängning behåller posten och kreditredovisningen, visar lokalt I/O-fel och
stoppar nya cacheallokeringar tills säker städning kan slutföras. Lokala
spoolfel registreras inte som bevis mot en korrekt remote peer.

Samma bekräftade stängningsordning gäller nu den tidigare SDK-spoolen. Den
samlade körningen fångade att dess rad och kredit tidigare togs bort före
filstängningen. Raden behålls nu under stängning och kvarvarande handtag
återförs till säker cleanup vid stopp. Deterministiska prov blockerar eller
underkänner stängningen. Det tidigare expiry-provet fångar dessutom prefix
och filhandtag atomiskt under workerlåset. Dess idle- och väntetidsgränser
är oförändrade. Den underkända samlade körningen bevaras separat.
Ett rapporterat close-fel kan också inträffa efter bekräftad stängning.
Då får krediten släppas men den lokala felstatusen består. Ett öppet eller
okänt handtag behålls däremot och ger inte återanvänd kredit. Båda fallen provas
med filobjektets normala closed-kontrakt, utan att dölja ett cleanup-fel.

Idle-prefix kan löpa ut efter 30 sekunder när den egna underhållslanen körs.
Aktiva requestlån skyddar filen från utgång. Stopp inväntar befintliga arbetare
innan cachefiler stängs. Detta inför ingen ny bakgrundstråd. De tidigare
nätverkstidsgränserna och fullnodens verifieringsomfång består.

## Verifierat komponentomfång

Riktade prov använder riktig TCP, autentiserade frames, individuellt signerade
TX och disponibla krypterade nodprofiler. Ett 5 000-TX-block bryts mitt i
överföringen och fortsätter vid nästa sparade fragment med ny autentisering.
Felaktigt END, ändrade spoolbytes, ändrad beskrivning, äldre peer, kort lokal
skrivning och stopp får inte ge för tidig journalpost eller falska TX-räknare.
En korrekt wire-hash och giltig yttre blocksignatur med felaktig inre
TX-signatur ska fortfarande avvisas.

Samtidighetsprov håller lokal skrivning och stängning öppna medan den andra
peer-lanen fortsätter. De kontrollerar även expiry/lån, separat diskkredit,
misslyckad stängning och bevarad kredit tills cleanup faktiskt lyckats.

Ett separat prov använder fyra verkliga SDK-validatorprocesser och tre
nodprofiler på samma Windowsvärd. Payloadhämtningen till replikan hålls
tillfälligt tillbaka medan de riktiga certifikaten produceras. Sedan bryts
LAN-GET efter två fragment, fortsätter vid byte 65 536 och följs av riktig
signatur-/exekveringskontroll mot SDK-certifierade konto- och ordningsrötter.
Profilerna återöppnas och kontrolleras igen. Det är inte fyra fysiska värdar
eller oberoende operatörer.

Första fyrnodsprovet föll på en observationskontroll som räknade även parallell
bevistrafik. Den körningen är bevarad och omklassas inte till godkänd. Den
korrigerade observationen avgränsar de manuella GET-anslutningarna och deras
autentiserade servertrådar. Nätverks-, krypto- och väntetidskraven sänktes inte.
Slutliga samlade resultat binds separat till den oförändrade källversionen.

## Historikpolicy: primärkällor och återstående arbete

CometBFT:s state sync kräver applikationsstöd och light-client-förankring med
betrodd höjd/hash och trust period. Det är en annan startväg än att själv
återspela varje originalblock. [CometBFT v0.40.0](https://raw.githubusercontent.com/cometbft/cometbft/v0.40.0/docs/core/state-sync.md).

Bitcoin Cores Assumeutxo skiljer snapshotens antagna historik från den
bakgrundsvalidering som senare kontrollerar det tidigare tillståndet. Det
kräver separata chainstates och tydliga övergångar, inte bara en sparad
kontolista. [Assumeutxo-design](https://raw.githubusercontent.com/bitcoin/bitcoin/master/doc/design/assumeutxo.md).

EIP-4444 är ett utkast som kopplar borttagning av äldre data till en uttrycklig
checkpoint-/weak-subjectivity-modell och annan åtkomst till historik.
Det är inget fristående bevis för att valfri DAG-payload säkert kan kastas.
[EIP-4444](https://eips.ethereum.org/EIPS/eip-4444).

Egen slutsats: GG behöver en versionsbunden arkiv-/retentions- och bootstrap-
policy som bevarar ägare, noncer, valda rötter och tydliga verifieringsomfång.
Nuvarande fulla genesisåterspelning behålls; pruning eller snapshot-tillit
aktiveras inte av denna transportändring. Gränserna 4 095 block/512 MiB består.
Uthållig målkapacitet, lång partition, full disk, fysisk acceptans, publik
ekonomisk modell och oberoende säkerhetsacceptans är fortfarande återstående krav.
