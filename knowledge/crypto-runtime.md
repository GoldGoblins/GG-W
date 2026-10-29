# CRYPTO: LIVE, lokala labb och verifiering

Granskning och implementation: 2026-10-27.

Användarens mål var att gå igenom hela CRYPTO, undersöka aktuella lösningar och
säkerhetsforskning, få Kaspa och Solana att fungera i LIVE och LOCAL LAB samt
förbättra både användarupplevelsen och AI:ns arbetsflöde.

## Användning

Välj SOL eller KAS i portföljen. Knappen **ANSLUTNING** i sidhuvudet öppnar
anslutningspanelen. Där väljer du **LIVE · läsläge**, **LOCAL LAB** eller Kaspas
**PAPER**. Panelen visar datakälla, anslutningskontroll, tidpunkt, svarstid och
aktuellt slot-/DAA-värde. Uppdateringsknappen begär en ny kontroll. Tidigare
resultat markeras inaktuella medan nytt underlag hämtas.

LIVE läser verkliga nätverksdata. Solanas nätverksidentitet kontrolleras med
genesis hash och nodens hälsostatus. Kaspa kontrolleras mot huvudnätets
block-DAG. En Kaspa-adress kan läggas till för bevakning; format, version,
padding och checksumma kontrolleras före lagring. Ett adressfel skiljs från
ett anslutningsfel. Ett simulerat KAS-saldo visas aldrig som huvudnätets saldo.

**LOCAL LAB för Solana** använder en installerad native validator om den finns.
Annars används den verifierade LiteSVM-versionen på Windows. Den kör riktig
SVM-transaktionsvalidering, inklusive signaturer, blockhash och avgifter.
Testfinansiering, simulering, överföringar, saldon och signaturstatus stöds.
Publika kontotillstånd sparas atomiskt och återställs när VM:n startas igen.
En VM deltar inte i validatornätverkets konsensus; tidigare signaturhistorik
och blockhashar gäller endast den aktuella VM-körningen.

**LOCAL LAB för Kaspa** startar en egen kaspad v2.1.0 i simnet, med loopback-
adresser, avstängd DNS-seeding/UPnP och separat datakatalog. Nodens verkliga
nätverk och wRPC-svar kontrolleras. Programmet stoppar endast en process vars
exekverbara fil, argument, datakatalog och skapandetid stämmer med dess kvitto.
En befintlig omärkt ledger tas inte över. Simnet startar utan automatisk mining.

**PAPPERSLABB för Kaspa** är en separat Counter-simulering. Dess steg är
pappershändelser även när en nod körs. SilverScript v1.0.0 kompilerar den lokala
källan till riktig bytekod; bytekod och källa sparas med ett gemensamt kvitto.
Ändrad källa gör kompileringen inaktuell. Kompilering innebär inte att en
covenant har distribuerats eller körts på kedjan.

Grafens diskreta öppna-ikon förstorar grafen inom arbetsytan. Stäng-ikonen
eller Escape återgår till portföljen. Kontroller har tangentbordsfokus,
förklaringar vid hovring och neutral färgsättning.

## Fynd och ändringar

- Tidigare saknades fungerande Kaspa-nodanslutning bakom nätverksvalen.
  Den gamla HTTP-adressen till en gRPC-port har ersatts av rätt wRPC JSON-väg.
- En lokal Python-namnrymd med namnet `kaspa` räknades felaktigt som ett SDK.
  Det krävs nu en verklig `RpcClient` för den indikatorn.
- Windows kunde inte använda den konfigurerade Linux-validatorn. En lokal
  Solana VM finns nu som uttryckligt alternativ, med separata statusuppgifter.
- Counter-källans äldre syntax kompilerade inte. Den är rättad, och resultatets
  byte-array tolkas korrekt. Ett tomt eller felaktigt artefakt kan inte ge OK.
- Solana-diagnostik kräver exakt 32 bytes för nyckel/blockhash och jämför
  RPC:ns svarssignatur med den faktiskt skickade transaktionens signatur.
  Ett tvetydigt svar orsakar ingen automatisk omsignering.
- Sena hälsosvar efter labbstopp förkastas. Kontroller samordnas, har tids- och
  storleksgränser och körs utanför Qt-tråden. Start av labbet aktiverar inte en
  handelsstrategi. Den native Solana-validatorns trådantal är begränsat.

## Underlag och avgränsning

Python-koden strukturgranskades med AST: samtliga crypto-/kaspa-moduler,
importer och symbolintervall indexerades. Kritiska anslutnings-, nyckel-,
transaktions-, lagrings- och UI-vägar undersöktes särskilt. REA kördes på
CRYPTO:s JavaScript-formattering. REA stöder inte den här Python-backenden;
inventeringen och testerna ska inte beskrivas som en fullständig REA-graf
eller en extern säkerhetsrevision.

Den breda offline-sviten omfattar samtliga `test_crypto*.py`, Kaspa-covenant och
Polymarket. Den inkluderar även befintliga tester för backtest, kostnader,
orsaksriktighet, prisdata, paper-konton, Pump-kontovalidering, UI och cache.
`tools/verify_crypto_runtime.py` gör separata verkliga publika läsanrop samt
lokala VM-, nod-, saldo-, signatur-, kompilerings- och omstartskontroller med
tillfälliga testkonton. Resultat sparas i RESEARCH och den privata arbetsloggen.
Användarens riktiga nycklar eller plånbok behövs inte för dessa kontroller.

## Källor och principer

Solanas dokumentation beskriver RPC-hälsa och behovet av WSL för dess vanliga
Windows-installation. Detta motiverar ett separat portabelt labbalternativ.
[Installation](https://solana.com/docs/intro/installation),
[getHealth](https://solana.com/docs/rpc/http/gethealth).

Solders beskriver LiteSVM som en lokal exekveringsmiljö och skiljer den från en
full RPC-validator. Windows-hjulet 0.29.0 verifierades här genom faktisk
transaktionskörning; plattformsstödet antogs inte enbart från dokumentationen.
[LiteSVM](https://kevinheavey.github.io/solders/tutorials/litesvm.html).

Kaspa v2.1.0:s release och implementation användes för nodversion, wRPC,
adressformat och aritmetiska gränser. Runtime-paketen kontrolleras mot fixerade
SHA-256-värden före installation i användarens appdata.
[Rusty Kaspa v2.1.0](https://github.com/kaspanet/rusty-kaspa/releases/tag/v2.1.0),
[adressformat](https://github.com/kaspanet/rusty-kaspa/blob/v2.1.0/crypto/addresses/src/bech32.rs).

Counter-syntax och artefaktformat kontrollerades mot den riktiga kompilatorn
och projektets egna språkfixturer.
[SilverScript v1.0.0](https://github.com/kaspanet/silverscript/releases/tag/v1.0.0).

Neodymes publicerade Solana-granskningar betonar bland annat kontots ägare,
signering, programidentitet och heltalsgränser. De principerna användes vid
jämförelsen med GG:s befintliga kontotester och vid de nya gränskontrollerna.
Detta är ett urval av relevanta förstahandskällor, inte ett påstående om att
alla forskare eller alla publika revisioner har granskats.
[Neodyme: Common Pitfalls](https://neodyme.io/en/blog/solana_common_pitfalls/).

## För AI och installation på en ny dator

Gemensam diagnostik finns i `backend/crypto_connections.py`; läs snapshotfält
för aktuell valuta och nätverk. Tolka aldrig `loading`, saknat saldo eller
inaktuell observation som en aktuell framgång. Kaspa- och Solana-labb har
skilda livscykler. `testnet` är den äldre interna inställningsnyckeln för de
lokala labben, inte ett påstående om anslutning till ett publikt testnät.

Python-beroenden finns i `requirements.txt`. Officiella Windows-paket installeras
med programmets Python och `tools/install_crypto_runtime.py`, respektive samma
kommando med `--compiler`. Ingen uppgradering av befintliga publika noddatabaser
eller operativsystemsförändring ingår. `config/dependencies.json` beskriver
versioner, källor och omfattning. Hemligheter hör aldrig hemma i rapporter,
kommandoradsargument, källfiler eller testloggar.
