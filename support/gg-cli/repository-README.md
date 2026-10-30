# GG CLI — Windows, Linux och Termux

En gemensam headless-kodbas med tre installationsvägar. Samma signerade
protokoll och samma CLI-kommandon används på dator och telefon. Ingen Qt,
webbläsare eller desktopinstallation behövs.

Detta är källkod med uttrycklig installation av beroenden, inte en fristående
EXE/APK. Repositoriet är `GoldGoblins/GG-CLI`; den fullständiga desktopkoden
för det gemensamma LAN-provet finns i [GoldGoblins/GG-W](https://github.com/GoldGoblins/GG-W).

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
att alla dess Pythonberoenden fungerar på varje telefon. Den första fysiska
telefonen har anslutit i LAN-provet, men ett komplett tokencirkelprov är
fortfarande inte godkänt.

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
python3 gg-cli.py --foreground --command "lan.start label=Linux allow_dag_transactions=true auto_produce=false" --bootstrap-file gg-lan-bootstrap.json
```

I Termux används `python` och `label=Termux`. `--invite-out` behövs inte
för automatisk annonsering. Den egna LAN-adressen väljs automatiskt.
Varje peer annonserar sin signerade publika inbjudan till koordinatorn;
Windows granskar de två kandidaterna och godkänner den gemensamma sessionen.
Ingen manuell IP-letning behövs när klienterna väl har startats.

Detta val gäller signerade, icke-finansiella testtransaktioner **i DAGoblin-
blocken**. Alla tre behöver uppdaterad kod och uttryckligt deltagarval före
ny parning. Windows väljer DAG-testtransaktioner i LAN-dialogen och kör sedan
ett tidsbegränsat prov där samma graf visar verkliga block, föräldralänkar,
verifierade DAG-TX och mättider. Motsvarande kommandon i en interaktiv
koordinatorsession är:

```text
lan.session_create distribute=true enable_dag_transactions=true
lan.dag_stress_start duration_ms=10000 transactions_per_block=16 interval_ms=100
lan.dag_stress_stop
```

Backend annonserar den aktuella testprofilens gränser. De är programgränser,
inte uppmätt hårdvarukapacitet. Tusentals TX/block och flera hundra block/s är
ett framtida prestandamål. Lokal validering och autentiserat gemensamt
bekräftat resultat redovisas separat; inget prov ger kanonisk finalitet.
Den äldre `allow_test_tokens`-/`lan.circle_start`-vägen är en separat
kvittoledger och väljs inte samtidigt med DAG-testtransaktionsläget.

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
lan.circle_start duration_ms=10000 batch=1 amount_atomic=1000000
```

`lan.circle_stop` avbryter provet. Varje apparat signerar själv; koordinatorn
ordnar testöverföringarna och signerar kvitton som alla tre verifierar.
Saldon och nonce är exakta heltal. Dessa testtokens saknar ekonomiskt värde
och är inte kanoniskt finaliserade DAG-transaktioner. Provet begränsas till
högst 60 sekunders gemensam arbetsbudget och en fast kvittokvot, följt av
högst en sekund för avstängningsmeddelanden. Verkligt uppmätt TX/s rapporteras
separat från block-/förslagshastigheten och bildfrekvensen.

Börja direkt efter ny parning med batch **1** i **10 sekunder**. Automatisk
förslagsproduktion är avstängd under parning/tokenprov; startkommandot anger
`auto_produce=false`. Befintliga ändliga sessions-/transportkvoter är kvar.
Höj därefter uttryckligen upp till
batch 16 när alla tre bekräftar samma kvittokedja och kompletta varv. Desktop
har motsvarande kontroller för batch 1–16 och längd 1–60 sekunder. En felkod
eller saknad slutkvittering betyder ett ofullständigt prov, även om verkliga
signerade överföringar redan hunnit bokföras. Felaktiga prov räknas inte som PASS.

Vid uppdatering: stoppa den egna peeren med Ctrl+C, kör `git pull`, starta
om och para alla tre igen med en ny publik bootstrap. Hämta även uppdaterad
GG-W på desktopdatorerna; en separat engångsprocess uppdaterar inte kod i en
redan körande nod.

[Hela CLI-handboken](support/gg-cli/README.md) ·
[LAN-provet](knowledge/dagoblin-lan.md) ·
[Protokoll- och lanseringsgränser](knowledge/dagoblin-launch-readiness.md)

## Verifierad omfattning

Windowskontrollerna använder disponibla lokala processer och isolerade
testdata. Tre loopbackprocesser är inte tre verifierade fysiska enheter.
Det första observerade Windows/Linux/Termux-provet registrerade 16 signerade
testöverföringar men avbröts med fel före ett komplett varv. Koordinatorns
saldon var då Windows 984, Termux 1016 och Linux 1000 GG-LAN(TEST); detta är
inte ett påstående om den senare sessionens aktuella saldon. Detta är
ett partiellt resultat, inte ett godkänt tokencirkelprov. Efter denna
källuppdatering återstår full omstart, ny parning och ett nytt fysiskt prov.

Publikt testnät och huvudnät är inte aktiverade av en installation. CLI delar
de gränser och den status som den aktuella backendkoden faktiskt rapporterar.
