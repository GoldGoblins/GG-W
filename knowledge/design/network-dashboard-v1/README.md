# GG NÄTVERK: koncept och fungerande testmiljö

## Ursprunglig avsikt

Användaren vill ge NÄTVERK samma genomarbetade struktur som CRYPTO, Marketplace
och Wallet: ett tydligt koncept, riktiga mätningar och grafer, små lättillgängliga
kontroller och en användbar informationspanel. GG ska utvecklas till ett eget
nätverk. Första steget ska provas med Ganache/Truffle eller en motsvarande
etablerad testmiljö, enligt ett praktiskt deploya–överför–verifiera-flöde.

## Fynd

Det tidigare GG-labbet har riktiga Ed25519-signaturer, Merklebevis, exakta belopp,
nonce, tre-av-fyra-blocksignaturer och verifierbar historik. Deltagarna delar en
process och är inte distribuerade noder. Transportdelen är ett lokalt,
resursbegränsat fragmenttest. Dessa egenskaper ska vara kvar och visas korrekt.

Truffle och Ganache är avvecklade. Hardhat är en etablerad ersättare och används
även i EatTheBlocks vägledning. Det ger en körbar lokal EVM med riktiga kontrakt,
transaktioner, gas, block och RPC-kvitton. EVM-utvecklingsnoden ersätter inte
framtida GG-konsensus eller nätverksadaptrar för andra protokoll.

## Beslut och implementation

- NÄTVERK öppnar **GG TESTNÄT**. **SIGNERAT LABB** finns bredvid. Båda bor direkt
  i den befintliga arbetsytan. Ingen ny fönsterram täcker innehållet.
- Två frysta imagegen-koncept: `concept-testnet.png` och `concept-lab.png`.
  Exakta prompter finns i `prompt-testnet.txt` respektive `prompt-lab.txt`.
  Siffrorna i koncepten är exempel; programmet importerar dem aldrig.
- Native Qt-kontroller, små knappar, exakta saldosträngar och tunna raka regler.
  Huvudyta cirka 72 procent och separat rullbar informationspanel cirka
  28 procent. Smala fönster använder en riktig sidolåda. Sidopanel-knappen
  fungerar även i nätverksvyerna.
- Grafer visar högst 32 uppmätta lokala operationer. Staplar representerar
  separata anrop; inga mellanliggande mätningar eller konstgjorda trafikvågor
  läggs till. Tom historik visar en tom graf. Budgetstaplar visar verkliga
  värden och gränser, inte påhittad genomströmning, CPU-belastning eller ping.
- `backend/gg_testnet.py` äger en separat Hardhat-process på en ledig
  `127.0.0.1`-port. Endast kedja 31337 tillåts. Processägarskap, genesis,
  kontolista och kontraktets körbara bytekod kontrolleras innan användning.
- Fyra slumpmässiga tillfälliga testkonton får utvecklingsmedel. Nycklar
  kommer inte från användarens wallet och skrivs inte till filer eller loggar.
  Hardhats råa konsolutdata kopplas till null redan vid processens start.
- **Deploya testtoken** deployar standard-ERC20 från OpenZeppelin med fast
  utbud 1 000 000 **GG-TEST**, sex decimaler och utan extern mint, ägare,
  överföringsskatt eller uppgraderingsmekanism. Det är inte Solana-tokenen GGHB.
- Överföringar får en oföränderlig tvåminutersgranskning med källa, mottagare,
  tillgång, exakt belopp, nonce och högsta gasavgift. Engångssändningen binds
  till hela underlaget. Ändrat tillstånd avvisas. Osäker sändning upprepas inte.
- **Kör fram och tillbaka** genomför fyra faktiska överföringar mellan
  testkontona: GG-TEST ut och tillbaka samt native DEV ut och tillbaka. Varje
  kvitto binds till rätt transaktion och block; både kontonas exakta saldoändring
  och gasavgiften kontrolleras. Tokenutbudet och återställt tokensaldo verifieras.
- Läsfel behåller äldre värden med tydlig felstatus och blockerar sändning.
  Stopp förstör nodens tillfälliga tillstånd. Nästa start får nya konton.
  En terminal avslutsspärr förhindrar försenad bakgrundsstart efter appavslut.
- Windows har verifierad Job Object-gräns: 512 MiB, 300 sekunders ackumulerad
  process-CPU, en process och automatisk stängning när ägarprogrammet dör.
  Detta är resursbegränsning, inte en fullständig OS-sandlåda.
  Andra plattformar rapporterar uttryckligen att denna Windows-gräns saknas.
  Sidopanelen visar faktiskt privat processminne och ackumulerad CPU-tid mot
  dessa gränser. Ingen procentuell momentan CPU-belastning uppskattas.
- Labbet har fått riktiga mätserier, begränsad block-/kööversikt och exakt
  bevarandekontroll. Verifieringen avvisar nu motstridiga kedje-ID:n och ändrade
  fasta genesisparametrar. Befintliga giltiga labbblock stöds fortsatt.

## Installation och verifiering

Verktygskedjan är installerad för denna arbetsstation. På en ny installation
körs det uttryckliga valfria installationsskriptet med projektets Python:

```text
.venv-windows/Scripts/python.exe support/gg-testnet/install_toolchain.py
```

Paket installeras från sina ursprungliga distributörer under aktuell användares
GG-verktygskatalog. Källpaketet innehåller låsta versioner och publik bytekod,
inte node_modules, privata konton eller nodtillstånd. Installationshjälpen i vyn
är läsbar information; en saknad verktygskedja installeras inte i bakgrunden.

Reproducerbara kontroller finns i `test_gg_testnet_contract`,
`test_gg_testnet_service`, `test_gg_testnet_process`, `test_network_lab_metrics`
och `test_network_dashboard_ui`. UI-evidens använder isolerade exempeldata;
ekonomiska kontroller kör en faktisk tillfällig Hardhat-nod. Resultat sparas
under `.runtime/network-dashboard-v10/`, utanför distributionspaketet.

Hardhats aktuella Zod 3-beroende har en kvarstående DoS-advisory. Detaljer och
den kompatibla tmp-patchen finns i `support/gg-testnet/README.md`. Varken
resursgränserna eller testerna innebär att beroendet är säkerhetsreviderat.

## Gränser och fortsatt arbete

Detta är ett fungerande **lokalt testnät**, inte en publicerad GG-mainnet.
Hardhat kör en EVM-utvecklingskedja, inte ett distribuerat konsensusnät.
Det finns inga P2P-peers, radiointegrationer eller verifierade cross-chain-bryggor
i testnoden. Inga riktiga medel har flyttats och inga användarnycklar har lästs.

Jämförelser med etablerade nätverk kräver separata tester av oberoende noder,
fel/partitioner, återhämtning, nätverksidentitet, långvarig drift, lagring,
uppgraderingar och mätt prestanda. Stöd för flera kedjor behöver fortsatta
testade läs-/signerings-/avvecklingsadaptrar; ett gemensamt gränssnitt räcker
inte för att göra alla protokoll utbytbara. GG-20/GG-721 på applikationsnivå,
avgiftsmodellen i labbet och den här ERC20-testtokenen är olika lager.

## Källor

- [Consensys om avvecklingen av Truffle/Ganache](https://consensys.io/blog/consensys-announces-the-sunset-of-truffle-and-ganache-and-new-hardhat)
- [EatTheBlocks: lokal Hardhat-nod och deployment](https://eattheblocks.com/getting-started-with-hardhat-smart-contract-framework/)
- [Hardhat: lokal utvecklingsnod](https://hardhat.org/docs/guides/development-node)
- [Hardhat: konfiguration](https://hardhat.org/docs/reference/configuration)
- [OpenZeppelin: ERC20](https://docs.openzeppelin.com/contracts/5.x/erc20)
- [CometBFT: konsensus och modellens förutsättningar](https://github.com/cometbft/cometbft/blob/main/spec/README.md)
