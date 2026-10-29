# GG nätverk och wallet: konceptlayout, färgroller och parallell DAG

Detta dokument beskriver v13:s leverans. Senare ändringar av blockintervall,
livekörning, layout och sessionsgränser finns i [Verkliga block och löpande
DAGoblin](gg-network-live.md). Historiska v13-mätningar nedan är inte nya prov.

Fördjupningen och det kapacitetsanpassade utvecklingsspåret heter nu
[DAGoblin](research/dagoblin/README.md). Där finns källgranskning, hotmodell,
postkvantum-/lagerkrav, kandidatarkitektur och ett körbart kapacitetsunderlag.
Detta lägger inte ny global slutlighet på den lokala prototypen.

## Ursprunglig avsikt

Användaren vill att den körbara vyn följer de tidigare konceptbilderna: tydliga
rutor, kompakta listor och tabeller, staplar, procent och ett verkligt nätverk
under latensgrafen. Normalt skrivbordsformat ska visa instrumenten samtidigt.
Walletens mottagningsvy ska vara lika kompakt och GGHB ska få pris från sin
exakta tokenadress. Sexton gemensamma accentfärger ska kunna väljas per
funktionsroll med ungefär Codex CLI:s betydelser, på en grå/vit bas.

Den senaste preciseringen gäller verkligt parallella block med flera
föräldrar och korsande länkar. Avsändaren förbereder eget arbete; andra
verifierar det. 20–300 parallella block och tusentals transaktioner per block
är önskad framtida kapacitet, inte resultat som den här datorn har bevisat.

## Fynd

- Layoutens tidigare kompaktgräns dolde både graf och formulär vid normal
  höjd. Den är ersatt med en sexdelad instrumentyta för normala skrivbordsytor.
- Walletens 40-pixelstext och stora fält fick det långa GGHB-saldot att brytas
  över knapparna. Mottagningsvyn använder nu små kontroller och exakt saldo
  på en rad. Prov vid 328×520 gav 450–452 pixlar innehåll i 486 pixlar visningsyta.
- GGHB:s dokumenterade äldre Pump-allokering är 151 byte. Den ska tolkas enligt
  det officiella SDK:ts kompatibilitet, inte som ett godtyckligt avklippt konto.
  Ett legitimt bränt utbud kan också vara mindre än skapandets utbud.
- Statiska JS-färgvariabler gav inte gemensam direkt ommålning. En reaktiv
  QML-singleton kopplar nu gränssnittets konsumenter till sparade färgroller.
- DAG-renderarens tidigare linjära nodsökning upprepades för varje kant.
  Ett hashindex och återanvända kantobjekt minskar det arbetet.

## Implementerat

### Layout och wallet

EVM, validatorer och signerat labb visar ramar, sammanfattning, instrument,
konton, historik och arbetsfält med gemensamma proportioner. Desktopens
grafer ligger samtidigt synliga. Långa listor rullar i sina egna ytor.
Små fönster har avgränsade val och sidolåda.

Walletens mottagningsadress, tokenadress och saldo har egna riktiga ramar.
Saldo `31 529 284.463525` visas utan radbrytning eller överlapp. Kopiering
använder hela adressen. Sändningens granskning och nyckel-/godkännandespärrar
är kvar. Uppdatera läser bara valt saldo och dess begränsade prisjobb; ett
prisfel får inte göra en lyckad saldoläsning misslyckad.

### Gemensamma färger

Inställningar → Appearance erbjuder 16 färger för varje roll: markering,
information, lyckat, väntan/varning, fel, länkar, nätverk, AI, resurser och
övrigt. Roller ändras oberoende, sparas och målar om andra vyer direkt.
Grönt/rött/gult/cyan/lila har semantiska grundvärden; grått och vitt är basen.
Det är en terminalbaserad palett, inte ett påstående om en universell exakt
Codex-hexpalett. Tokenfärger förblir separata och styr walletens procentbåge.

### GGHB-pris

Exakt mint: `6TY5cDkAD3BN5L8MEXAcd2LysxWRAiji8TJSHUBapump`.
Tre verkliga publika läsningar verifierade mainnet, kontoägare, discriminator,
mint, reserver och ett färskt SOL/USD-ankare. Vid kontrollen var reservpriset
cirka 0,00000307286147 USD. Det är ett tidsbundet, indikativt kurvpris och
inte ett löfte om att ett helt innehav går att sälja till det priset.
Samma adress ger nu värdering även när användaren bara begär denna token.
Manuell uppdatering och minst 60 sekunders cache gäller; ingen global skanning.

### Verkliga block och parallella förslag

Hardhat och CometBFT skapar verkliga tomma kedjeblock med ungefär två sekunders
intervall även utan överföringar. Samma tidigare konsensusregler och exakta
överföringsgranskningar gäller.

Den nya separata **DAG-LABB**-vyn använder `gg_parallel_dag.py`: fyra lokala
producenttrådar skapar verkliga signerade syskonförslag samtidigt. Varje
förslag refererar till upp till sju redan kända föräldrar. Ett konkret prov
gav två omgångar, 48 förslag, 384 validerade testtransaktioner och 168 synliga
föräldralänkar. En oberoende verifierare utan signeringsnycklar får samma
lokala förhandsresultat även vid omvänd leveransordning.

Knappen **3 vågor · 2 s** begär tre verkliga, begränsade jobb. Kommande jobb
avbryts när vyn lämnas, minimeras, stoppas eller får fel/godkännandespärr.
Ingen trafik eller arbetsloop startas av status eller vid programstart.
CLI har samma motor via `dag.start`, `dag.wave`, `dag.status`, `dag.stop` och
det ändliga engångsprovet `python gg-cli.py --command dag.test --json`.
Varje TerminalService har en separat instans; samtidiga terminaler kan inte
stoppa varandras eller desktopens DAG.

## Mätningar och gränser

Den parallella motorn är ett lokalt lager för signerade dataförslag och
deterministisk förhandsberäkning. Den har ingen P2P-transport, global
datatillgänglighet eller ny BFT-/PoW-finalitet. Publik status anger alltid
`canonical_finalized: 0` och `EXPLICIT_CHECKPOINT_REQUIRED`. Inga riktiga
wallet-tillgångar eller användarnycklar ingår. Den ersätter inte Kaspa och
är inte en implementation av GHOSTDAG eller Narwhal/Tusk.

Aktuella provgränser är 32 förslag per jobb, 512 transaktioner totalt per jobb,
128 transaktioner per förslag, sju föräldrar, 192 lagrade poster och 8 MiB
sessionskredit för förslagsdata. Krediten är inte hela processens RSS.
Det separata Windowsprovet för producent och oberoende verifierare ökade
från cirka 25,6 till 34,6 MB RSS; hela GG:s 200–300 MB-mål är fortfarande
inte verifierat. Fysisk telefon är inte testad.

Renderprov med återspelning av verkliga signerade snapshots, 48 noder och
168 länkar, gav 106 bilder/s över två sekunder inklusive avsiktlig tomgång,
med p95 6,875 ms. Batchernas första bild tog 41,5/43,3 ms. Det är därför
inget löfte om låsta 60 Hz i hela appen. Nya block skapas inte av ritningen.

Egen förberäkning eliminerar inte nätverkets validerings-, bandbredds- eller
lagringskostnad. Kvoter, bytegränser, nonce-, signatur-, vittnes-, replay- och
konfliktkontroller är implementerade i den lokala modellen. Öppen nodanslutning,
Sybil-motstånd, global konsensus och påståendet att attacker gynnar nätverket
är inte bevisade egenskaper. Dessa kräver ett separat protokoll och test med
oberoende noder innan produktionsmedel kan kopplas på.

## Verifieringsunderlag

- `.runtime/network-v13-price-acceptance.json`: publikt GGHB-prisprov.
- `.runtime/network-v13-dag/engine-acceptance.json`: riktiga signaturer,
  föräldrar, verifierare och processminne.
- `.runtime/network-v13-dag-render/render-result.json`: renderklocka och jank.
- `.runtime/network-concept-v13/layout-result.json`: layout och riktiga Qt-flöden.
- `.runtime/network-v13-final/`: sammanhållen slutkontroll och Linuxprov.

[DAG-protokoll och tester](gg-parallel-dag.md), [prisdefinitioner](token-market-pricing.md),
[färger](gg-terminal-palette.md), [kadens](gg-block-cadence-v13.md).
Primärkällor: [Kaspa-headerns verkliga föräldrar](https://github.com/kaspanet/rusty-kaspa/blob/master/consensus/core/src/header.rs)
och [Narwhal/Tusk-artikeln](https://arxiv.org/abs/2105.11827).
