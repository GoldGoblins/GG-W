# CRYPTO, wallet, MP och GG-nätverket – sessionsgenomgång 2026-10-27

## Ursprunglig avsikt

Användaren vill ha en sammanhängande marknad, wallet och marketplace som kan
beskriva och använda tillgångar från många nätverk. Huvudflödet ska likna en
kombination av en bred coinlista och en DEX-utforskare: coin → nätverk → token
→ kontrakt → handelspool. SOL och KAS ska inte vara hela produktens gränssnitt.
GG-20/GG-721 ska uttrycka gemensam logik. Marketplace ska visa begripliga,
visuella objektpass och transaktionskvitton för varor och tjänster.

Det egna nätverket ska kunna utvecklas mot små, resurssnåla deltagare i
webbläsare, mobiler och servrar, även över svaga förbindelser. Avsändaren ska
kunna förbereda beräkningar och bevis. Bidrag, användning och rimlig tokenekonomi
är målet; synliga knappar, reglage, status och aktivitet ska göra funktionerna
begripliga för användaren.

## Fakta och fynd

Den tidigare gemensamma OMNI-delen fanns, men CRYPTO:s första sida och walletens
första flöde var fortfarande SOL/KAS-orienterade. Det gjorde den bredare
funktionen svår att upptäcka. MP hade redan material, ursprung, tidigare liv,
bilder och kvitton men saknade flera användbara katalogfilter.

En token behöver en identitet med nätverk och referens. Samma ticker kan
beskriva flera helt olika tillgångar. En CoinGecko-post, ett tokenkontrakt och
en DEX-pool är olika objekt. DEX Screener anger `priceUsd` för poolens
**bastoken**; priset får inte återanvändas för dess quotetoken.
[DEX Screener API](https://docs.dexscreener.com/api/reference).

CMC100 är ett definierat index, inte en lista över alla nätverks native coins.
GG:s globala lista använder därför CoinGeckos publika börsvärdesordning och en
separat native-klassificering från leverantörens plattformsmetadata. Den gör
inte anspråk på att replikera CMC100:s indexportfölj. Klassificeringen är
leverantörsdata, inte ett verifierat adapterstöd för varje kedja.
[CMC100-metodik](https://s3.coinmarketcap.com/uploads/CoinMarketCap_100_Index_Methodology.pdf),
[CoinGecko markets](https://docs.coingecko.com/reference/coins-markets).

Jupiters token-API och OpenSea API har dokumenterade nyckelkrav. Inga sådana
nycklar hämtades eller lagrades. CMC:s provade publika indexanrop gav 429.
De tjänsterna används som dokumenterade förebilder; de är inte påstådda live-
integrationer i denna ändring.
[Jupiter tokeninformation](https://github.com/jup-ag/docs/blob/main/docs/tokens/token-information.mdx),
[OpenSea API](https://docs.opensea.io/reference/api-overview).

## Beslut som är genomförda

| Del | Beteende i implementationen | Verifiering |
| --- | --- | --- |
| Marknaden | Förstasida i CRYPTO. Global lista, native coins, DEX-token, bevakning och registrerade tillgångar. Sökning på namn, symbol eller offentlig adress. | Publika liveanrop och verklig QML med kontrollerade testdata. |
| Flera led | Coin-detalj visar stödda nätverksvarianter; DEX-detalj visar kontrakt och pooler. Import kräver exakt referens och RPC-kontroll. | Samma ticker på Ethereum/Base förblir två tillgångar. Quotetoken får inte fel baspris. |
| Filter | Nätverk, börsvärde, volym, förändring, likviditet och prissatt/oprissatt. Global lista med 100 poster per sida, upp till 50 sidor. | Sortering, paus, cache, källfel, skilda adressers söknycklar. |
| Uppdatering | Synlig hämtning, källstatus, äldre pris, paus och manuellt försök. Synlig marknad uppdateras med 30/120 sekunders intervall. Minimerad vy gör inga timerstyrda publika uppdateringar. | Bakgrundskö, sammanslagna statusanrop och paus utan nätverksanrop. |
| Diagram | CoinGeckos verkliga prispunkter; DEX har lokalt observerade punkter. Inga fabricerade OHLC-ljus. | Felaktiga/futuristiska tidsstämplar och motstridiga punkter avvisas. |
| Wallet | Gemensam positionslista för offentliga bevakningskonton. Exakta mängder och nätverksfilter, saldo/kontouppdatering, kopiera adress och aktivitetslista. | Heltal över JavaScripts säkra talområde förblir exakta. Saknat saldo/pris blir inte noll. |
| Värdering | Endast uttryckligen bunden tillgång och färskt pris + färskt verifierat saldo räknas. Saknade värden och delsumma framgår. | Ingen koppling via ticker. GG-labb räknas separat från USD-värdet. |
| Nätverksregister | Tolv förinställda publika nätverk: Bitcoin, Ethereum, BSC, Polygon, Arbitrum, Base, Optimism, Avalanche, Solana, Kaspa, TRON och Cardano. | Bitcoin genesis/adresskontroll; EVM chain ID; tidigare probes och nya publika identitetsprober. |
| MP-katalog | Sökning och filter för samling, ursprungsnätverk, varor/tjänster, status, prisvaluta och bilder. Prissortering bara inom samma valuta. | Exakt strängjämförelse av basenheter, även över 2^53. Virtuell katalog för 2 000 poster. |
| NFT-koppling | Objektpass kan ange ERC-721/ERC-1155/KRC-721 på ett annat nätverk än prisets. Referensen kan öppnas i NFT-inspektorn. | Referensen binds till v3-identiteten. Ändrat kvitto avvisas vid inläsning. Deklaration är inte ägarbevis. |
| GG-labb | Fyra lokala deltagare med Ed25519, Merkle-vittnen, nonce och 3/4 blocksignaturer. Oberoende avsändare kan utgå från samma nyliga verifierade rot. | Omspelning före signering; manipulerat saldo, replay och äldre rot avvisas. Rotfönster: 64 verifierade tillstånd. |
| Svag transport | Begränsade fragment, kvoter, paketförlust, saknade-paket-omförsök, utgång och avbryt. Inaktiva peers släpper sina platser. | Inkomna byte räknas före godkännande. Utgång/avbryt rensar väntande delar. |
| Webbnod | Befintlig statisk verifierare med offlinecache, begränsad kö och paus/batterihänsyn. | Tidigare WebCrypto-prov mot Python-genererade paket. Ingen mining eller peer discovery införs här. |

Äldre SOL/KAS-labb och strategiverktyg finns under en egen menypost. Äldre
privata nycklar eller lokala SVM-konton kopieras inte automatiskt till offentliga
bevakningskonton. Mainnet-skrivning förblir beroende av en explicit signerande
adapter och befintliga behörighetskontrakt.

Tokenimport är verifierad för EVM och Solana. Native-saldoläsning på övriga
listade nätverk innebär inte automatiskt stöd för deras alla tokenstandarder.
Saknad importadapter visas som otillgänglig. Walletens förberedda positionslista
begränsas till 2 048 poster och visar antal utelämnade positioner som delsumma;
den bygger inte en obegränsad produkt av konton och registrerade tillgångar.

## Research och användbar inspiration

- GMGN/BullX: sökning med kontraktsadress, kedjefilter, token → analys/pooler,
  och tydlig skillnad mellan upptäckt och riskbedömning.
  [GMGN introduktion](https://docs.gmgn.ai/index/quick-start),
  [BullX Explore](https://bullx.gitbook.io/bullx-neo-docs/finding-tokens/explore-page).
- MetaMask/Phantom: samlad wallet, tillgångshantering och uttrycklig anslutning.
  [MetaMask flera nätverk](https://support.metamask.io/manage-crypto/tokens/how-to-view-your-token-balance-across-multiple-networks/),
  [Phantom provider](https://docs.phantom.com/solana/detecting-the-provider).
- OpenSea: samling, nätverk och objekt som skilda navigeringssteg.
  [OpenSea discovery](https://docs.opensea.io/docs/search-and-discovery).
- Bitcoin: separat bekräftat saldo och mempoolförändring; Base58Check,
  Bech32 och Bech32m kontrolleras enligt adressversion.
  [mempool REST](https://mempool.space/docs/api/rest),
  [BIP-350](https://github.com/bitcoin/bips/blob/master/bip-0350.mediawiki).

REA användes för statisk analys av `MarketFormat.js` och `MarketplaceBrowse.js`.
Rapporter och avgränsade publika textkällor sparas i RESEARCH Workbench.
Python/QML kontrollerades genom källgranskning och exekverbara tester. Inga nya
native-binärer infördes; Ghidra användes därför inte för denna källändring.
Detta är inte en oberoende säkerhetsrevision av externa börser, wallets eller
samtliga deras repositories. Publika nyckelkrävande tjänster kringgicks inte.

## Antaganden och återstående genomförande

En gemensam tillgångsvy låter användaren se olika kedjors tillgångar tillsammans.
Den flyttar inte originalkedjans värde till GG. En backad representation behöver
en verifierbar låsning/utgivning/inlösen, en definierad tillitsmodell och riktiga
signerare. Någon sådan brygga har inte implementerats eller publicerats.

GG-labbet är fortfarande en huvudbok i **en process**, med sessionsnycklar i
RAM. Det är ingen driftsatt distribuerad blockkedja. Produktion kräver bland
annat peer discovery, konsensus över opålitliga noder, återhämtning/forks,
beständig säker nyckelhantering, liveness/Sybil-motstånd och externa tester.
Innehavaråterföring/burn/bidragspool finns som begränsade avgiftsscenarier;
ingen produktionstoken eller utlovad avkastning har skapats.

Förberäknade bevis minskar visst mottagararbete. De eliminerar inte inkommande
trafik, minne och verifieringskostnad. Resursbudgetar behövs fortfarande.
Radioförsöket är en lokal transportmodell, inte verifierad verklig radiotrafik.
Webbläsare och mobiloperativsystem kan pausa en bakgrundssida.

Börsorder, hårdvaruwalletsignering, reala MP-köp och automatiserad avveckling
behöver separata verifierade integrationer. Publika API:er kan begränsa eller
stoppa sina svar; då visar GG fel/ålder och behåller senaste kända data.
Testresultat visar den avgränsade implementationens beteende och är ingen
garanti för felfri drift eller universell kompatibilitet.

## Reproducerbar kontroll

Kör med projektets Python:

```powershell
.venv-windows\Scripts\python.exe tests/run_crypto_checks.py
.venv-windows\Scripts\python.exe -m unittest tests.test_marketplace_contract tests.test_kaspa_covenant
```

Den nya flödeskontrollen finns i `tests/test_crypto_explorer.py` och
`tests/test_crypto_explorer_ui.py`. UI-kontrollen laddar verklig QML och verklig
bakgrundsruntime med kontrollerade publika svar. Skärmbilderna i verifierings-
underlaget är testdata, inte livekurser eller verkliga innehav. Samlade resultat,
publika prober och Workbench-verifiering sparas privat i appens runtime-underlag.
Gränssnittsändringarna laddas vid nästa vanliga appstart.
