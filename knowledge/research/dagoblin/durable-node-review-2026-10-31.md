# Beständig nodidentitet och historik

Datum: 2026-10-31. Omfattning: explicit vald privat LAN-profil, lokala
testprocesser och programgränssnitt. Ingen fysisk enhet har uppdaterats eller
startats om under arbetet. Detta inför inte kanonisk DAG-finalitet eller pengar.

## Ursprunglig avsikt

Samma nod ska behålla sin identitet och sin verifierade historik efter återstart.
En långsam eller frånkopplad nod ska kunna återhämta sig utan att de andra
producenterna behöver vänta. CLI äger tillståndet; Desktop återger samma källa.

## Fakta och fynd

Det tidigare LAN-läget hade endast nycklar och historik i RAM. En omstart krävde
ny parning. En mottagen PAGE kunde dessutom flytta hämtningspositionen förbi
ett block vars föräldrar ännu saknades. Den positionen får inte lagras som om
blocket vore verifierat.

En bestående nätverksidentitet innebär också att gamla signerade testplaner kan
dyka upp efter återstart. Tidigare förbrukade planer måste därför förbli
förbrukade även när RAM-tillståndet försvinner.

## Beslut och implementation

- `lan.start profile=MittNodnamn` skapar en ny explicit profil.
  `lan.resume profile=MittNodnamn` öppnar samma profil. Ett befintligt namn
  skrivs aldrig över och saknad eller skadad lagring återställs inte tyst.
- Profilen lagrar transportidentitet, två egna producentnycklar, signerad roster,
  verifierade DAG-förslag, eventuella äldre testtokenkvitton, hämtningspositioner,
  förbrukade testplaner och ett låst protokollfel. Finansiella walletnycklar
  ingår inte.
- Windows skyddar privata nyckelbytes med aktuell användares DPAPI. POSIX
  använder den befintliga explicita scrypt/AES-GCM-kontexten med dolt
  terminalinmatat lösenord. Lösenord ingår inte i argument, status eller filer.
- Ett kernel-lås och en exklusiv SQLite-anslutning begränsar profilen till en
  ägande process. Låsen hålls tills nodens egna arbetare har stannat.
- Varje ny godkänd post och dess signerade integritetshuvud skrivs i samma
  SQLite-transaktion före publicering i RAM/gossip. `synchronous=EXTRA`
  verifieras vid öppning. Vid okänt skrivutfall stoppas fortsatt egen produktion
  tills lagrad historik har återlästs.
- Återläsningen kontrollerar både lagringsintegriteten och varje posts vanliga
  protokollregler innan lyssnare, gossip eller producentnycklar aktiveras.
  Konton och nästa sekvens härleds ur samma godkända poster; gamla mättider
  blir inte ny trafik eller ny produktion.
- En PAGE måste vara sammanhängande från begärd position. Endast verifierad
  och lagrad sammanhängande prefixhistorik får flytta återhämtningspunkten.
  Föräldralösa block kvitteras inte bort. Positionen sparas efter ett giltigt
  autentiserat END.
- Återstart återupptar ingen gammal produktion eller testplan automatiskt.
  Ett nytt ändligt eget jobb kräver uttryckligt lokalt startkommando.
- CLI-status och Desktop visar om källan använder beständig profil eller RAM.
  Desktopobservationen är fortsatt läsande och äger inga CLI-signernycklar.

Lagringen följer programmets befintliga ändliga LAB-gränser: högst 4 095
DAG-poster, 4 096 äldre kvitton och 512 MiB rå journaldata. Detta är inte en
obegränsad produktionsdatabas, pruning eller checkpointbaserad fast sync.

Valet av atomisk journal, synkronisering och exklusiv ägare bygger på
[SQLite:s atomic commit](https://www.sqlite.org/atomiccommit.html),
[synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous) och
[locking mode](https://www.sqlite.org/pragma.html#pragma_locking_mode).

## Verifiering

Lokala regressionsfall provar krypterade nycklar, parallell ägare, ofullständiga
filer, ändrat integritetshuvud, felaktiga protokollposter, skrivfel, okänt
commitutfall, bestående equivocationfel, återställda saldon/noncer, spärrad
planåteranvändning och sanningsenlig CLI-/Desktopstatus.

Ett separat prov använder tre ägda loopbackprocesser med riktiga TCP-länkar.
Koordinatorprocessen avslutas abrupt både före och efter SQLite-commit. De andra
två fortsätter skapa block. Återstarten behåller identitet och exakt nästa egen
sekvens och alla tre konvergerar till samma verifierade blockmängd och konton.
Detta är processkraschprov på Windows, inte ett verifierat strömavbrott på alla
plattformar. POSIX-krypteringen provas lokalt; fysisk Linux/Termux väntar på den
sammanhållna acceptansen.

## Antaganden och återstående frågor

Disk, operativsystem och SQLite måste respektera sina synkroniseringskontrakt.
En full återställning av en äldre giltig diskbild kan inte upptäckas med enbart
data från samma återställda disk. Externa betrodda kontrollpunkter eller ett
monotont signeringsankare återstår före en sådan garanti.

LAN-roster binder endpoint. Adressbyte/DHCP-migrering kräver ett specificerat
förfarande; `lan.resume` byter inte adress eller identitet i smyg. Förlorat
profilskydd/lösenord har ingen automatisk återställningsbakdörr.

Publik transport, data availability, kanonisk DAG-konsensus, lättklientbevis,
monetär modell, mining/pooler, beskärning och huvudnätsberedskap återstår enligt
[leveranskontraktet](delivery-contract.json). Lokal beständighet uppfyller inte
dessa separata krav.
