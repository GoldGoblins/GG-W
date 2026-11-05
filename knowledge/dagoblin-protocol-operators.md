# DAGoblin: operatörsceremoni för ett privat TESTNET

Målet är fyra riktiga SDK-väljare på Windows/Linux och en separat Termux-klient
som kan verifiera kvitton, skicka kontotransaktioner och arbeta åt en pool.
Varje väljare har en egen skyddad ägare, validerarprofil, nodnyckel och
governancekonto. Producerinbjudningar anger den verkliga ägaren, noden, plattformen
och belöningskontot. Ett förslag eller en pools andel är inte ett certifierat block
eller en nätverksbetalning; kvitton måste verifieras mot samma genesis.

Detta är ett TESTNET-recept. Fyra väljare på två datorer ger två fysiska
felområden. Två väljare på samma dator gör inte datorerna till fyra oberoende
felområden. Termux LIGHT har ingen rösträtt och är ingen registrerad blockskapare.
En långsam worker bidrar i sin takt och behövs inte för väljarnas kvorum.

## Förutsättningar och offentliga filer

Använd sammanhängande uppdaterade CLI- och nativepaket. Kör exemplen från
GG-källroten med `python gg-cli.py`, eller motsvarande installerade CLI-startare.
Kör skyddade profilkommandon i en riktig terminal **utan `--json`** så att den
ordinarie lösenordsdialogen fungerar. Lägg aldrig lösenord eller seed i kommandot,
JSON, dokumentationen eller en överförd fil. Varje profil skapas lokalt på sin
egen dator; kopiera endast de offentliga exporter som kommandona skriver.

Exemplen använder en redan skapad katalog `ceremony` och illustrativa privata
LAN-adresser. Välj datorernas faktiska adresser, LAN-intervall och lediga portar.
Flytta offentliga filer mellan datorerna med den redan etablerade
bootstrapöverföringen. Inget här kräver en ny överföringsmetod.

| Väljare | Dator | Ägarprofil | Validerarprofil | Ägarport | P2P-port |
| --- | --- | --- | --- | --- | --- |
| Windows A | 192.168.1.10 | WinA | WinVoteA | 47001 | 47101 |
| Windows B | 192.168.1.10 | WinB | WinVoteB | 47002 | 47102 |
| Linux A | 192.168.1.20 | LinuxA | LinuxVoteA | 47001 | 47101 |
| Linux B | 192.168.1.20 | LinuxB | LinuxVoteB | 47002 | 47102 |

Alla filutskrifter kräver ett nytt filnamn och befintlig föräldrakatalog.
Symboliska länkar och Windows-junctions avvisas. Signerade offentliga dokument
ska behålla sina exakta exporterade bytes; omformatera dem inte i en editor.
Policyexemplet får däremot vara indragen JSON och valideras strikt utan dubblettfält.

## 1. Skapa gemensam kontext och oberoende lokala profiler

Skapa kontext **en gång** och dela samma offentliga fil till båda datorerna:

```text
python gg-cli.py --json --command "protocol.context_create path=ceremony/context.json"
```

Kommandot skapar en ny offentlig TESTNET-identitet och startar ingen nod.
För ett redan specificerat sammanhang stöds `spec_path` med exakt schemat
`gg.protocol.context-spec.v1`: `schema`, `chain_id`, `network_id`,
`genesis_time_unix`, `environment=TESTNET`.

Skapa följande på Windows för A. Upprepa på respektive dator med tabellens andra
profilnamn, adress och portar; ägar- och governanceprofiler ska vara självständiga.

```text
python gg-cli.py --command "protocol.owner_create profile=WinA label=WindowsA host=192.168.1.10 port=47001 allowed_cidr=192.168.1.0/24"
python gg-cli.py --command "protocol.validator_create owner_profile=WinA profile=WinVoteA label=WindowsA p2p_port=47101"
python gg-cli.py --command "protocol.validator_invite_export profile=WinVoteA path=ceremony/win-a-validator.json"
python gg-cli.py --command "protocol.initial_producer_export owner_profile=WinA profile=WinVoteA context_path=ceremony/context.json producer_slot=0 label=WindowsA platform=windows path=ceremony/win-a-producer.json"
```

`validator_create` öppnar angiven `owner_profile` och skapar eller öppnar det lokala
governancekontot. Utan `account_profile` heter det `gov_` följt av validerarprofilen
(långa namn förkortas deterministiskt). `validator_invite_export` skriver fyra
verkliga ägar-/konto-/nod-/validerarsignaturer. `initial_producer_export` använder
den egna ägarens producentplats 0 eller 1, validerarens nod och governancekontot;
plattformen är `windows`, `linux`, `termux` eller `other`. Ägaren måste vara ny
för den första exporten. En redan bunden profil får bara återexportera sin exakt
tidigare accepterade inbjudan. Exemplet registrerar fyra producenter, en per väljare.

Samla de fyra validerarinbjudningarna och fyra producentinbjudningarna tillsammans
med kontextfilen hos den som sammanställer genesis. Inga skyddade profiler följer med.

## 2. Välj uttrycklig testpolicy och sammanställ genesis

Granska och kopiera
[`protocol-testnet-policy.example.json`](../support/dagoblin/protocol-testnet-policy.example.json)
till exempelvis `ceremony/policy.json`. Det är en fullständig **testpolicy** med
enkla arbetströsklar för ändliga funktionstester, inga mainnetparametrar eller
påståenden om optimal ekonomi, hashrate eller säker prestanda.

Policyn anger alla ekonomifält och alla nio protokollgränser; verktyget fyller inte
i monetära standardvärden. Detta recept kräver `max_accounts="4294967296"`,
`initial_voting_power="1"` och
`allocation_rule="EQUAL_INITIAL_GOVERNANCE_ACCOUNTS"`. Den initiala tillgången
delas exakt lika mellan **unika** initiala governancekonton. Med fyra olika
konton och exempelpolicyn blir det 250000000000 atomära enheter per konto.
En odelbar totalsumma avvisas; ingen rest flyttas till ett annat konto.
Noll initial tillgång ger en tom allocationslista, aldrig nollbalansposter.

```text
python support/dagoblin/prepare_protocol_ceremony.py --context ceremony/context.json --validator-invite ceremony/win-a-validator.json --validator-invite ceremony/win-b-validator.json --validator-invite ceremony/linux-a-validator.json --validator-invite ceremony/linux-b-validator.json --producer-invite ceremony/win-a-producer.json --producer-invite ceremony/win-b-producer.json --producer-invite ceremony/linux-a-producer.json --producer-invite ceremony/linux-b-producer.json --policy ceremony/policy.json --output ceremony/genesis-spec.json
python gg-cli.py --json --command "protocol.genesis_assemble spec_path=ceremony/genesis-spec.json path=ceremony/pin.json"
python gg-cli.py --json --command "protocol.genesis_review path=ceremony/pin.json"
```

Receptverktyget kontrollerar offentliga signaturer, kontext, identiteter, portar,
policy och exakt fördelning. Det öppnar inga profiler, anropar inga processer,
startar inget nätverk och utfärdar inget konsensuscertifikat. Alla argumentvägar
tolkas från katalogen där verktyget körs; receptfilen innehåller absoluta sökvägar.
Sammanställ därför receptet lokalt där indatafilerna finns. Det kräver nytt
utdatafilnamn och skriver kanonisk JSON med `O_EXCL` utan överskrivning.

`genesis_assemble` läser schemat `gg.protocol.genesis-file-spec.v1`, validerar den
färdiga publika v7-genesis med den installerade nativekärnan och skriver pinfilen.
`genesis_review` upprepar nativevalideringen och visar initialt tillstånd och antal
väljare/producenter. `certificate_asserted=false` betyder att genesisgranskningen
inte påstår att ett SDK-block redan är certifierat.

## 3. Alla initiala operatörer accepterar samma genesis

För över samma offentliga `pin.json` till varje dator. Varje operatör granskar den
och skriver sin egen acceptans med sin egen skyddade ägare, väljare och
governancekonto. Kör exempelvis för Windows A och upprepa för de övriga tre:

```text
python gg-cli.py --json --command "protocol.genesis_review path=ceremony/pin.json"
python gg-cli.py --command "protocol.genesis_endorse owner_profile=WinA profile=WinVoteA pin_path=ceremony/pin.json path=ceremony/win-a-acceptance.json"
```

Acceptansen binder de egna profilerna till denna genesis innan signaturerna
exporteras. Använd inte samma profiler för en annan genesis. Samla alla fyra
acceptansfiler hos sammanställaren och förbered bootstrapreceptet:

```text
python support/dagoblin/prepare_protocol_ceremony.py bootstrap --pin ceremony/pin.json --validator-invite ceremony/win-a-validator.json --validator-invite ceremony/win-b-validator.json --validator-invite ceremony/linux-a-validator.json --validator-invite ceremony/linux-b-validator.json --endorsement ceremony/win-a-acceptance.json --endorsement ceremony/win-b-acceptance.json --endorsement ceremony/linux-a-acceptance.json --endorsement ceremony/linux-b-acceptance.json --output ceremony/bootstrap-spec.json
python gg-cli.py --json --command "protocol.bootstrap_assemble spec_path=ceremony/bootstrap-spec.json path=ceremony/bootstrap.json"
python gg-cli.py --json --command "protocol.bootstrap_review path=ceremony/bootstrap.json"
```

Bootstrapreceptet har exakt `schema=gg.protocol.bootstrap-file-spec.v1`,
`pin_path`, `validator_invite_paths` och `endorsement_paths`. Verktyget kräver
samtliga initiala väljares fyra signaturer på exakt samma pin; den faktiska
CLI-sammanställningen upprepar både signaturkontroller och nativevalidering.
Den färdiga offentliga bootstrapfilen kan nu delas med datorerna och mobilen.

## 4. Skapa telefonklient och autentiserad relay

Skapa först en egen lokal ägare på Termux med `protocol.owner_create` och
telefonens faktiska privata LAN-adress/lediga ägarport. Skapa därefter LIGHT från
den färdiga bootstrapfilen:

```text
python gg-cli.py --command "protocol.client_create owner_profile=Phone profile=PhoneLight bootstrap_path=ceremony/bootstrap.json label=Termux role=LIGHT path=ceremony/phone-client.json"
python gg-cli.py --command "protocol.account_create profile=PhonePay label=PhonePayments"
python gg-cli.py --command "protocol.account_export profile=PhonePay path=ceremony/phone-account.json"
```

Klientkortet signeras av telefonens verkliga nod och ägare och har ingen rösträtt.
Det skapas efter bootstrap och måste överföras tillbaka till relayoperatören för
den uttryckliga allowlistan. Kontokortet innehåller bara den offentliga adressen
och en signatur. En faktisk kontotransaktion krävs för att ge telefonkontot medel;
klientkort, poolandelar och UI-räknare skapar ingen balans.

Windows A exporterar sin signerade relayadress (här en separat ledig port):

```text
python gg-cli.py --command "protocol.relay_endpoint_export owner_profile=WinA profile=WinVoteA bootstrap_path=ceremony/bootstrap.json host=192.168.1.10 port=47201 path=ceremony/relay.json"
```

För över den offentliga relayfilen till Termux. Inga lyssnare startas av exporten.
En LIGHT-startplan kräver `endpoint_path` med detta signerade kort; servernyckeln
får inte ersättas med ett godtyckligt värde.

## 5. Förbered lokala planer och kör ändligt i foreground

`protocol.start_plan` skriver en ny katalog med `bootstrap.json`, `settings.json`
och `run.json`; det startar inget. Följande väljarplan utan `options_path` startar
sedan konsensus utan automatisk produktion/mining/pool:

```text
python gg-cli.py --command "protocol.start_plan owner_profile=WinA profile=WinVoteA bootstrap_path=ceremony/bootstrap.json role=VALIDATOR output_dir=ceremony/win-a-run"
python gg-cli.py --foreground --command "protocol.run path=ceremony/win-a-run/run.json"
```

Gör motsvarande lokala plan för var och en av de fyra väljarna och kör dem i fyra
terminaler. Planerna använder respektive signerad P2P-adress, verkliga nodnyckel
och de andra väljarnas offentliga inbjudningar. `run.json` har schemat
`gg.protocol.operator-start.v1`. Före start öppnas skyddade profiler och samma
bootstrapbindning kontrolleras; inget testfixture väljer nycklar eller genesis.
Ctrl+C stoppar processen. Detta skapar ingen bakgrundsdaemon.

Noderna kan startas i valfri ordning. Begärda pooler, relay, mining och
kontosubmissioner väntar på ett verkligt verifierat certifikat innan de startas
exakt en gång. `protocol_network.operator_start` visar `NODE_STARTED`,
`WAITING_FOR_CERTIFICATE`, `READY` eller `FAILED`; startväntan är begränsad till
120 sekunder och kan avbrytas. En startad nod är alltså inte ensam bevis på att
kvorum bildats eller att ett block certifierats.

För ett ändligt producent-/poolprov kan Windows A i stället skapa en ny plan med
`options_path=ceremony/win-a-options.json`. Spara följande offentliga utkast som
`ceremony/win-a-options-draft.json`:

```json
{
  "account_profiles": ["gov_WinVoteA"],
  "producer": true,
  "mining": {"producer_slot": 0, "duration_seconds": 60},
  "pools": [{"pool": "TestPool", "account_profile": "gov_WinVoteA", "operator_source_path": "win-a-validator.json", "commission_bps": 100, "create": true}],
  "relay": {"endpoint_path": "relay.json", "client_card_paths": ["phone-client.json"], "policy": {"accept_accounts": true, "pool": "TestPool", "producer_slot": 0}}
}
```

Skriv den kanoniska indatafilen med befintlig offentlig exportfunktion, utan
överskrivning (utkastet innehåller inga hemligheter):

```text
python -c "import json; from pathlib import Path; from backend.gg_protocol_setup import write_public; write_public('ceremony/win-a-options.json', json.loads(Path('ceremony/win-a-options-draft.json').read_text(encoding='utf-8')))"
python gg-cli.py --command "protocol.start_plan owner_profile=WinA profile=WinVoteA bootstrap_path=ceremony/bootstrap.json role=VALIDATOR options_path=ceremony/win-a-options.json output_dir=ceremony/win-a-pool-run"
python gg-cli.py --foreground --command "protocol.run path=ceremony/win-a-pool-run/run.json"
```

Stoppa Windows A:s tidigare foregroundprocess innan poolplanen körs; samma
skyddade ägarprofil kan inte leasas av två processer samtidigt.

`operator_source_path`, relaykortet och klientkortet löses relativt optionsfilen.
Den offentliga operatörsadressen hämtas från den signerade källan. Kommissionen
ovan är ett explicit testval. `create=true` använder `protocol.pool_ensure`: en
ny bok skapas, eller en existerande bok öppnas endast om operatör, avgift och
övriga bindningar stämmer. Den återställs inte automatiskt. Inkomster måste
komma från certifierat nätverkstillstånd och bestå efter kall omstart.

Telefonens plan kan först göras utan workerjobb:

```text
python gg-cli.py --command "protocol.start_plan owner_profile=Phone profile=PhoneLight bootstrap_path=ceremony/bootstrap.json role=LIGHT endpoint_path=ceremony/relay.json output_dir=ceremony/phone-run"
python gg-cli.py --foreground --command "protocol.run path=ceremony/phone-run/run.json"
```

För ett ändligt workerprov anges en separat kanonisk optionsfil, skapad från
ett offentligt utkast med samma exportfunktion, med exempelvis
`{"account_profiles":["PhonePay"],"pool_work":{"account_profile":"PhonePay","duration_seconds":60,"attempts":65536}}`
och `options_path` vid skapandet av en **ny** telefonplan. LIGHT kör ingen native
väljare, lokal producent, lokal relay eller lokal pool. Workerjobbet har en
uttrycklig tid- och försöksgräns; konsensusprocesserna kör tills de stoppas.

## 6. Visa CLI-noderna i Desktop

Starta Desktop som samma lokala användare som CLI. Desktop läser endast de
offentliga observationerna från användarens redan körande processer. Det
öppnar inga skyddade profiler och startar ingen extra nod. Vid flera lokala
CLI-processer väljs noden i DAG-flikens källväljare, med ägarprofil, nativeprofil
och roll. Nätverkets räknare summeras inte mellan källorna.

Valet binds till exakt process och offentlig nod-, nätverks- och kontoidentitet.
Om processen försvinner, stoppas eller byter identitet töms visningen och den
valda källan visas som otillgänglig. Välj då uttryckligen en aktuell källa.
Desktop byter inte automatiskt till ett annat konto. Äldre observationer märks
som äldre data och ska inte indikera en aktuell anslutning.

Observationerna lagras privat på respektive operativsystem. En Linux-process
ska använda Linux-användarens privata lagring; en Windows-monterad katalog
med öppna Unix-rättigheter är ingen giltig ersättning. Publika bootstrapfiler
kan däremot överföras enligt det etablerade filreceptet ovan.

Avstängning avbryter först arbete och ingress och inväntar sedan ägda trådar
och nativeprocesser innan journaler släpps. Ett uttryckligt `STOP_PENDING` är
inte ett genomfört stopp: samma runtime behåller ägarskapet för ett nytt
stoppförsök. Ingen annan process ska samtidigt öppna de journalerna.

## Avgränsad fysisk acceptans

Nästa fysiska körning ska använda dessa operatörsexporter hela vägen. Kontrollera
samma granskade genesis på alla enheter, fyra verkliga väljare och korrekt
plattform/ägare för producent och block. Gör en verklig kontobetalning till
telefonens signerade kontoadress, följ den från kö till verifierat SDK-kvitto och
kontrollera att UI visar samma certifierade uppgifter som CLI. Kör därefter ett
ändligt workerjobb, verifiera verklig blockattribution och certifierad poolutbetalning,
stoppa och återstarta processen och kontrollera samma kvitto/balans från lagring.
Ett föreslaget block, en anslutningsindikator eller en sparad poolandel räcker inte.

Registrera också bortfall och återanslutning för en väljare, fel bootstrap,
obehörigt klientkort och en långsam/avbruten telefon. Ett förväntat avvisande ska
vara tydligt och får inte bokföras som genomförd betalning. Avsluta samtliga
foregroundprocesser efter provet. Resultatet är ett ändligt funktionstest mellan
enheterna; målet 5000 TX/block och hundratals block/s kräver en separat uppmätt
kapacitetskörning. Detta recept aktiverar inget offentligt testnet eller mainnet.
