# Solana wallet, token discovery and explicit transfers

## Ursprunglig avsikt

Användaren vill lämna en walletadress, se sina riktiga tillgångar i GG och
kunna ta emot token. Första konkreta provet är GGHB på Solana: från Phantom
till ett konto i GG och tillbaka. Den gemensamma portföljen ska samtidigt
behålla nätverkskvalificerad identitet för alla sina anslutna konton.

Publika adresser och saldon för det verkliga provet ligger i privat användar-
och teststatus, inte i den distribuerade källan. Tokenets fullständiga mint
kontrolleras; ticker är aldrig en identitet eller signeringsbehörighet.

## Genomfört

- Samma konto- och positionsvy används oberoende av nätverk. En tillgång binds
  till kedja och kontrakt/mint. Konton på olika kedjor slås inte ihop via ticker.
- Solana kan läsa både SPL Token och Token-2022 med `getTokenAccountsByOwner`,
  kontrollera nätverkets genesis, ägare, tokenprogram, mint och decimaler samt
  batchvalidera mintkonton. Mängder hanteras som heltal och exakta strängar.
- Upptäckten begränsas till 512 tokenkonton per program och 128 mintar per
  körning. En överskriden gräns markeras. RPC-fel bevarar tidigare observationer;
  en fullständig lyckad ägarsökning utan tokenkonto kan ge ett verkligt nollsaldo.
- Metaplex-namn hämtas från rätt metadata-PDA och program, med mintkontroll och
  begränsad Borsh-avläsning. Token-2022:s inline-metadata kan också visas.
  Namn är presentation, inte ett ekonomiskt eller kryptografiskt förtroendebevis.
- Ta emot-vyn visar konto, nätverk, mint/kontrakt, full adress, kopiering,
  verkligt saldo och tidsstämpel. Bevakning kan startas/stoppas, läser högst
  var femtonde sekund i tio minuter och stannar när vyn döljs eller minimeras.
  Saldoändring beskrivs som saldoändring, aldrig som ett transaktionskvitto.

## Lokal GG-wallet på Solana

En ny Solana-nyckel kan skapas och lagras krypterad med Windows DPAPI under
aktuell användare. Inga okrypterade nyckel- eller seedfiler skapas. Snapshot,
logg, clipboard och chattexport får bara offentlig metadata. Den äldre
SOL-labbnyckeln migreras eller används inte som mainnet-signerare.

En portabel `.ggwallet`-backup använder scrypt (N=131072, r=8, p=1), AES-256-GCM,
slumpmässig salt/nonce och autentiserad kedja/offentlig adress. Den kontrolleras
genom dekryptering innan backupstatus sätts. Lösenord anges i appen, inte i chatten.
Fel lösenord eller manipulerad backup ersätter inte en fungerande lokal nyckel.
Backup krävs innan lokal sändning kan förberedas. System utan verifierad säker
nyckellagring får ingen okrypterad reservlösning.

Skapande, backup/återställning och sändning använder separata, exakta engångs-
operationer i befintligt TASK_SCOPED-flöde. Vanligt ja/nej i chatten hanteras
direkt av värdappen; operationen skickas inte tillbaka till en modell.
Godkännandet binds till operationens aktuella mål och underlag. Lösenord
stannar i RAM, och en ändrad endpoint, fil eller granskning stoppar åtgärden.
En förberedd överföring är osignerad. Aktuell användares uttryckliga
godkännande krävs för effekten, enligt AGENTS.md. Inga privata nycklar behöver
lämnas till en agent. Ett konto med lokal nyckel kan inte tas bort som vanlig
publik bevakning och därmed gömmas genom det enklare borttagningsflödet.

## Förberedelse och sändning

SOL och vanliga SPL-token har en separat, uttrycklig överföringsadapter.
GGHB-provet använder det vanliga Token-programmet. Token-2022 med särskilda
överföringsregler kan läsas men avvisas av denna sändningsadapter. Det är inte
ett påstående om att alla tokenstandarders överföringar redan stöds.

Förberedelsen kontrollerar konto, nätverk, signerare, exakt belopp, faktiskt
spenderbart tokensaldo, mintprecision, mottagarens tokenkonto, SOL för avgift
och eventuell kontohyra, blockhash, avgiftsuppskattning och simulering. Ett
saknat associerat tokenkonto skapas med den idempotenta ATA-instruktionen.
SPL-beloppet binds med `TransferChecked`. Upp till åtta verifierade källkonton
kan kombineras om saldot är fragmenterat; större fragmentering avvisas.
Mottagare, belopp, mint, avgift och
simuleringsresultat visas före signering och binds till granskningsunderlaget.
Ändrad mottagare, ändrat meddelande eller utgången offert kräver ny förberedelse.

Sändningen kräver fortfarande aktuell behörighet, granskning och matchande lokal
signerare. Det äldre gemensamma RPC-gränssnittet är fortsatt läsbegränsat på
mainnet. Den uttryckliga adaptern sänder högst en gång, med förhandskontroll.
Signaturen sparas före sändning. Timeout efter möjlig acceptans förblir osäker;
den signeras inte om. Ny utgående förberedelse från samma konto blockeras medan
en tidigare sändning saknar verifierat utfall. Användaren kontrollerar signaturen
mot nätverket. Bekräftad/slutlig status visas först efter verkligt RPC-svar.

Om signaturen saknas kan en ny granskning fastställa att giltighetstiden har
passerat: den bundna RPC-källan måste rapportera finaliserad blockhöjd förbi
utkastets `lastValidBlockHeight` och därefter en tillräckligt färsk historisk
signaturkontroll utan träff. Hela genesis och samma endpoint kontrolleras.
Då markeras överföringen som misslyckad/utgången och signaturen bevaras.
Läsfel, gammal kontext, endpointbyte eller saknad äldre bindning lämnar
utfallet olöst. Ett samtidigt bekräftat/slutligt utfall får inte skrivas över.
Detta litar på RPC-källans finalitets- och historieuppgift; det är ingen egen
konsensusverifiering. Ingen automatisk ny signering eller omsändning sker.

För retur från ett nybildat GG-konto behövs SOL där för nätverksavgiften;
ett mottaget SPL-saldo ersätter inte avgiftsvalutan. Den externa Phantom-
walleten behåller sin egen nyckel och används inte som lokal signerare.

## Verifiering

Backendfallen kontrollerar Windows DPAPI på riktigt, krypterad backup och
återställning, fel lösenord/tamper, behörighetskontroll före nyckelgenerering,
exakt tokenupptäckt, metadataidentitet, utgången/ändrad granskning, återspelning,
osäkert sändningsutfall och det äldre läsbegränsade RPC-gränssnittet.

En riktig LiteSVM kör signaturverifierade SPL-överföringar fram och tillbaka
med ett separat testmint med sex decimaler, inklusive ATA-skapande, samt en
native SOL-överföring. Detta är ett isolerat VM-prov, inte mainnetkonsensus.
Qt-provet använder kontrollerade fixturer för mottagarsaldo, kopierbar adress,
scrollning, dold bevakning och den nya walletvyn. Publika mainnet-prober har
läst den uppgivna GGHB-minten och Phantomadressen utan signering eller sändning.

## Återstående gränser

Portföljens gemensamma format innebär inte universell automatisk tokenupptäckt.
EVM:s registrerade ERC-20 kan läsas; full upptäckt behöver en indexeradapter.
Andra nätverksfamiljers tokenstandarder behöver motsvarande verifierade adaptrar.
Den egna GG-huvudboken är fortsatt ett lokalt labb i en process. En distribuerad
nod, produktionskonsensus och verifierade crosschain-bryggor är separata arbeten.
Att en tillgång visas i samma UI flyttar inte dess värde mellan kedjor.

## Primärkällor

- [Solana transfer instructions](https://solana.com/docs/tokens/basics/transfer-tokens)
- [Solana getTokenAccountsByOwner](https://solana.com/docs/rpc/http/gettokenaccountsbyowner)
- [Metaplex metadata state](https://github.com/metaplex-foundation/mpl-token-metadata/blob/main/programs/token-metadata/program/src/state/metadata.rs)
- [Associated token account instructions](https://github.com/solana-program/associated-token-account/tree/main/interface/src)
- [Windows CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- [Phantom transaction signing](https://docs.phantom.com/solana/sending-a-transaction)
