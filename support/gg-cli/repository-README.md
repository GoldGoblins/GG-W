# GG CLI — Windows, Linux och Termux

En gemensam headless-kodbas med tre installationsvägar. Samma signerade
protokoll och samma CLI-kommandon används på dator och telefon. Ingen Qt,
webbläsare eller desktopinstallation behövs.

Detta är källkod med uttrycklig installation av beroenden, inte en fristående
EXE/APK. Repositoriet är avsett som `GoldGoblins/GG-CLI`; ursprungskoden
underhålls även i [GoldGoblins/GG](https://github.com/GoldGoblins/GG).

## Hämta koden

Klona repositoriet eller hämta och packa upp dess käll-ZIP. Följ sedan rätt
installationsväg från repots huvudmapp. Python **3.10 eller senare** behövs.
Installationskommandot laddar uttryckligen ned de exakt versionslåsta
Pythonberoendena från PyPI till en privat miljö för den aktuella användaren.
Det använder inte global pip, sudo eller administratörsrättigheter.

### Windows

Installera Python 3.10+ om det saknas och öppna PowerShell i repots mapp:

```powershell
.\install\windows.cmd --check
.\install\windows.cmd --launch
```

`--check` visar bara planen. Det andra kommandot installerar beroendena och
öppnar CLI med den installerade miljöns exakta Python, även om datorn också
har andra Python-/desktopmiljöer. Om `py` saknas används `python`.

### Linux

Python, pip och venv ska finnas från distributionens egna paket. Därefter:

```sh
sh install/linux.sh --check
sh install/linux.sh --launch
```

Installationen kräver inte root. Om ett versionslåst beroende behöver byggas
från källkod behövs plattformens vanliga C-kompilator och byggverktyg.

### Android med Termux

Öppna Termux och installera vid behov dess egna Python-/byggpaket:

```sh
pkg install python python-pip clang make
sh install/termux.sh --check
sh install/termux.sh --launch
```

Kör skriptet med `sh` som ovan; en vanlig Linuxsökväg för shebang krävs inte.
Termux är Android/Bionic. En lyckad Windows-/Linuxinstallation bevisar inte
att dess Pythonberoenden fungerar på en fysisk telefon. Det fysiska
Termuxprovet är ännu inte verifierat i detta källunderlag.

Alla tre skript är tunna anrop till samma `install.py`. `--launch` öppnar CLI,
men startar ingen nod. Utelämna flaggan om du bara vill installera miljön.
Installation och användardata ligger utanför repot; inga privata nycklar eller
inloggningar ingår i källpaketet. Det valfria Solana-SDK:t installeras bara
med `--wallet-signing` och behövs inte för LAN-noden.

## Första kontrollen

```text
python gg-cli.py --json --command network.readiness
python gg-cli.py --json --command lan.status
```

Använd `python3` om det är tolkens namn. En statusläsning skapar inga
identiteter och startar ingen nätverksnod. `network.readiness` redovisar
skillnaden mellan privat LAN-prov och ett ännu inte färdigt publikt nätverk.

## Windows → Linux → telefon

Windows kan vara koordinator i GG AI Desktop → DAGoblin → LAN, eller i en
interaktiv CLI-session. Koordinatorn sparar en **publik bootstrapfil** som
kopieras till Linux och telefonen. Filen innehåller koordinatorns publika
identitet och endpoint, inga privata nycklar.

Linux ansluter exempelvis så här från paketets mapp:

```sh
python3 gg-cli.py --foreground --command "lan.start label=Linux allow_test_tokens=true" --bootstrap-file gg-lan-bootstrap.json --invite-out gg-lan-linux.json
```

I Termux används `python`, `label=Termux` och exempelvis
`--invite-out gg-lan-termux.json`. Den egna LAN-adressen väljs automatiskt.
Varje peer annonserar sin signerade publika inbjudan till koordinatorn;
Windows granskar de två kandidaterna och godkänner den gemensamma sessionen.
Ingen manuell IP-letning behövs när klienterna väl har startats.

En separat engångsprocess styr inte en redan körande CLI-process. Använd
samma interaktiva sessions `:`-fält för `lan.*`-kommandon. Foregroundläget
visar status tills Ctrl+C och städar bara sina egna trådar och socketar.
Efter processomstart krävs ny parning. Befintliga exportfiler skrivs inte över.

`allow_test_tokens=true` är ett uttryckligt tillval för det privata
GG-LAN(TEST)-provet. Windowskoordinatorn ska också startas med detta tillval
(eller motsvarande kryssruta i Desktop). När alla tre kandidater granskats
kan samma interaktiva koordinator-session köra:

```text
lan.session_create distribute=true enable_test_tokens=true
lan.circle_start duration_ms=10000 batch=16 amount_atomic=1000000
```

`lan.circle_stop` avbryter provet. Varje apparat signerar själv; koordinatorn
ordnar testöverföringarna och signerar kvitton som alla tre verifierar.
Saldon och nonce är exakta heltal. Dessa testtokens saknar ekonomiskt värde
och är inte kanoniskt finaliserade DAG-transaktioner. Provet begränsas till
högst 60 sekunders gemensam arbetsbudget och en fast kvittokvot, följt av
högst en sekund för avstängningsmeddelanden. Verkligt uppmätt TX/s rapporteras
separat från block-/förslagshastigheten och bildfrekvensen.

[Hela CLI-handboken](support/gg-cli/README.md) ·
[LAN-provet](knowledge/dagoblin-lan.md) ·
[Protokoll- och lanseringsgränser](knowledge/dagoblin-launch-readiness.md)

## Verifierad omfattning

Windowskontrollerna använder disponibla lokala processer och isolerade
testdata. Tre loopbackprocesser är inte tre verifierade fysiska enheter.
Den aktuella Linux-/Termuxkoden måste installeras och provas på respektive
enhet innan någon sådan kompatibilitet eller genomströmning påstås.

Publikt testnät och huvudnät är inte aktiverade av en installation. CLI delar
de gränser och den status som den aktuella backendkoden faktiskt rapporterar.
