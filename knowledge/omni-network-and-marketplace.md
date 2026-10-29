# GG OMNI och MP – avsikt, genomförande och verifieringsgränser

## Användarens ursprungliga avsikt

CRYPTO och MP ska fungera genom samma logik oavsett nätverk, token, kodspråk
eller anslutningsmedium. GG-20 beskriver delbara tillgångar och GG-721 unika
objekt. Nyttan i MP är ett begripligt kvitto på en vara eller tjänst:
transaktion, ursprung, innehåll och tidigare liv. Bilden hjälper användaren att
känna igen objektet. Den visuella förebilden är KNOWLEDGE:s klickbara cell.

Användaren vill att både små och stora enheter bidrar: mobil, webbläsare,
dator, webbhotell, VPS och radio. Kraftigare enheter ska kunna utföra större
beräkningsuppgifter. Avsändaren ska kunna bifoga bevis för sitt arbete så att
mottagaren gör mindre arbete. Avgifter och faktiska tjänster i GG/MP är
tokenens grund. Rättvisa bidragsersättningar och innehavarincitament ska
undersökas, utan att användningen blir beroende av ett visst nätverk.

## Vad vi upptäckte

MP hade redan material, grundämnen, sammansättningar, Merklebevis och tidigare
liv. Det är ett objekt- och proveniensregister, inte bara en bildmarknad.
Tidigare prisfält och plånboksantaganden var SOL-bundna. Nya priser använder
nätverkskvalificerade tillgångar och heltal som text. Ticker är presentation,
inte identitet. Äldre kvitton behåller sin hashversion; nya objekt använder
identitetsversion 3, där en genererad paper-referens inte ändrar identiteten.

Ett objektpass kan finnas före en affär. Ett transaktionskvitto måste dessutom
beskriva parter, objekt, pris, tid och utfall. Paperköp sparar nu ett separat
kvittounderlag i katalogens atomiskt publicerade tillstånd. Betalning och
leverans anges uttryckligen som simulerad respektive ej verifierad.

En gemensam operation kan ha olika implementering. ERC-721 identifierar ett
unikt objekt med kontrakt och token-ID och har ägar-, behörighets- och
mottagarregler. ERC-1155 beskriver kvantiteter per token-ID och har andra
överföringsregler. De kan därför inte behandlas som samma ägarmodell.
[ERC-721](https://eips.ethereum.org/EIPS/eip-721),
[ERC-1155](https://eips.ethereum.org/EIPS/eip-1155).

Seaport skiljer erbjudna objekt från motprestation och inkluderar bland annat
tidsgränser och räknare. Vi tar med dessa begrepp i vidare orderarbete; den
lokala MP-katalogen är inte en Seaport-implementation eller ansluten börs.
[Seaport-modeller](https://docs.opensea.io/docs/seaport-models).

KRC-721:s indexer tolkar inskriptioner och faktisk transaktionsstruktur.
Listningens UTXO, säljarbetalning och köparutgång har betydelse för avveckling.
Det är inte ett EVM-kontrakt med ett annat namn. Den läsadapter som ingår
kontrollerar nätverk och synkstatus men litar fortfarande på indexern.
[KRC-721-specifikation](https://github.com/Nacho-the-Kat/krc721-protocol/blob/master/doc/KRC-721.md),
[REST-gränssnitt](https://github.com/Nacho-the-Kat/krc721-protocol/blob/master/doc/REST.md).

ERC-2981 ger royaltyinformation i försäljningsprisets enhet. En royaltyoffert
bevisar inte att någon marknad verkställer betalningen.
[ERC-2981](https://eips.ethereum.org/EIPS/eip-2981).

KasMI:s publika produktöversikt och profil visar en bredare marknad med varor,
NFT-hantering och flera plånboksval. Det är UX-underlag, inte verifierat bevis
för dess avveckling, säkerhet eller samtliga integrationer. Inloggning och köp
genomfördes inte. [KasMI](https://kasmi.online/),
[profilöversikt](https://kasmi.online/profile).

EatTheBlocks granskades som utbildnings- och kodreferens via dess README,
inte som en fullständig revision av alla lektioner. StackExchange-trådar om
reflection och transferavgifter användes för att hitta fallgropar. Frågor och
exempelkod är hypotesunderlag, inte produktionsbevis. OpenZeppelins dokumentation
användes för gränssnitt, behörigheter och mottagarkontroller.
[EatTheBlocks](https://github.com/jklepatch/eattheblocks),
[reflection-fråga](https://ethereum.stackexchange.com/questions/162628/how-to-further-improve-safemoons-reflection-token-transfer-erc20-bep20),
[OpenZeppelin ERC-721](https://docs.openzeppelin.com/contracts/5.x/api/token/erc721).

## Beslut som är implementerade

- `omni_assets`: nätverkskvalificerad identitet, exakta belopp, publika konton,
  begränsade register och beständig aktivitetslogg. CAIP-form används där den
  passar. GG:s `native`, Kaspa, TRON, Cardano och labbnamn är privata
  tillägg, inte påståenden om registrerade CAIP-namnrymder.
- `omni_rpc`: publika läsadaptrar för Bitcoin, EVM, Solana, Kaspa, TRON och Cardano.
  RPC-nätverk kontrolleras där protokollet erbjuder en sådan kontroll. TRON
  och Cardano har svagare nätverksbindning i denna version. HTTPS-adresser
  kontrolleras och anslutningen binds till den kontrollerade publika IP-adressen.
  Felaktig läsning markeras; senaste kända saldo ersätts inte med noll.
- `omni_intents` och `schemas/gg-intent.schema.json`: språkoberoende operationer
  och tydliga routningstillstånd. En beskrivning ger ingen behörighet. Saknad
  brygga anges som saknad; den ersätts inte med en påhittad lyckad överföring.
- `marketplace_protocols`: aktiverbara läsmoduler för ERC-721, ERC-1155,
  KRC-721 och ERC-2981. GG-20/GG-721 är kärnkontrakt på applikationsnivå.
  GG-1155 betecknar utgåvor i den semantiska modellen. Inga nya kontrakt har
  publicerats på någon blockkedja.
- MP har ett bildbaserat objektpass med klickbara material-, ursprungs-,
  historik- och transaktionsdelar. Bildimport kopierar en kontrollerad lokal
  rasterfil till privat användartillstånd; bildens innehåll binds till objektet.
  Bilder renderas begränsat och katalogen använder virtuella kort.
- Tjänster har en egen typ. Materialmassa används inte som tjänstemått.
  Deklarerad massa och producentuppgifter är inte oberoende materialbevis.
- Paperbotar använder de befintliga sex strategierna, med egna konton per
  fullständigt tillgångs-ID. Börsparet kontrolleras för generiska Binance-spotpar.
  Tillgångens koppling till börsens ticker är ett uttryckligt användarval.
  Generiska konton kör endast manuellt startade, avgränsade analyssteg.
- CRYPTO, MP och Wallet delar OMNI-vyn. Arbeten visar väntan, utfall och fel.
  Långsamma operationer sker utanför GUI-tråden. MP-utkast sparas vid fel.
- CRYPTO öppnar nu den breda marknadsutforskaren. Global coinlista, native-
  filter, DEX-token, pooler och bevakning leder vidare till gemensam wallet.
  Tolv publika nätverk är förinställda. SOL/KAS-labben har en egen menypost.
  Se [sessionsgenomgången](crypto-session-review.md) för ny research,
  filterbeteenden, verifiering och återstående produktionsarbete.
- MP filtrerar samling, ursprungsnätverk, objekttyp, status, bilder och valuta.
  NFT-källan kan skilja sig från betalningsnätverket. V3-kvittensens identitet
  och tillståndshash kontrolleras vid kataloginläsning.

## Nätverkslabb och bevis

`omni_lab` genomför signerade överföringar mellan fyra lokala deltagare.
Alla får lika stor testtilldelning. Tre av fyra signaturer krävs för ett block.
Saldo, nonce, nätverksidentitet och medskickade Merklebevis kontrolleras.
Historiken kan verifieras genom omspelning. Nycklar finns bara i processens RAM;
efter omstart är sessionen förseglad. En ny session skapas endast på begäran.
Omspelning sker före ny signering. Oberoende avsändare kan förbereda mot samma
nyliga tillstånd; vittnesroten måste finnas bland de 64 senaste verifierade
tillstånden och aktuell nonce och täckning måste fortfarande stämma.

Detta är en signerad laboratoriehuvudbok i **en process**, inte distribuerad BFT,
GHOSTDAG, DAGKNIGHT, produktions-L1 eller ett SNARK-system. Merklebeviset visar
medlemskap i ett tillstånd. Signaturen visar autenticitet. De bevisar inte
godtycklig programkörning. Mina och statelessness-forskning visar relevanta
spår för att skilja dyr bevisproduktion från billigare kontroll.
[Mina](https://docs.minaprotocol.com/mina-protocol),
[Ethereum statelessness](https://ethereum.org/roadmap/statelessness/).

`omni_transport` testar små fragment, omordning, förlust, dubbletter, livslängd,
kvoter per avsändare, global bytebudget och begränsad kö/lagring. Testet kan
skicka om saknade paket. Det är inte en radiodrivrutin, en BPv7-implementation
eller ett bevis på DoS-immunitet. Avsändarens färdiga beräkning tar inte bort
mottagarens kostnad för trafik, lagring och verifiering. Även DTN-protokoll
behöver flödeskontroll. [RFC 9171](https://www.rfc-editor.org/rfc/rfc9171.html),
[libp2p resursbudgetar](https://github.com/libp2p/go-libp2p/blob/master/p2p/host/resource-manager/README.md).

Väntande omförsök går att avbryta och utgångna fragment rensas. Profilbyte
avbryter gamla försök. Inaktiva peerposter släpper sina platser efter två minuter;
inkomna byte redovisas även om paketen inte släpps in i kön.

Mobil/radio/dator/server-profiler styr transportbudget i labbet. Rollnamnen
light/relay/archive/validator/gateway är konfigurerbara testprofiler; de startar
inte separata distribuerade tjänster. Inga belöningar skapas för att bara
deklarera en roll. En snabbare enhet får inte automatiskt större rösträtt.

Avgiftsscenarier jämför bidragspool, burn och innehavaråterföring. Endast den
betalda testavgiften fördelas; heltalsavrundning går till bidragspoolen.
Saldo + pool + burn ska alltid motsvara ursprunglig tilldelning. Det finns
ingen produktionsutgivning, automatisk bidragsutbetalning eller utlovad APY.

## Lätt webbnod

`knowledge/gg-node-web` är ett fristående statiskt webbpaket med IndexedDB-kö,
offlinecache, paus och verifiering av labbets offentliga Merkle-/Ed25519-paket.
Det kan serveras via HTTPS på vanligt webbhotell eller VPS. En sida kan bädda
in det via iframe på samma origin. Paketet startar ingen mining, peer discovery
eller nätverksavveckling. Det har ingen signerarnyckel.

I OMNI/NODE finns Starta lokal webbvy, Öppna webbnoden och Stoppa webbvy.
Appen äger servern, binder till en ledig loopbackport och stänger den vid avslut.
Den serverar bara de sex statiska verifierarfilerna och högst fyra anslutningar
samtidigt. Fristående start: `.venv-windows/Scripts/python.exe tools/serve_omni_node.py`.
Servern binder bara `127.0.0.1:8874`; stoppa med Ctrl+C. I OMNI/NODE kan man
förbereda och kopiera ett offentligt testpaket från en aktiv labbsession.
Klistra in paketet i webbvyn och starta lokal verifiering. Ett nytt block
ändrar tillståndsroten, så ett nytt paket behövs efter det.

Kön är högst 64 meddelanden / 256 KiB, med fem minuters livslängd. Indata
begränsas till 8 KiB per meddelande och 1 MiB per sidöppning och UTC-dag.
Den sistnämnda kvoten är lokal och kan återställas genom omladdning; den är
ingen nätverksbehörighet eller Sybil-resistens. Offlinecachen är ingen garanti
för konstant bakgrundsdrift. Webbläsare och operativsystem kan pausa eller
avsluta processen. Batteriskydd används där webbläsaren exponerar batteristatus.
[Service worker-livscykel](https://developer.chrome.com/docs/workbox/service-worker-lifecycle).

## Antaganden, öppet arbete och bevisnivå

Målet är universella semantiska gränssnitt. Full kompatibilitet med **alla**
nätverk är inte verifierad. Okända nätverk kan representeras i registret men
behöver egna testade adapterimplementationer. Bridges, on-chain-order,
hårdvarusignering, börsorder, produktionskonsensus och verklig radio återstår
som egna integrationer. Ingen credentialsfil behövde läsas för detta arbete.

Nuvarande lokala gränser: 128 nätverk, 2 000 tillgångar, 128 bevakningskonton,
2 000 äldre MP-objekt, 2 000 NFT-bevakningar, 1 024 bilder / 512 MiB bildarkiv,
256 block per aktiv labbsession. Dessa gränser gör försöket förutsägbart; de
är inte genomströmningslöften för ett globalt nätverk.

Verifiering omfattar manipulerade bevis, replay, saknat quorum, exakta belopp,
isolering mellan tillgångar med samma ticker, nätverks- och tokenkontroller,
kvittobindning, paketförlust, överlast, WebCrypto-integration och verklig QML
vid 360/900 px. Katalogtestet har 2 000 poster och färre än 60 skapade kort.
Publika liveprober nådde åtta nätverk; sex gav explicit nätverksidentifiering,
TRON/Cardano gav publika block/tip med lägre identitetsbevis. Liveinspektion
av ett ERC-721- och ett KRC-721-objekt fungerade i läsläge.

REA analyserade webbkärnans JavaScript statiskt. Python granskades i källkod,
AST och tester; detta är inte en REA-analys av hela Pythonprogrammet eller en
extern säkerhetsrevision. Reproducerbara tester finns i `tests/test_crypto_omni.py`
och `tests/test_crypto_omni_ui.py`. Underlaget sparas också i RESEARCH Workbench.
