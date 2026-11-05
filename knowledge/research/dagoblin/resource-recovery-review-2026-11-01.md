# DAGoblin: begränsat minne och återupptagbar dataåterhämtning

## Ursprunglig avsikt

Riktiga signerade block och transaktioner ska ligga bakom CLI och Desktop.
En långsam replika ska kunna arbeta i sin takt. Ofullständiga data får inte
bli ett block i journalen, ett verifierat saldo eller lokal finalitet.
Blockets signerande producent är fortfarande dess enda kryptografiska
skapare, även när någon annan nod levererar eller verifierar dess bytes.

## Konstaterade fel

Det isolerade fyrnodsprovet med 50 000 TX nådde SDK-certifiering efter tidigare
minnesändringar, men full återhämtning fastnade. SDK-arbetaren kastade alla
delvis hämtade bytes när åttasekundersjobbet tog slut. Även valideringen av
färdig data ärvde den nästan förbrukade hämtningstiden.

LAN-återhämtningen begränsade dessutom hela en stor GET till samma åtta
sekunder, trots att transporten redan har en separat ändlig bulkgräns.
I ett ägt loopbackprov tog en verklig 50 000-TX-överföring cirka tolv sekunder
att ta emot och ytterligare tio sekunder att validera. Åttasekundersförsöket
avbröts under mottagningen utan att någon transaktion hade publicerats.
Detta är mätningar på en dator, inte fysisk nätkapacitet eller målhastighet.

En separat SDK-genomgång visade att varje peer/kanal behöll kapaciteten hos
sitt största mottagna meddelande. Kanonisk jämförelse, blockhash och
signaturmeddelande skapade också extra fullständiga kopior av stora JSON-data.

## Beslut och genomförande

- Tillfälliga, obetrodda SDK-bytes sparas mellan nätarbetspassen i ägda
  temporärfiler. Högst åtta poster och 64 MiB deklarerad temporär kredit får
  finnas samtidigt. Trettio sekunder utan framsteg frigör en övergiven post.
  Filerna är inte en nodjournal och stängs vid stopp, fel eller färdig behandling.
- Varje nytt pass verifierar referenscertifikatet och hela den valda ordningen.
  Deldata binds till nätets ankare, blockidentitet, index, exakt storlek och
  wire-digest. Ett nytt giltigt suffix behöver inte starta om en äldre hämtning.
- Den verkliga temporärfilens färdiga bytes hashas på nytt. Därefter krävs
  samma fulla block-/TX-signaturer, föräldrar, noncer, saldon och atomiska
  beständiga antagning som tidigare. Åtta sekunder är en nätarbetsskiva;
  den fullständiga, storleksbegränsade valideringen har separat CPU-/RAM-
  styrning och täta avbrottskontroller. Den skapar ingen finalitet på egen hand.
- Ändrad eller skadad källa återställs eller lämnas för en annan källa.
  Lokal diskbrist anklagar inte en giltig producent. Ett stängningsfel stoppar
  återhämtningen synligt och återstående resurser städas fortfarande.
- En stor autentiserad LAN-GET får hålla högst 32 MiB färdiga poster med
  levande minnesreservationer. Korrekt END krävs, socketen stängs, och full
  validering sker sedan utanför nätets tidsgräns. PAGE och små förfrågningar
  behåller sin tidigare antagnings-/kvitteringsordning. Återhämtningen använder
  den befintliga bulktransportens gräns i stället för schemaläggarens åtta sekunder.
- Bara mottagningsbuffertar över 256 KiB lämnas tillbaka efter ett färdigt
  SDK-meddelande. Vanliga cirka 64 KiB konsensusdelar återanvänder sina små
  buffertar. Meddelandets bytes och maximala tillåtna storlek ändras inte.
- Standardbibliotekets kanoniska JSON-bytes jämförs eller hashas utan en extra
  utmatningskopia. Signaturmeddelandet behåller exakt samma domän och bytes.
  Kryptografiska meddelande-/signaturbeslut cachas inte genom denna ändring.
- CLI/UI skiljer verkliga obetrodda hämtningsbytes och pågående validering från
  färdiga verifierade block. Samtidig vanlig LAN-antagning får inte räknas en
  gång till som ett nytt SDK-återhämtat block.

Stark innehållsidentitet behövs när delar återanvänds efter ett avbrott;
HTTP:s If-Range-princip är en relevant jämförelse, inte ett påstående att
GG använder HTTP Range för LAN-protokollet.
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-if-range).
Temporärfilernas livscykel använder standardbibliotekets etablerade hantering.
[Python tempfile](https://docs.python.org/3.13/library/tempfile.html).

## Verifierad evidens och återstående gränser

Den isolerade prototypen passerade hela 50 000-TX-kedjan med fyra riktiga
SDK-barnprocesser: undanhållen källa och skadade svar, exakt återhämtning via
annan ägare till replika, korrekt signerande ägare i CLI-data samt återöppning
av alla tre nod- och fyra validatorprofiler med samma tillstånd och identitet.
Det var en längre diagnostisk körning. Den ersätter inte det ursprungliga
90-sekundersprovet eller ett fysiskt treenhetsprov.

Riktade regressioner använder verkliga signerade data och provar bland annat
fortsatta offset, nytt giltigt certifikatsuffix, ändrad källa/temporärfil,
felaktig TX-signatur under korrekt blocksignatur och wire-digest, disk-/RAM-
kredit, källbyte, avbrott under riktig motor-/resurskontroll och atomisk
publicering. Ett verkligt stort GET-prov verifierar separat mottagning och
validering; ogiltigt END och för stor kö får inte publicera data.

SDK-ändringarnas exakta original, resultat och hela härledda modul verifieras.
Originalets modulcache och projektets go.mod/go.sum lämnas oförändrade.
Ett särskilt Go-prov körs mot den verkliga härledda SDK-kanalen och kontrollerar
både storbuffertens frigöring och återanvändning av vanliga konsensusdelar.

Slutliga bygg- och regressionskvitton binds till de ordinarie källorna efter
sammanförandet. Uthålligt kapacitetsmål, historik-/diskpolicy, fysisk fel- och
uthållighetsacceptans, offentligt medlemskap, monetär modell, mining/pooler och
oberoende säkerhetsacceptans är separata kvarstående krav. Ingen huvudnäts-
beredskap eller absolut säkerhet följer av dessa prov.
