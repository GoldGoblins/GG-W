# GG Crypto Space: gemensam TUI-grund

## Ursprunglig avsikt

CRYPTO och MP ska kännas som delar av samma användbara cryptoarbetsyta.
Användaren pekade på för mycket luft runt rubriker och sammanfattningar,
trånga listor, en delad tokendetalj som krympte grafen och en tom MP-start.
OSINT, KNOWLEDGE och Velo var referenser för informationshierarki och tydlig
visning. ”Bredda vyerna” betydde att tänka friare och bredda inspirationen.
Obsidian/Ledger behåller svart/grå/vit grund och semantiska färgaccenter.

## Fynd och designbeslut

Jupiter och Uniswap skiljer utforskning, tillgång, portfölj och specialverktyg
inom en stabil navigationsram. En token kan utforskas utan att det samtidigt
finns en användbar exekveringsväg. Phantom visar också olika nätverksvarianter
som skilda positioner. GG behåller sin strikta nätverks-/kontraktsidentitet.
[Jupiter Spot](https://jup.ag/spot), [Uniswap](https://app.uniswap.org/swap),
[Phantom asset pages](https://help.phantom.com/articles/understand-asset-pages-in-phantom-52633747656211).

Velo granskades som källkod och dokumentation: README, arkitektur, mätmodell,
modell, körning, rendering, canvas, braille, tema, historik och relevanta tester.
Det är ett terminalbaserat hastighetstest i Go/Bubble Tea. GG:s implementation
är fortsatt Qt/QML. Velo-binära filer, installationsskript och mätmotor har
inte installerats eller körts. Ingen benchmark av dess prestanda på denna
dator har gjorts. Inspiration och referens är åtskilda från kopierad programkod.
[Velo](https://github.com/bjarneo/velo),
[arkitektur](https://github.com/bjarneo/velo/blob/main/docs/architecture.md),
[mätmodell](https://github.com/bjarneo/velo/blob/main/docs/measurement.md).

Det som förts över som designprinciper:

- Ett gemensamt skal med stabil navigation och en kort rubrikrad.
- En huvudgraf och sekundära fakta/händelser med tydlig prioritet.
- Smala vyer döljer eller öppnar sekundär information på begäran.
- Bakgrundsarbete, förberedd ögonblicksbild och rendering hålls separata.
- Händelser kommer från arbetet som faktiskt utförs.
- Diagram använder verkliga observationer; saknad data förblir saknad.
- Färgroller återanvänds. Tomgång behöver ingen dekorativ animation.

## Implementerat

`CryptoSpaceFrame.qml` används av både CRYPTO och MP. Marknad, Portfölj,
Marketplace, Botar och Nätverk/labb ligger i samma sidomeny. Specialverktygen
samlas i en meny. MP-fliken kan gå tillbaka till rätt CRYPTO-avsnitt. Inbäddad
MP använder samma befintliga skal. Äldre SOL/KAS- och analysfunktioner finns
kvar, med borttagen dubbel navigation och kompaktare portföljsammanfattning.

Marknadslistan har en verktygsrad med sökning, urval och filter på begäran.
En vald token öppnas över hela innehållsytan. Prishistorik läses automatiskt
för CoinGecko-token; veckokurvan eller lokala observationer kan visas när en
full historik inte finns. Grafens datumaxel använder riktiga tidsstämplar när
sådana finns. Pooler, nätverksvarianter och import ligger i en informationspanel.
Tidigare SOL/KAS-status uppdateras inte kontinuerligt när andra avsnitt är
aktiva, utom när dess egna jobb behöver följas.

Kontoöversikten är CRYPTO:s startsida. Totalvärdet ligger ovanför innehaven,
med konton/nätverk, antal positioner med läst positivt saldo och faktisk
saldokontroll. Nätverks- och kontourval ändrar totalen med separata exakta
Decimal-summor; en textsökning filtrerar listan utan att ändra kontots total.
Bekräftade nollsaldon kan visas med en toggle. Okända saldon döljs inte som
noll. Den tomma startsidan behåller översikten och öppnar kontoformuläret på
begäran. Inga demotillgångar läggs till för att fylla ytan.

Wallet använder samma tillgångsvy i arbetsytan och popupen: belopp, uppskattat
värde, nätverk och lässtatus. Konto-/nätverksfilter, sökning och en tillgångsdetalj
leder till adress, saldouppdatering och rätt kanoniskt bunden marknadstillgång.
Den tomma vyn innehåller ett formulär för offentlig adress i stället för en
stor tom lista. Tillagda konton kan läsa registrerade tillgångar direkt;
stora tokenregister begränsar första läsningen till native-saldot.
Publika konton och GG-labb är separata lägen. Överföring i labbet visas i
labbtillgångens detalj. Avancerade äldre verktyg ligger i en meny.

Översiktens uppdateringsknapp läser valda kontons registrerade saldon och
identitetsbundna priser. Ett jobb begränsas till 64 positioner, med full
kontovalidering före RPC. Större urval kräver val av konto eller tillgång.
CoinGecko-priser läses samlat med explicita provider-ID:n, aldrig ticker;
DEX-priser läses för exakt nätverk och kontrakt, högst 16 sådana tillgångar.
Marknadens sökning, paus och valda token ändras inte av walletuppdateringen.
Källornas befintliga cache och anropsbudget används. Misslyckade läsningar
behåller förra observationen med felstatus, aldrig ett konstruerat nollsaldo.
[CoinGecko market data](https://docs.coingecko.com/reference/coins-markets).

En ensam prisobservation eller en lokal observationsserie kortare än en minut
visas som antal observationer och senaste pris medan historik byggs upp.
Den ritas inte ut över en hel grafyta. En verklig konstant serie med tillräcklig
tidsutsträckning har en neutral linje, ett enda prisvärde på axeln och ingen
fylld yta som kan se ut som en avkastningsgraf.

Okända token-decimaler värderas aldrig som hela token. Mängden visas då i
basenheter och USD-värdet förblir okänt. Bekräftat Bitcoin-saldo och väntande
mempoolförändring är skilda uppgifter. Kopplingen från wallet till marknad
använder fullständigt tillgångs-ID och verifierad prisbindning, aldrig ticker.

MP visar lokala varor/tjänster och en separat publik samlingskatalog.
CoinGeckos publika NFT-lista och samlingsdetaljer läses med begränsning,
cache, paginering, identitetskontroll och gemensam anropsbudget med marknaden.
Kaspa/KRC-721 är en alternativ indexerkälla; rätt nätverk och synkstatus krävs.
Kaspa-källan visar den första sidan, upp till 50 samlingar, i denna version.
[NFT-lista](https://docs.coingecko.com/reference/nfts-list),
[samlingsdetaljer](https://docs.coingecko.com/reference/nfts-id),
[KRC-721 API](https://krc721.kat.foundation/docs).

En katalogreferens ger inget ägarbevis, protokollbevis eller säljorder.
Referenser med okänt format hålls synliga men kan inte automatiskt skickas
till en inkompatibel inspektör. Token-ID och protokoll måste kontrolleras
innan en specifik NFT kan inspekteras. Publika samlingar skapar inga lokala
varor, prisåtaganden eller paperköp.

Samlingsbilder läses bara från CoinGeckos angivna bildvärd och rätt sökväg,
över kontrollerad publik HTTPS. Bildstorlek, format och dimensioner valideras
innan en lokal förhandsbild visas. Detta är privata cachefiler, inte medföljande
produktbilder eller nygenererade illustrationer.

## FAKE_PROGRESS=FORBIDDEN

Detta är användarens uttryckliga UI-princip för hela GG AI DESKTOP:

1. Arbetsstatus visar ett faktiskt köat eller körande jobb.
2. Procent kräver uppmätt färdigt arbete och en känd relevant totalmängd.
3. Tid som gått sedan start är inte bevis på hur stor del som är klar.
4. Okänd återstående tid visas som okänd. Ingen automatisk uppskattning
   eller timer får fylla en förloppsindikator.
5. Start, validerat svar, cacheläsning, väntan på anropsbudget, fel och klart
   ska motsvara händelser i rätt fas. Cacheläsning är inte ett nytt nätverkssvar.
6. List- och grafdata får inte ersättas av produktionsmockar för att fylla yta.
   Isolerade testfixturer märks och används enbart i tester.
7. Saknad balans, volym, historik eller pris är inte noll.
8. Mätmotorn ändrar tillstånd. UI läser och renderar det. En UI-timer får
   uppdatera en vy, men inte uppfinna arbete eller marknadshändelser.

`crypto_activity.py` läser enbart verkliga sparade händelser. En separat
bakgrundsläsare låter starten av ett långsamt anrop synas medan huvudjobbet
fortfarande väntar på svaret. Panelen är begränsad till 80 poster. Att frysa
panelen stoppar visningen; jobbet fortsätter. Ny visning följer senaste data.
Stängd eller dold panel gör inga timerstyrda aktivitetsläsningar. Oförändrade
svar bygger inte om visningen. En faktisk begäran kan visa en indeterminerad
arbetsindikator; den visar ingen påhittad procent.

Velo har en uttrycklig demomotor och tidsbestämda mätfaser. Dessa delar har
inte överförts till GG:s produktionsindikatorer. En hastighetsmätning med känd
längd är inte samma sak som en RPC-förfrågan med okänd svarstid.

## Verifiering och återstående gränser

Qt-tester kontrollerar en sammanhängande marknad → token → MP → wallet →
labb-navigation, dominerande list-/grafyta i smal och bred vy, publika
samlingar utan lokala varor, bild-/detaljval och en riktig händelselogg.
Backendtester kontrollerar start före avslutat svar, stilla snapshots utan
fabricerade händelser, cachefel, samlingsidentitet, bildvärd och osynkron indexer.
Liveprober använder publika data i en separat tillfällig testprofil.

Det är en sammanhängande arbetsyta för befintliga läs-, paper- och
labbfunktioner. Publik NFT-katalog är inte anslutning till alla externa
marknadsplatsers säljorder. Mainnetsignering, en verifierad brygga och
produktionskonsensus är fortsatt separata, tidigare dokumenterade integrationer.
Se [sessionsgenomgången](crypto-session-review.md).

Velo är MIT-licensierat, Copyright (c) 2026 bjarneo. Licensmeddelandet finns
som referens i `knowledge/references/velo-LICENSE.txt`. Ingen Velo-kod eller
binär körs som runtimeberoende i GG. Den gemensamma TUI-grunden är avsedd att
återanvändas vid fortsatt arbete med andra moduler i GG AI DESKTOP.
