# DAGoblin på tre egna LAN-enheter

Första målet är en Windows-dator, en Linux-dator och en Androidtelefon med
Termux på samma privata nät. VPS och huvudnät ingår inte i detta steg.
Samma headless-transport används av Desktop och terminalpaketen.

## Vad som överförs

Varje peer skapar två egna tillfälliga producentnycklar och en separat
transportidentitet i sitt RAM. En signerad publik inbjudan beskriver peerens
adress och publika nycklar. Koordinatorn väljer exakt tre inbjudningar och
skapar en signerad session med sex producenter och gemensam publik genesis.
Varje peer har bara sina egna två signeringsnycklar. De andra producenternas
och kontonas privata nycklar överförs inte.

Peertrafiken använder signerad ömsesidig challenge, sessionsdomän och
sekvenskontroller. Inventering och begäran av saknade föräldrar är begränsade
med fasta frame-, byte-, orphan- och sessionskvoter. Normal dataframe är
högst 64 KiB; den större publika sessionsfilen är högst 256 KiB. En sådan
begränsning är inte ett bevis mot alla nätverksattacker.

Förslags-DAG:en överför **verkliga tomma signerade förslag**. Finansiella
transaktioner mellan peers är avstängda: de lokala förhandsrötterna är ännu
inte gemensamma slutliga checkpoints. Grafen visar verkliga signerade
förslag och deras verkliga föräldrar; mottagningsordningen är lokal.
Kanonisk finalitet är noll. Ed25519 är inte kvantsäkert. Trafikens signaturer
ger inte krypterad innehållssekretess.

Ett separat valbart **GG-LAN(TEST)**-läge överför riktiga signerade
testtokenöverföringar. Alla tre peers måste först ha valt `allow_test_tokens=true`.
Koordinatorn ordnar överföringarna och signerar en hashkedja av kvitton;
alla peers kontrollerar signaturer, exakta heltalssaldon, nonce och samma
tillståndsrot. Varje peer behåller sin egen signerare. Detta är en uttryckligt
koordinatorordnad testledger med en fast testtilldelning, inte DAG-konsensus
eller pengar som kan tas ut eller användas på ett publikt nätverk.

## Uppstart

Packa upp plattformens källpaket och kör dess uttryckliga bootstrap enligt
[terminalens README](../support/gg-cli/README.md). Ingen nod startas av en
vanlig statusläsning. Installationen och Pythonkörningen på en fysisk
Termuxtelefon måste fortfarande verifieras där.

Windows är koordinator. I Desktop öppnas DAGoblin och LAN-inställningen.
Starta parning och spara den publika bootstrapfilen till Linux och telefonen.
Välj före start **Tillåt privata GG-LAN-testtokens** om tokenprovet ska köras.
Filen innehåller koordinatorns publika identitet och endpoint, inga privata
nycklar. Nycklar lever bara under processen: en omstart kräver ny parning.

På Linux med full GG-W Desktop öppnas samma DAGoblin → LAN-dialog.
Ange nodnamn, välj **Tillåt privata GG-LAN-testtokens** om provet ska köras
och klicka **Anslut med publik bootstrap…**. Läs filen som Windows sparade.
Starta ingen extra koordinator på Linux. Appen annonserar sin signerade
inbjudan till Windows och visar den anslutna peerens graf i Desktop.

Telefonen kör sin egen foregroundprocess med bootstrapfilen bredvid
`gg-cli.py`. Exempel från GG-CLI-mappen i Termux:

```sh
python gg-cli.py --foreground --command "lan.start label=Termux allow_test_tokens=true" --bootstrap-file gg-lan-bootstrap.json
```

Linux CLI är ett valfritt alternativ med `python3` och `label=Linux`.
`--invite-out` behövs inte för automatisk annonsering. Om en publik inbjudan
ändå exporteras måste filnamnet vara nytt: export skriver aldrig över en
befintlig fil. Detta är inte ett kommando för lösenord eller privata nycklar.

Deras lokala IPv4 väljs genom operativsystemets route till koordinatorn;
ingen manuell IP-inmatning behövs på dessa enheter. Kontrollera kandidaternas
namn i Windows innan den gemensamma trepeersessionen skapas. Enheten skickar
sin signerade publika inbjudan till koordinatorn i bootstrapfilen; koordinatorn
kontrollerar även den annonserade endpointen före kandidatvisning. En kandidat
ansluts inte automatiskt till en ny session.

När alla tre signerade inbjudningar tillåter testtokens kan Windows skapa
sessionen med testledgern. I samma interaktiva koordinator-CLI används:

```text
lan.start label=Windows allow_test_tokens=true
lan.export_bootstrap path=gg-lan-bootstrap.json
lan.status
lan.session_create distribute=true enable_test_tokens=true
lan.circle_start duration_ms=10000 batch=16 amount_atomic=1000000
```

De andra klienterna startas med bootstrapfilen innan sessionen skapas.
Kontrollera deras namn i `lan.status`. I Desktop finns motsvarande
cirkelknapp och en saldorad per peer i LAN-dialogen. `lan.circle_stop`
avbryter provet, medan `lan.stop` eller Ctrl+C stänger hela den egna peeren.
Ett prov har en gemensam arbetsbudget på högst 60 sekunder, inklusive
första och sista kvittosynkronisering och nätväntan, samt en fast kvittokvot.
Därefter har enbart avstängningsmeddelanden en separat gemensam budget på
en sekund. Om arbetsbudgeten tar slut före alla tre bekräftat samma kedja
visas ett delvis genomfört prov med `TIME_BUDGET`. Mängden är
exakta atomiska testenheter: 1 000 000 atomer motsvarar en GG-LAN(TEST).
Belopp går aldrig genom binära flyttal.

Koordinatorn begär bara den överenskomna cirkelöverföringen av den egna
signeraren på respektive apparat. Signerade batcher och kvitton skickas över
den autentiserade transporten. Ett godkänt varv kräver att alla tre har
bekräftat samma kvittokedja. Visad TX/s bygger på faktiskt kvitterade
testöverföringar och uppmätt tid, med transportens resursgränser kvar.
Delvis genomförda prov, kvotstopp och saknad synk ska redovisas uttryckligen.

Desktop visar den aktiva LAN-peerens graf, verkliga peerstatus och egna
producenter. **Stoppa** avbryter även under parning och belastning; städningen
görs utanför UI-tråden. Ctrl+C avslutar terminalprocessens egna trådar och
socketar. Ett fristående CLI-kommando styr inte en annan process.

## Godkänt enhetsprov

Ett lokalt prov med tre separata processer ersätter inte dessa kontroller:

1. Alla tre fysiska enheter visar samma sessionsdomän och sex producenter.
2. Varje enhet signerar bara för sina egna två producenter.
3. Förslag från alla tre enheter tas emot och verifieras hos de andra två.
4. Gemensamma förslag har identiska hashvärden och föräldrareferenser.
5. Avbrott eller frånkoppling visas som verkligt tillstånd; återanslutning
   inom samma session reparerar saknade föräldrar inom kvoten.
6. Stoppa/Ctrl+C fungerar under trafik och lämnar inga egna arbetare kvar.

Appen anger inte automatiskt att fysiska värdar har verifierats. Ett stängt
brandväggshål, ett isolerat gäst-Wi-Fi eller en sovande telefon kan hindra
trafik trots samma SSID. Ändra nät-/brandväggsinställningar först när ett
konkret anslutningsfel visar att det behövs.

[Nästa steg och publik beredskap](dagoblin-launch-readiness.md)
