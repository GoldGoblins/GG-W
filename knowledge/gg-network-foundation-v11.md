# GG nätverk och terminal — verifierad lokal grund

## Ursprunglig avsikt

Användaren vill ha ett riktigt GG-nätverk, lättillgängliga konton och tillgångar,
marketplace samt samma funktioner i en äkta terminal på Windows, Linux och en
Android-telefon med Termux. Målet är hög kapacitet och låg resurskostnad utan att
offra korrekta överföringar, kontroll av mottagare eller tydlig visuell struktur.
En snygg skärm eller ett snabbt utvecklings-RPC räcker inte som nätverksbevis.

## Genomfört

- Hardhat-adaptern återanvänder sin egen HTTP-anslutning, batchar enbart läsningar
  och kontrollerar svarens exakta identiteter. Sändningar återförsöks aldrig
  automatiskt. Kedja, genesis, kontraktskod, nonce, granskning och kvitton granskas.
- Fyra separata CometBFT 0.40.0-processer kör en egen GG-testhuvudbok över lokal
  P2P. Fyra lika viktade, statiskt kända validatorer kräver minst tre signaturer.
  Testkonton och validatorer har separata nycklar. Ed25519 använder etablerade
  bibliotek, med byte-för-byte-test mot befintligt Solana-SDK.
- Exakta heltalsbelopp, signaturer, genesis, kedja och nonce kontrolleras. Fast
  utbud är 1 000 000 GG-NET-TEST, sex decimaler, fyra testkonton. Ingen gasavgift
  finns i denna begränsade native-huvudbok. Tillgången är skild från GGHB.
- Ett transaktionskvitto kräver SDK-verifierad inkludering och återspelning av
  hela blocket mellan certifierade före- och eftertillstånd. Tillstånd efter H
  förankras korrekt i header H+1. Ett redan kontrollerat block återanvänds för
  dess övriga exakta transaktionsbytes; cache får inte korsa genesis eller rådata.
- Belastningstest skickar oberoende signerade förfrågningar i pipeline men
  räknar endast unika verifierat slutförda överföringar. En olöst blockfront
  bevakas i taget för att undvika att varje väntande medlem frågar efter samma
  ännu saknade certifikat. Ingen signatur- eller saldokontroll tas bort.
- Feltest visar framsteg med en stoppad validator, utebliven finalisering med
  två stoppade, återhämtning av samma redan signerade transaktion och bevarat
  offentligt anti-dubbelsigneringsläge vid återstart. Nycklar lagras bara i RAM.
- Desktop har ett eget VALIDATORER-läge under NÄTVERK, samma godkända
  Obsidian/Ledger-proportioner, verkliga mätningar, konton, granskning och sidopanel.
  EVM-testnätet och det äldre enprocesslabbet finns kvar som tydliga separata lägen.
- En nyckellös WASM-klient kör samma CometBFT-kontroller i webbläsaren. GG låser
  genesis/validatorer från sin egen session innan ett paket läses. Ett paket får
  inte välja sitt eget förtroendeankare. Ett giltigt historiskt saldo märks med
  höjd; kontrollen bevisar inte att det är det senaste saldot.
- `gg-cli.py` startar en verklig prompt_toolkit-TUI med wallet, marketplace och
  nätverk. Listor, tangentbord, formulär, sökning, sidopaneler och textgrafer är
  terminalceller. Inga Qt-, webview-, Pillow- eller Rust-SDK-beroenden behövs för
  bevakning och det lokala nätverket. Ingen periodisk tom omritning används.
- CLI använder samma publika saldo-/tokenadaptrar, katalog, objektpass och
  transaktionslogik. Marketplace är fortfarande lokala objekt och paperkvitton,
  med publika samlingsreferenser; ingen verklig säljorder eller cross-chain-brygga.
- Wallet erbjuder bevakning, mottagaradress, saldon, tokenimport, GG-testbetalningar
  och valfri riktig Solana-adapter. Den senare kräver separat solders-SDK,
  krypterat valv, verifierad backup, låst granskning och exakt mänskligt ja.
  Windows använder DPAPI; POSIX använder scrypt-131072-8-1 och AES-256-GCM med
  dolt lösenord för en operation. Befintliga krypterade backupformat bevaras.
  Lösenord och nycklar accepteras inte i kommandoargument eller kommandologg.

## Uppmätt och verifierat

Windows: Ryzen 7 7735HS, 8 kärnor/16 trådar, 15,2 GiB RAM, pågående desktoplast.
Alla siffror nedan är små lokala observationer, inte maximal eller uthållig
kapacitet. Human granskning ingår inte i aktiva transaktionsmätningar.

| Test | Aktiv genomströmning | Median / p95 | Vad som kontrolleras |
|---|---:|---:|---|
| EVM före optimering, ERC20, 20 st | 1,654/s | cirka 600 / 720 ms | Hela prepare/send-flödet |
| EVM efter optimering, ERC20, 20 st | 32,110/s | 31,611 / 33,204 ms | Samma kontroller, kanoniskt kvitto |
| EVM efter optimering, native, 20 st | 34,734/s | 28,893 / 30,294 ms | Samma kontroller, kanoniskt kvitto |
| GG fyra validatorprocesser, 32 st | 40,273/s | 714,981 / 725,539 ms | Klientens SDK-verifierade finalisering |
| GG fyra validatorprocesser, 128 st | 90,728/s | 986,835 / 1257,802 ms | Klientens SDK-verifierade finalisering |

GG-tabellens TPS använder hela benchmark-API-anropets väggtid. Inklusive start,
kontroll och stopp blev motsvarande 32-/128-test 11,640 respektive 39,925/s.
128-testet kontrollerade tre transaktionsblock, 128 unika överföringar och exakt
sluttillstånd. Slutavläst privat nodminne var cirka 321 MiB totalt för fyra
processer; verifierarprocesser och Python ingår inte i det minnesmåttet.
EVM och BFT gör olika arbete och deras värden får inte beskrivas som samma finalitet.

WASM-verifieraren är cirka 30,5 MiB. En faktisk exporterad saldobild verifierades
i isolerad Chromium på cirka 210 ms; WASM linjärt minne var 19 MiB, exklusive
webbläsarens och JavaScripts övriga kostnad. Detta är ingen kostnadsfri eller
generell ZK/SNARK-verifierare.

Verklig Linux/amd64-testning kördes i en separat Podman-VM/container på samma
fysiska dator: ren installation utan Qt, sju nätverks-/felkontroller, krypterad
wallet create/backup/restore, filrättighet 0600, hemlighetskontroll och MP-objektpass.
Containerns cgroup-gränser var inte tillgängliga i den befintliga VM:n; ingen
verifierad Linux-resursisolering påstås. Windows behåller verifierade Job-gränser.

## Beslut, antaganden och kvarstående frågor

Beslut: bygg på etablerad konsensus och signaturer, mät verkliga kvitton och håll
presentation skild från kryptografiska garantier. Lätta klienter verifierar
certifikat och kontobevis; de blir inte automatiskt validatorer eller extra TPS.

Antagande: en fast, enoperatörs lokal miljö är rätt första teststeg när användaren
bara har en dator. Linux-VM är ett plattformstest, inte geografisk decentralisering.
Fler maskiner för en validator innebär inte fler oberoende validatorer.

Kvarstår: riktiga oberoende maskiner/operatörer, nätfördröjning och bandbredd,
Byzantinska fel utöver stopp, offentlig medlemsmodell, ekonomiska incitament,
arkiv/state sync, säker nyckeldrift, mobil energiförbrukning och längre belastningar.
Sharding, generell parallell exekvering, betalningskanaler och trustless bryggor
är inte implementerade och inget test här visar att GG överträffar publika
Solana, Kaspa eller Lightning.

Android/arm64 är korskompilerat men inte kört på en riktig telefon. En upstream
Android-länkbegränsning kräver det dokumenterade kompatibilitetsvalet
`-checklinkname=0`, endast i Android-bygget; kvitto och README markerar detta
experimentellt. SDK-signeringens Rust-bygge i Termux behöver också enhetstest.
Androids spärr för `/proc/net` hanteras med en begränsad publik readiness-rad
direkt från exakt ägd barnprocess, endast vid nekad kernelavläsning. Windows
behåller kernelkontrollen, och alla saldon/kvitton kräver fortfarande certifikat.

Källpaket för tre plattformar skapas av `support/gg-cli/build_release.py`.
Inget GitHub-push eller release-publicering sker genom byggverktyget.

## Återskapa

Se [terminalens installation och kommandon](../support/gg-cli/README.md) och
[konsensusmotorns beroenden och säkerhetsgränser](../support/gg-consensus/README.md).
`support/gg-consensus/benchmark.py --engine hardhat` respektive
`--engine consensus --count 32` startar endast egna nya testnoder och stoppar dem.
`gg-cli.py --command network.test --json` gör ett ändligt lokalt feltest och
stannar noderna; en vanlig TUI-session behåller nätverket tills användaren avslutar.

Primära upstreamkällor finns i motorns README och låsta Go-moduler. GUI:t kan
startas utan något nodverktyg installerat. Ingen motornedladdning eller nodstart
sker automatiskt när programmet öppnas.
