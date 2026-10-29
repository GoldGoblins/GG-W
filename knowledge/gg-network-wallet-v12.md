# GG nätverk, wallet och portabel återställning

Senare layout-, pris-, färg- och DAG-arbete beskrivs i
[v13-underlaget](gg-network-wallet-v13.md). Den här texten bevarar v12-baslinjen.

## Användarens avsikt och förtydliganden

Utgå från användarens komposit och den fungerande crypto-/marketplace-stilen.
Placera GG NÄTVERK i ramen bredvid CRYPTO. Gör arbetsytan överskådlig med verkliga
mätvärden, blockrelationer, begränsade listor och fasta informationsgrupper.
Wallet ska ha valbara tokenfärger och en proportionell fördelningsbåge.

Prisuppslag gäller de tillgångar användaren faktiskt har eller följer, med
nätverk och adress som identitet. Manuell uppdatering är standard; en statusvy
ska inte skanna nätverk eller ständigt fråga efter priser.

Det slutliga walletkravet skiljer mellan eget och AI-assisterat kontoflöde,
användningsrollen Trading/Förvaring samt hur nyckeln förvaras. Papperswallet är
standard och skild från AI-wallet. Ägaren ska kunna återställa på en annan dator
utan bindning till GG-konto, maskin eller AI. För AI-wallet ska ägaren kunna
låsa upp återställningsorden lokalt igen. Det tidigare förslaget om en permanent
enhetsspärr är därför inte en del av implementationen.

## Levererad implementation

- Nätverksytornas långa huvud-/sidopaneler är ersatta med fasta ytor och
  anpassade grupper. Långa transaktions-, konto- och händelselistor rullar i
  sina egna ytor. På små skärmar väljs informationsgrupp med flik eller väljare.
- Blockgrafen visar verkliga hash-/parent-länkar och valbara sju efterföljare.
  Noder återanvänds och vektorer ritas med QtQuick.Shapes. Inga grafiktimers,
  Canvas-bitmappar eller 60 Hz RPC-anrop behövs. Klick på en mätstapel väljer
  dess verkliga block när en verifierbar observation finns.
- Paletten delas av desktopens gränssnitt och native-terminalen. Tokenpricken
  erbjuder 16/32/64 färger, sparade per nätverkskvalificerad tillgång. Samma färg
  används i bågen. Oprissatta tillgångar får ingen påhittad procentandel.
- Trading/Förvaring filtrerar lista, exakt total och båge. Flytt mellan egna
  konton väljer en registrerad mottagare på samma nätverk och använder befintlig
  granskning. Det är ingen automatisk signering eller brygga.
- Generell prisväg använder faktiskt registrerade innehav/favoriter med delad
  60-sekunderscache, max 64 tillgångar och begränsade anrop. Källa, tidpunkt,
  likviditet, kvalitet och äldre data följer med noteringen.
- Ny wallet får 12 eller 24 engelska BIP39-ord, numrerad engångsvisning och tre
  slumpvis valda ordkontroller. Standard är PAPER, 24 ord och Trading.
  Ingen tidsgräns finns medan ägaren skriver.
- PAPER sparar endast offentlig adress och uppsättningsmetadata. Efter Nästa
  rensas ordlistans egna buffertar; bara tre saltade ordkontroller behålls tills
  provet är klart. Ingen privat signeringsnyckel eller frasfil publiceras.
- AI använder befintligt krypterat lokalt nyckelvalv och en separat portabel,
  lösenordskrypterad BIP39-återställning. Nyckelägaren kan visa orden privat,
  exportera krypterad återställning och återställa samma adress på annan dator.
- Hemliga ord/lösenord skickas inte i OMNI-status, chatt, terminalhistorik eller
  vanlig JSON-utdata. Återvisning använder privat Qt-/TTY-väg och ett nytt
  avgränsat godkännande. GG:s bild- och textinsyn spärras medan orden visas.
  Återvisningen töms vid stängning, navigering och minimering.
- Native-terminalen erbjuder samma PAPER-/AI-skapande, dold frasåterställning,
  privat ordvisning och krypterad export. Enter/Esc stänger den privata ytan
  före capture-spärren släpps. `--json` har ingen ordvisningsyta. En uttrycklig
  walletuppdatering prissätter valda kontons native-tillgångar och positiva
  positioner; vanlig status och uppstart gör inga prisanrop. Kärnan kräver inte Qt.

## Faktiska gränser

Nuvarande motortyper är Hardhat EVM-kedja, fyra lokala CometBFT-processer och
signerat enprocesslabb. Ingen ny BlockDAG- eller hybridkonsensus är införd.
Renderingens bildfrekvens är inte block/s. Testgrafens native-mätning gav
93,59 FPS i snitt, median 8,852 ms och p95 30,903 ms på 165 Hz-skärm; detta är
inte en garanti om varje bild inom 16,7 ms eller om hela appens bildfrekvens.
Programmet har inte verifierats klara ett absolut RAM-tak på 200–300 MiB.

Generell tokenprissättning är konkret kopplad till sju konfigurerade EVM-kedjor,
Solana och TRON; de befintliga native-priskällorna behålls för övriga registrerade
nätverk. Pump-fallbacken gäller verifierbara direkta SOL-/USDC-kurvor. Inte alla
lanseringsplattformar eller godtyckliga nätverk har adapter. Slutkontrollen av
minten `6TY5cDkAD3BN5L8MEXAcd2LysxWRAiji8TJSHUBapump` gjorde sex publika läsanrop,
alla HTTP 200, med färska verkliga USD-ankare. DEX-/Gecko-vägen gav inget
kvalificerat pris. Pump-kontots ägare/discriminator och mainnet-genesis
verifierades, men den första decodern avvisade dess historiska151-byte layout.
Detta är nu rättat mot officiellt SDK4.1.0, tillsammans med kontrollen av
legitimt bränt mintutbud. En ny tre-anropskontroll gav en positiv, tidsstämplad
`BONDING_CURVE_SPOT`-notering från verifierade reserver. Historik finns i
`.runtime/token-market-public-acceptance-v12.json`, rättad kontroll i
`.runtime/network-v13-price-acceptance.json`. Det bevisar inte kurstillgång för
alla andra Pump-tokens; se [prisdefinitionerna](token-market-pricing.md).

Ny BIP39-nyckel/adress och befintlig lokal signering gäller för närvarande
Solana, med SLIP-0010-sökvägen `m/44'/501'/0'/0'`. Återställning måste använda samma
sökväg. Ledger/Tangem och andra externa adresser kan bevakas och ta emot;
direkt enhetssignering är inte implementerad eller verifierad. AI-assisterat
är ett uttryckligt kontoflöde, inte en obegränsad fullmakt: varje verklig
överföring följer fortfarande befintligt avgränsat användargodkännande.

Senare ordvisning gäller bara wallets som faktiskt skapats/återställts med
lagrad mnemonicåterställning. Äldre eller importerade råa signerarnycklar har
ingen ursprunglig BIP39-fras som GG kan rekonstruera automatiskt; nya ord som
skulle återställa en annan adress uppfinns aldrig. PAPER lagrar inga ord, så
ägaren återställer från sin egen papperskopia. Metoderna är användarvalda och
innebär ingen bindning till ett GG-konto eller en viss AI.

Krypterat lokalt valv använder OS-/lösenordsskydd enligt plattform. Den portabla
frasen använder scrypt-131072-8-1 och AES-256-GCM med kedja, adress och sökväg som
autentiserad metadata, utan maskin-/GG-kontobindning. Återställningsord ger
ägarskap även utanför GG. Python/Qt kan inte lova fysisk radering av alla
oföränderliga RAM-kopior; egna buffertar rensas och referenser tas bort. GG:s
capture-spärr skyddar egna vägar, inte andra program, kamera eller RAM-forensik.

## Underlag och kontroll

[Konceptbild](design/gg-network-wallet-v12/concept.png) ·
[bildspecifikation](design/gg-network-wallet-v12/prompt.txt) ·
[blockmätningar](gg-block-telemetry.md) · [prisdefinitioner](token-market-pricing.md) ·
[terminalpalett](gg-terminal-palette.md) · [capture-gräns](sensitive-ui-capture-boundary.md).

Tester använder disponibla noder, isolerade användarrötter och publicerade
BIP39/SLIP-0010-testvektorer. Inga verkliga användarfraser, privata nycklar eller
finansierade wallets användes. GitHub-publicering har inte utförts.

Den färska slutkörningen omfattade 316 utvalda tester, med två avsiktliga
plattformshopp, samt 31 syntetiska capture-/metadata-kompatibilitetstester.
Åtta ytterligare Linux/amd64-kontroller verifierade PAPER skapande/återställning,
portabel fraskryptering, fel lösenord och POSIX-spärr i en tillfällig miljö
utan nätverk under walletproven. Där laddades inte Qt, Solders eller Pillow.
Linux AI-signerpublicering och fysisk Termux-telefon ingick inte.

Det nya CLI-mnemonicflödet och privata native-terminalytor har verifierats på
Windows. Den tidigare Linux/amd64-baslinjen omfattade noder, äldre krypterad
backup/restore och marketplace. Det nya mnemonicflödet är ännu inte verifierat
på Linux eller fysisk Termux-enhet; Windowsprov ersätter inte dessa kontroller.

Primärkällor: [BIP39](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki),
[SLIP-0010](https://github.com/satoshilabs/slips/blob/master/slip-0010.md),
[Trezor python-mnemonic](https://github.com/trezor/python-mnemonic),
[Ledger Solana-signerare](https://developers.ledger.com/docs/device-interaction/dmk-ts/references/signers/solana).
