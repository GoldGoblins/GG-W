# GG Terminal — Windows, Linux och Termux

Samma Python-kod ger en riktig textbaserad terminal för wallet, marketplace och
GG:s lokala nätverk. Ingen Qt, webbläsare, webview, bildmotor eller automatisk
nodstart krävs. Terminalen ritar bara när tillståndet eller terminalstorleken
ändras. En öppen desktop-session används inte som terminalens tillstånd.

Detta är ett källpaket med explicita paketinstallationer, inte ett fristående
native-program eller en offline-installation. Windows är den lokala testmiljön.
Den tidigare Linux/amd64-baslinjen har verifierats i en isolerad VM/container
med verkliga noder, krypterad wallet-backup/restore och MP-objektpass. Det nya
BIP39-flödet är verifierat med publicerade testvektorer och native terminalinput
på Windows. En ny Linux/amd64-kontroll verifierar PAPER skapande/återställning,
krypterad mnemonic, fel lösenord och capture-spärr helt utan nätverk under
walletproven, utan Qt/Solders/Pillow. AI-signerpublicering ingick inte i det
Linuxprovet. En fysisk Termux-enhet är ännu inte testad.
Androids native paketbyggen och terminalflöde är därför inte verifierade här.

## Starta från checkout eller käll-ZIP

Python 3.10 eller senare behövs. Packa upp ZIP-filen och öppna dess huvudmapp.

Det fristående GG-CLI-repot och de nya källpaketen har tre tunna
installationsvägar till samma installerare:

```text
Windows: .\install\windows.cmd --launch
Linux:   sh install/linux.sh --launch
Termux:  sh install/termux.sh --launch
```

Läs [den korta installationsguiden](repository-README.md) för plattformens
förutsättningar. `--check` visar bara den publika planen utan installation
eller nätverk. `--launch` startar CLI med exakt den privata miljöns Python
som bootstrap returnerade; ingen nod startas automatiskt.

Från den fullständiga GG-checkouten går samma installerare att köra som
`python support/gg-cli/install.py --platform windows --launch` (byt profil
till `linux` eller `termux` och tolkens namn vid behov). Den manuella
bootstrapvägen finns också kvar:

Windows:

```powershell
python support/gg-cli/bootstrap.py
python gg-cli.py
```

Linux:

```sh
python3 support/gg-cli/bootstrap.py
python3 gg-cli.py
```

Bootstrap skapar en privat venv under användarens datafolder och installerar de
exakta versionerna i requirements-filerna från PyPI. Den använder varken sudo,
administratörsrättigheter, ett globalt pip-mål eller `curl | sh`. Om den befintliga
Windows-checkoutens venv redan innehåller terminalberoendena kan launchern använda
den. Installation sker bara när bootstrap uttryckligen körs.

Termux använder samma två Python-kommandon. Installera Python och dess pip/venv
via Termux först. Om psutil eller PyCryptodome behöver kompileras krävs Termux
Clang och make. Ett valfritt Rust-baserat wallet-SDK kan även kräva Rust/Cargo.
Bootstrap installerar inte OS-paket och försöker inte ändra Termux globala pip.
Exempel på operatörens separata paketsteg, när dessa saknas:

```sh
pkg install python python-pip clang make
python support/gg-cli/bootstrap.py
python gg-cli.py
```

Termux är Android/Bionic, inte vanlig glibc-Linux. Linux-wheels eller en lyckad
Windows-installation bevisar därför inte att native-paketen fungerar där.

## Engångskommandon och JSON

Beredskap för separat publikt testnät och huvudnät beskrivs med samma
headless-kod som desktopstatus. En lokal testkörning kan hållas igång explicit:

```text
python gg-cli.py --json --command network.readiness
python gg-cli.py --foreground --command dag.live_start
```

Det andra kommandot kör åtta oberoende **lokala** producenter med verkliga
signaturer och varierad takt tills Ctrl+C. Det startar ingen publik nodtjänst.
I den interaktiva sessionen finns även `dag.live_stop` (paus), `dag.status`
och `dag.stop`. Ett annat engångskommando styr inte en redan körande process.
Utan `--foreground` städas sessionens egna motorer som tidigare vid exit.

Läs [lanseringsgränserna](knowledge/dagoblin-launch-readiness.md) före publik
drift. Första enhetsprovet gäller Windows, Linux och Termux på lokalt nätverk.

## Privat LAN-prov: Windows, Linux och Termux

Starta Windows som koordinator via Desktop → DAGoblin → LAN. Spara den
**publika bootstrapfilen** och kopiera den med källpaketet till Linux och
telefonen. På varje enhet skapas egna tillfälliga nycklar i RAM; bootstrapfilen
innehåller inga privata nycklar. Från Linuxpaketets mapp:

```sh
python3 gg-cli.py --foreground --command "lan.start label=Linux allow_test_tokens=true auto_produce=false" --bootstrap-file gg-lan-bootstrap.json
```

På telefonen: samma kommando med `label=Termux`. Använd `python` om det är
tolkens namn. `--invite-out` behövs inte för automatisk annonsering.
Ingen manuell IP-adress behövs: bootstrap anger koordinatorn och operativsystemet
väljer den egna adressen. Den signerade inbjudan annonseras till koordinatorn.
Windows visar högst två kandidater före ditt uttryckliga sessionsval.
En misslyckad annonsering lämnar parningen öppen med felstatus för nytt försök.

Tre peers delar sex producenter, två signerare per enhet. Förslags-DAG:en
överför tomma signerade förslag med verkliga föräldrar. Det uttryckliga
testtokenvalet aktiverar en separat koordinatorordnad GG-LAN(TEST)-ledger;
inga finansiella överföringar eller DAG-finalitetscertifikat ingår. Aktuell fysisk Linux-/Termuxruntime
har anslutit i det första fysiska provet, men kompletta tokenvarv och full
slutkvittering är ännu inte godkända. Se [hela provet](knowledge/dagoblin-lan.md).

`--foreground` visar status och hålls öppet till Ctrl+C. Ett separat
engångskommando kan inte styra den processen. Interaktiv CLI har samma
`lan.*`-kommandon i `:`-fältet. Exportfiler måste ha nya namn; befintliga filer
skrivs aldrig över. Efter processomstart krävs ny parning.

En Windowskoordinator kan också köras helt i interaktiv CLI. Starta
`python gg-cli.py` och kör följande i samma sessions `:`-fält, ett kommando
i taget. Linux och telefonen startas med den exporterade bootstrapfilen
innan kandidaterna granskas och sessionen skapas:

```text
lan.start label=Windows allow_test_tokens=true auto_produce=false
lan.export_bootstrap path=gg-lan-bootstrap.json
lan.status
lan.session_create {"distribute":true,"enable_test_tokens":true}
lan.circle_start duration_ms=10000 batch=1 amount_atomic=1000000
```

`lan.status` ska först visa Windows och de två förväntade kandidaterna.
`lan.session_create` är ditt uttryckliga val av dessa tre peers. Använd
`lan.pause` för att pausa egna producenter, `lan.distribute` för ett nytt
distributionsförsök och `lan.stop` för att avsluta den egna sessionen.
Alla tre startkommandon måste uttryckligen tillåta testtokens för att
`enable_test_tokens=true` ska accepteras. `amount_atomic=1000000` är en
GG-LAN(TEST) med sex decimaler. Cirkelprovet signerar på respektive apparat,
mäter kvitterade överföringar och kontrollerar att alla tre har samma
kvittokedja. `lan.circle_stop` avbryter provet. Testtokens har inget ekonomiskt
värde; saldo och kvitton är inte DAG-konsensus eller huvudnätsaktivitet.
Automatisk förslagsproduktion är avstängd under parning och tokenprov. Kör
batch-1-provet direkt efter ny parning; fasta sessions- och transportkvoter
höjs inte av denna uppdatering. `lan.produce interval_ms=250` är ett separat
uttryckligt val för ett senare förslagsprov, inte ett steg före tokenprovet.

```sh
python gg-cli.py --once --json
python gg-cli.py --once --view marketplace --width 100 --height 30
python gg-cli.py --command help --json
python gg-cli.py --command wallet.status --json
python gg-cli.py --command wallet.watch --args '{"chain_id":"eip155:1","address":"0x0000000000000000000000000000000000000001","label":"Bevakning"}' --json
```

JSON-citering i sista exemplet är för ett POSIX-skal; PowerShell kräver korrekt
citering för den aktuella Python-versionen. `--args` är ett publikt JSON-objekt,
inte skalkod. Inga lösenord, fröfraser eller privata nycklar får anges i argv.
Publika bevakningsadresser ger ingen signeringsrätt. Externa läsningar görs först
vid ett uttryckligt refresh-/katalogkommando, inte som dold bakgrundspollning.

## Wallet och mänskligt godkännande

`wallet.create` skapar som standard en **PAPER-wallet med 24 engelska BIP39-ord**
och rollen `TRADING`. Välj 12/24 ord, `TRADING`/`STORAGE` och `PAPER`/`AI` i
formuläret med `n`. Båda metoderna ger en användarägd adress; AI-läget äger inte
nyckeln och ger ingen stående rätt att flytta tillgångar.

PAPER kräver först ett uttryckligt ja till pappersförvaringen. Orden visas
numrerade på en separat lokal terminalyta tills du trycker Enter eller Esc.
Därefter besvaras tre slumpvis valda ordkontroller dolt. GG sparar bara adress
och uppsättningsmetadata, ingen PAPER-fras eller privat signerarnyckel. AI väljs
uttryckligen och kräver ett lösenord två gånger för lokalt krypterat valv och
portabel krypterad frasåterställning. Samma exakta skapandegodkännande krävs före
publiceringen i registret.

Nyckelhärledningen gäller för närvarande **Solana**, med SLIP-0010-sökvägen
`m/44'/501'/0'/0'`. En annan wallet måste använda samma sökväg för att återställa
samma adress. Att en adress kan bevakas på andra kedjor innebär inte stöd för
nyckelhärledning eller signering där.

PAPER, bevakning, publika saldon och GG:s testnät använder inte solders eller Qt.
AI och Solana-signering kräver det valfria SDK:t:

```sh
python support/gg-cli/bootstrap.py --wallet-signing
```

Det installerar exakt solders 0.29.0, jsonalias 0.1.1 och typing_extensions 4.16.0.
På stödda Windows-/Linux-arkitekturer finns distributionshjul från leverantören.
Termux kan behöva bygga solders från Rust-källkod. Det Android-bygget är **inte
verifierat här** och SDK-installationen kan misslyckas. Watch-/GG-nätverksläget
behöver inte detta SDK och fortsätter vara separat, liksom PAPER-flödet.

I helskärmens `:`-fält kan samma publika kommandon anges:

```text
wallet.create label="Min paperwallet" method=PAPER count=24 purpose=TRADING
wallet.restore_phrase label="Återställd wallet" method=PAPER purpose=STORAGE
wallet.recovery pubkey=DIN_OFFENTLIGA_SOLANA_ADRESS
wallet.export_recovery pubkey=DIN_OFFENTLIGA_SOLANA_ADRESS path="ABSOLUT_LOKAL_SÖKVÄG"
```

`wallet.restore_phrase` frågar efter frasen dolt; den hör aldrig hemma i
kommandot. `wallet.recovery` visar en AI-wallets sparade ord privat efter dolt
lösenord och nytt godkännande. `wallet.export_recovery` kopierar endast den
krypterade frasfilen till en ny lokal fil. `wallet.backup`/`wallet.restore` är
fortsatt den separata äldre signerbackupen, inte samma format som frasfilen.

Ordvisningen kräver helskärmens privata TTY-yta; använd gärna minst 40×24 tecken.
`--json` och vanlig engångsutdata har ingen sådan yta och avvisar skapande,
frasåterställning och ordvisning före generering/dekryptering. Orden hamnar inte
i status, JSON, normal terminalhistorik eller publika modellfält. GG:s egen
capture spärras tills den privata ytan är rensad; andra program och kameror
omfattas inte av den spärren.

Senare ordvisning gäller AI-wallets som faktiskt skapats/återställts med detta
lagrade mnemonicflöde. En äldre/importerad rå signerarnyckel har ingen ursprunglig
BIP39-fras som GG kan återskapa automatiskt. Nya ord skulle kunna ge en annan
adress och uppfinns därför aldrig. PAPER sparar medvetet inga ord: senare
återställning kräver ägarens papperskopia. Detta är valda förvaringsmetoder,
utan låsning till GG-konto eller AI.

Lösenord läses dolt i terminalen, aldrig via kommandoraden. Windows använder
användarens DPAPI-valv. Den portabla POSIX-vägen använder det lösenordskrypterade
valvet. Skapa/backup/restore och verklig sändning visar en konkret publik
operationsbeskrivning och kräver ett uttryckligt `ja`/`yes` i terminalen. Det
finns ingen `--yes`-flagga. Om en terminal/prompt saknas avvisas operationen.
Godkännandet är bundet till just den operationen, förbrukas efter försöket och
ersätter aldrig desktopens pågående arbetsuppgift. En ändrad mottagare, fil,
RPC-identitet, granskningspost eller utgångstid kräver ny granskning.

## Priser och färger

Walletens `r` / `wallet.refresh` läser de valda kontonas saldon och gör ett
begränsat prisjobb för deras native-tillgångar och positiva tokenpositioner.
Nyupptäckta Solana-mintar ingår. Status och uppstart gör inga prisanrop; ingen
automatisk minutloop startas. CoinGeckos explicita identiteter prioriteras,
sedan kan exakta kedje-/tokenadresser användas hos DEX Screener/GeckoTerminal.
Adaptrar finns för sju EVM-kedjor, Solana och TRON. BTC/KAS/ADA behåller sina
native-källor. Pump-fallbacken är begränsad till verifierade direkta SOL-/USDC-
kurvor och ett verkligt färskt USD-ankare. Jobb begränsas till 64 tillgångar;
cache återanvänds i minst 60 sekunder. En notering är indikativ, inte en handel.

Alla tokens har inte en tillgänglig prisväg. Exempel-minten
`6TY5cDkAD3BN5L8MEXAcd2LysxWRAiji8TJSHUBapump` får nu en verifierad indikativ
reservnotering efter rättat stöd för den officiella historiska151-byte
Pump-allokeringen och legitimt bränt mintutbud. Ett tomt/avvisat svar från andra
marknader gör fortfarande aldrig priset noll. I projektcheckouten finns mer underlag i
`knowledge/token-market-pricing.md`.

Terminalen läser samma `config/gg-palette.json` som desktopens kontroller:
neutrala gråtoner och gemensamma semantiska accentfärger. Paletten bygger på
valda xterm256-färger från GG:s terminalrenderare; den påstås inte vara ett
universellt Codex-tema. Ingen Qt-import behövs för färgerna.

## GG-nätverket

### DAGoblin på Windows, Linux och Termux

Den gemensamma LAN-koden kör tre separat ägda peers. Det nya valbara
DAG-testläget bär signerade testtransaktioner **i DAG-blocken**. Det kräver
uppdaterad kod, ny parning och `allow_dag_transactions=true` på alla tre:

```sh
python gg-cli.py --foreground --command "lan.start label=Termux allow_dag_transactions=true auto_produce=false" --bootstrap-file gg-lan-bootstrap.json
```

På Linux används `python3` och `label=Linux`. Bootstrapen ska vara den nya
publika fil som den uppdaterade Windowskoordinatorn skapade. Inga privata
nycklar flyttas mellan apparaterna. Foregroundprocessen måste vara kvar;
ett nytt engångskommando styr inte den gamla processen.

Den interaktiva koordinatorns kommandon, eller desktopens motsvarande
LAN-kontroller, skapar och kör det tidsbegränsade provet:

```text
lan.session_create distribute=true enable_dag_transactions=true
lan.dag_stress_start duration_ms=10000 transactions_per_block=16 interval_ms=100
lan.dag_stress_stop
```

Lokalt verifierade DAG-transaktioner och nätverksbekräftad genomströmning
visas separat. En gemensam bekräftelse kräver samma verkliga blockmängd och
tillstånd hos alla tre. Det är ett icke-finansiellt, ofinaliserat testprotokoll.
Den tidigare `lan.circle_start` mäter en separat kvittoledger och får inte
räknas som DAG-TX. Tusentals TX/block och flera hundra block/s är mål att
belastningsprova, inte uppmätta egenskaper eller garantier för dessa profiler.
Se [det gemensamma LAN-underlaget](../../knowledge/dagoblin-lan.md).

### Lokala protokollprov

Parallell DAG kan provas separat utan nodbinär eller nätverk:

```sh
python gg-cli.py --command dag.test --json
```

Utvecklingsspåret heter **DAGoblin**. Den lokala testmotorn har ingen global
slutlighet. Forskningsunderlag och förslag till kapacitetsanpassad takt finns i
`knowledge/research/dagoblin/README.md`, även i de tre källpaketen.
Planeraren är helt offline och använder inga walletnycklar:

```text
python support/dagoblin/analyze.py --json
python support/dagoblin/analyze.py --input capacity.json
```

Den skiljer Gbit/s, Gib/s och GiB/s och räknar på länk, signerare/verifierare,
disk och minnesfönster. Exakta rationaltal visas som strängar. Resultaten är
villkorade kapacitetsscenarier, inte uppmätt TPS. Bytebaserade tak och estimat
från p95-servicetider redovisas separat; p95 ger ingen säker körtakt.
Okänd exekverings-/kvorum-
kapacitet får inte tolkas som obegränsad. Den ändrar inte provmotorns gränser
eller startar någon nätverkslast. Se arkitekturdokumentet för säkra återförsök
och långsamma enheter.

Det ändliga provet skapar två vågor med 24 signerade förslag och åtta
testtransaktioner per förslag, kontrollerar verkliga föräldralänkar och stänger
sin egen RAM-session. I TUI:ns `:`-fält finns `dag.start`, `dag.wave`,
`dag.status` och `dag.stop`; `dag.wave blocks=24 transactions_per_block=8`
använder samma motor som desktop. Status skapar inga nya block eller arbetare.
Olika engångskommandon delar ingen levande session.

Detta är fyra producenttrådar på en dator och ett experimentellt lager för
signerade förslag, inte nätverkskonsensus eller kanonisk finalitet. Gränserna
är högst 32 förslag, 512 transaktioner totalt per jobb och sju verkliga
föräldrar per förslag. Det finns inga riktiga tillgångar. Se
[DAG-protokollet och kvarstående arbete](../../knowledge/gg-parallel-dag.md).

Motorn är valfri. Installera/bygg den uttryckligen med dess separata verktyg:

```sh
python support/gg-consensus/install_toolchain.py --native-only
```

Se support/gg-consensus/README.md för leverantör, verifiering och plattformskrav.
Fyra separata CometBFT-validatorprocesser på **en dator och en operatör** är ett
lokalt testnät med statisk validatorlista, inte ett publikt decentraliserat nät.
Nycklar finns bara i nodsessionens RAM. TUI:n håller sin uttryckligt startade
session levande och stoppar endast sina egna noder när den avslutas. Separata
engångskommandon delar inte en levande nodsession. Ingen anslutning görs till
desktopens befintliga testnod eller en godtycklig RPC-port.

Ett ändligt funktionstest som startar och stannar sina egna fyra noder:

```sh
python gg-cli.py --command network.test --json
```

I helskärm: `1` wallet, `2` marketplace, `3` nätverk, pilar väljer rad och Enter
visar detaljer. `/` söker och `?` visar kommandon. Wallet: `a` bevaka, `n` skapa,
`e` mottagaradress, `f` förbered, `s` skicka granskad, `t` token, `k` backup,
`o` återställ fras eller äldre backup, `m` visa AI-ord privat och `g` exportera
krypterad frasåterställning. Marketplace: `l` växlar lokalt/publikt, `u` hämtar publik katalog
och `a` registrerar ett lokalt objekt. Nätverk: `p` startar, `x` stoppar, `v`
kör feltest och `b` mäter 32 verifierade överföringar. `q` avslutar.

## Filer, beroenden och källpaket

Standard: `%LOCALAPPDATA%/GoldGoblins/gg-terminal` på Windows respektive
`$XDG_DATA_HOME/goldgoblins/gg-terminal` (eller `~/.local/share/...`) på POSIX.
`GG_TERMINAL_STATE_ROOT` och `GG_TERMINAL_DATA_ROOT` kan peka på egna privata
terminalmappar. Launchern sätter backendens sökvägar innan backend importeras.
Ärvda `GG_DESKTOP_*`-värden väljer inte desktopens tillstånd automatiskt.

Grundberoenden: prompt_toolkit 3.0.53, wcwidth 0.2.14, psutil 7.2.2,
PyCryptodome 3.23.0, bech32 1.2.0 och mnemonic 0.21. wcwidth 0.2.14 är ett avsiktligt fryst,
rent Python-hjul för portabilitet; det är inte den senaste wcwidth-versionen.
Installation använder `--no-deps` med den explicit deklarerade beroendelistan.
Inga Qt-/webbläsarpaket eller privata användardata ingår i terminal-ZIP:arna.

Källpaket skapas lokalt efter källfrysning:

```sh
python support/gg-cli/build_release.py --platform all --output-dir .runtime/gg-terminal-release
```

Byggaren använder en granskad fillista och vägrar oväntade backend-importer.
Den kopierar inga användarprofiler, `.runtime`, venvs, nycklar, tillståndsdatabaser
eller Go-binärer. Manifestet innehåller endast publika källfiler och deras
integritetsuppgifter. Alla plattformsarkiv innehåller samma programkod.

Den befintliga projekt-README:n anger [GoldGoblins/GG](https://github.com/GoldGoblins/GG)
som repository. Arkiven är förberedda för en GitHub-release men ingen publicering,
push eller uppladdning görs av dessa verktyg. En GitHub-kopia innehåller ändringen
först efter att projektägaren faktiskt har publicerat den.

Verifierade leverantörssidor:
[prompt_toolkit 3.0.53](https://pypi.org/project/prompt_toolkit/3.0.53/),
[wcwidth 0.2.14](https://pypi.org/project/wcwidth/0.2.14/),
[psutil](https://pypi.org/project/psutil/),
[PyCryptodome 3.23.0](https://pypi.org/project/pycryptodome/3.23.0/),
[solders 0.29.0](https://pypi.org/project/solders/0.29.0/).
