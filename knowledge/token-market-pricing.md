# Riktade tokenpriser från publika källor

Användaren vill se priser även för tokens som saknas i CoinGeckos vanliga
katalog, på alla nätverk där det finns en tillförlitligt identifierad källa.
Samtidigt ska GG bara fråga efter faktiska wallet-positioner, sparade favoriter
eller en uttryckligen vald tillgång. Ingen global tokenskanning införs.

## Faktisk prisväg

Walletens tidigare prisväg använde bara kopplingar mellan tillgångsregistret och
`crypto_explorer`. En upptäckt SPL-mint utan en sådan koppling kunde därför
förbli oprissatt även om en publik DEX-pool fanns.

En manuell uppdatering kan nu använda följande avgränsade vägar:

1. Befintlig giltig CoinGecko-koppling eller en uttryckligt konfigurerad native-
   tillgångsidentitet. Ett färskt giltigt aggregatpris prioriteras.
2. DEX Screener med exakt nätverk och tokenadress. Bara base-tokenens USD-pris
   används; en token som enbart förekommer som quote får inte ärva basens pris.
   Den giltiga poolen med högst rapporterad USD-likviditet väljs. Små pooler
   döljs inte: under 1 000 USD märks priset `LOW_LIQUIDITY`. Noll/saknad
   likviditet märks `UNKNOWN_LIQUIDITY`.
3. GeckoTerminal som publik, nätverks-/adressbunden reservkälla. Tokenpostens
   nätverksprefix, adress och typ kontrolleras. Det är ett provideraggregat,
   inte ett separat påstående om en verifierad eller exekverbar pool.
4. För en ofullständig Pump-kurva på Solana: härledd PDA, huvudnäts-genesis,
   programägare, discriminator, mintkonto, supply, decimals och quote-mint
   kontrolleras genom de befintliga bundna RPC-läsningarna och protokolldecodern.
   Endast direkt SOL-/USDC-parning stöds. SOL/USDC behöver ett verkligt färskt
   USD-pris; USDC antas inte alltid vara exakt en dollar. Både bas- och quote-
   mintens verkliga decimals kontrolleras. Resultatet är en indikativ kvot av
   virtuella reserver, `VIRTUAL_RESERVE_SPOT_NOT_EXECUTABLE`, utan påhittad
   likviditet eller löfte om ett försäljningspris.

En giltig tidigare quote behåller sitt ursprungliga as-of vid fel/429. En
misslyckad ny läsning gör aldrig priset noll och uppdaterar inte dess färskhet.
Kända gamla eller framtida provider-tidsstämplar förblir inaktuella även om
HTTP-svaret precis hämtades. Provider utan egen uppdateringstid får uttryckligen
`timestamp_basis: FETCH_OBSERVATION`, inte en uppdiktad marknadstidsstämpel.

## Faktiskt inkopplade nätverk

| Nätverk | Tokenpriser via adress | Native-pris |
|---|---|---|
| Ethereum, Base, Optimism, Arbitrum One | DEX Screener / GeckoTerminal | Konfigurerat ETH-provider-ID |
| BNB Smart Chain, Polygon, Avalanche C-Chain | DEX Screener / GeckoTerminal | Befintliga explicita CoinGecko-ID:n |
| Solana | DEX Screener / GeckoTerminal; begränsad Pump-kurvadapter | CoinGecko, kanonisk WSOL-referens som indikativ reservkälla |
| TRON | DEX Screener / GeckoTerminal | Befintligt TRX-provider-ID |
| Bitcoin, Kaspa, Cardano | Ingen ny generell token-/launchpad-adapter | Befintliga BTC/KAS/ADA-provider-ID:n |
| Andra användarregistrerade nätverk | `NETWORK_ADAPTER_UNAVAILABLE` tills en specifik adapter verifierats | Ingen identifiering genom tickernamnet |

Detta är inte ett löfte om pris för varje token på varje kedja. En obevakad,
inaktiv eller olistad marknad, en okänd quote-kedja och en provider som saknar
data förblir oprissatt. GMGN-sidor skrapas inte och inga autentiserade API:er,
hemligheter, handels-/signeringsvägar eller nya protokoll gissas fram.

## Budget, tillstånd och gränssnitt

`backend/token_market_prices.py` erbjuder `quote(chain_id, reference)` och
`quotes([(chain_id, reference), ...], anchors=...)`. Identiteten inkluderar alltid
kedjan. Samma EVM-adress på två kedjor är två separata cacheposter; Solana- och
TRON-adresser behåller skiftlägeskänsligheten.

Ett riktat jobb tillåter högst 64 tillgångsidentiteter och 12 käll-/RPC-anrop i
tokenadaptern. Adresser batchas högst 30 per nätverk. Pump begränsas till 32
kurvor och en korrelerad kontobatch med basmint, PDA och stödda quote-mints.
Den befintliga CoinGecko-batchen är separat och omfattar bara efterfrågade
provider-ID:n. Inga globala listor behöver hämtas för dessa värderingar.

RAM-cachen har högst 256 poster och återanvänds mellan wallet och favoriter.
Positiva och negativa resultat har minst 60 sekunders återanvändning.
GeckoTerminal har minst sex sekunder mellan anrop, i linje med den försiktigare
aktuella publika dokumentationen om cirka tio anrop/minut och en minuts cache.
429 respekterar en numerisk Retry-After inom en begränsad 60–3 600-sekunders
backoff. Ingen ny pollingtråd, timer, redirect eller automatisk retry införs.

Transporten accepterar bara de två fasta publika HTTPS-källorna, kontrollerar
och pinnar publik DNS-adress, verifierar TLS, använder fyra sekunders HTTP-
timeout och högst 2 MiB svar. Dubbla JSON-nycklar och NaN/Infinity avvisas.
Decimalexponenter begränsas också före formatering för att ett kort skadligt
`1e-999999999` inte ska orsaka en enorm strängallokering.

`crypto_explorer.refresh_wallet_quotes()` sparar nätverkskvalificerade observationer
i `wallet_quotes` utan att skapa nya tillgångar eller ändra marknadens
navigation. `refresh_favourites()` läser endast verkligt sparade stjärnposter.
`omni_wallet.snapshot()` gör inga pris-/RPC-anrop. Den lämnar förberedda fält:

- `price_source`, `price_observed_at`, `price_source_timestamp`
- `price_quality`, `liquidity_usd`, `price_basis`
- `price_stale`, `price_reason` och `price_policy.mode: MANUAL_ONLY`

Det vanliga statusdraget får inte starta ett prisjobb. Valfri minutuppdatering
behöver uttryckligen hanteras av den synliga, relevanta vyn; backend startar
aldrig en sådan loop själv. Fiatvärdering kräver fortsatt färskt saldo, kända
decimals och giltigt färskt pris. Ett pris är separat från ägande, signeringsrätt
och genomförbar handel.

## Verifiering och det konkreta användarexemplet

Offlinetester omfattar exakta kedje-/adressidentiteter, quote-tokenförväxling,
likviditetsurval, låg/okänd likviditet, gamla och framtida as-of, 429, original-
tidsstämpel, batchning, cacheåteranvändning, ingen HTTP vid upprepade statusdrag,
endast sparade favoriter, HTTP/DNS/TLS-/svarsgränser, Pump-kurvor och befintliga
CoinGecko-prisers företräde.

Den 29 oktober 2026 kontrollerades Solana-minten
`6TY5cDkAD3BN5L8MEXAcd2LysxWRAiji8TJSHUBapump` först med ett DEX-anrop som gav
HTTP 200 och noll pooler. Den slutliga, isolerade acceptanskontrollen gjorde
sex publika läsanrop: CoinGecko, DEX Screener, GeckoTerminal, mainnet-genesis och
två kontobatcher. Alla gav HTTP 200. Verkliga färska USD-ankare fanns, men inget
kvalificerat exakt-mint-pris kunde hämtas från DEX-/Gecko-vägen.

Den första implementationen avvisade felaktigt den historiska **151-byte**
allokeringen som ett trasigt fält. Den officiella `@pump-fun/pump-sdk` 4.1.0,
`src/sdk.ts` (`decodeBondingCurve`), beskriver uttryckligen denna version och
nollutfyllning till dagens 166 byte. Decodern stöder nu just den dokumenterade
allokeringen; andra okända halvfält och oväntade längder avvisas fortsatt.

Det andra felet var kravet att mintens aktuella utbud måste vara exakt lika
med kurvans ursprungliga utbud. SPL-burn minskar mintutbudet utan att ändra
kurvans prisreserver. Nu krävs ett positivt återstående utbud högst lika med
ursprunget, med verkliga reserver högst lika med återstående och virtuella
reserver. Inflation, tom mint, fel ägare, avslutad kurva och syntetisk
efter-migrationshandel avvisas fortfarande.

En ny kontroll gjorde **tre publika läsningar**: färskt SOL/USD hos CoinGecko,
mainnet-genesis och en kontobatch. Minten gav då en verifierad reservnotering
på cirka **0,00000307286147 USD**, slot 462790122, med kvalitet
`BONDING_CURVE_SPOT`. Det är en indikativ marginalnotering från virtuella
reserver, inte ett genomförbart försäljningspris för hela innehavet. Pris och
tidpunkt följer med resultatet; siffran är ingen permanent kurs.

Ett manuellt tokenuppslag kan hämta de två kända omräkningsankarna SOL och USDC
i samma begränsade CoinGecko-batch även om native SOL inte finns bland de valda
innehaven. Ingen $1-peg antas. Favoriter använder samma explicita ankare och
cache. Statusvisning hämtar fortfarande ingenting.

Inga användarregister ändrades och inga transaktioner skickades. Den tidigare
avvisningen finns kvar som historisk evidens i
`.runtime/token-market-public-acceptance-v12.json`; den godkända kontrollen finns
i `.runtime/network-v13-price-acceptance.json`. En fryst offentlig kontofixtur
och offlinetester verifierar att exakt denna mint når walletens värdering utan
ett separat SOL-innehav. Detta lovar inte att varje annan marknad har en kurs.

Primärkällor: [DEX Screener API](https://docs.dexscreener.com/api/reference),
[GeckoTerminal Public API och aktuell OpenAPI](https://api.geckoterminal.com/docs/index.html),
[GeckoTerminal OpenAPI-specifikation](https://api.geckoterminal.com/docs/v2/swagger.json),
[officiella Pump-protokolldokument](https://github.com/pump-fun/pump-public-docs),
[officiellt Pump SDK 4.1.0](https://www.npmjs.com/package/@pump-fun/pump-sdk/v/4.1.0).
