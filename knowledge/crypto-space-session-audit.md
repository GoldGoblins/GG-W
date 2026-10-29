# Crypto Space: sessionens krav och verifierad omfattning

## Ursprunglig avsikt

GG ska ge en samlad, lättläst kontoöversikt, marknad, wallet, botar och
marknadsplats. Obsidian/Ledger använder svart och grått med vit text och
begränsade accentfärger. Velo är en visuell referens för informationstäthet,
hierarki och verklig telemetri. Innehållet ska ligga i varje fliks riktiga
arbetsyta. Användaren vill även ha en egen GG-kedja och fungerande utbyte
mellan nätverk. Första konkreta överföringsprovet gäller GGHB på Solana.

## Fynd och rättelser

- Arbetsytans innehåll hade höjd från en annan förälder, extra marginaler
  och en separat appnavigation. Innehållet förankras nu direkt i GgFrames
  faktiska viewport. CRYPTO och MP använder samma tunna sektionsrad.
- Översikten prioriterar totalt värderat innehav, kontourval och tillgångar.
  Sekundära kontofakta, saldokällor och registrerade händelser ligger bredvid
  på breda ytor. Saknade priser eller historik förblir saknade.
- MP har sökning/källa, kategorier/material från faktiska objekt, virtuell
  bildkatalog och intilliggande föremålspass. Smala ytor kan öppna ett helt
  pass. Saknade bilder får ärliga platshållare. Inga exempelobjekt skapas i
  användarens bibliotek.
- Ett snabbare klick kunde byta detalj innan ett pågående jobb var klart.
  Marknad, kvitto och wallet binder nu valet till rätt begäran. Felaktigt
  eller ofärdigt kvitto blir inte handlingsbart. Snabb bildimport behåller
  rätt bildidentitet och fel raderar inte formuläret.
- Solanas CAIP-kedjeidentifierare innehåller en förkortning av genesis.
  Mainnetkontrollen använder nu hela RPC-värdet. Förkortningen duger till
  identitet i ett register, inte till denna jämförelse.
- Vanliga SPL-saldon kan vara uppdelade på flera tokenkonton. Överföringen
  kan använda upp till åtta verifierade källkonton i en granskad transaktion;
  större fragmentering avvisas uttryckligen.
- Överföringens sparade signatur och tillstånd följer en monoton modell.
  Sent RPC-svar får inte skriva över redan bekräftat/slutligt utfall.
  Kända avbrutna arbetare återställs utan automatisk omsändning. Tidigare
  överföringar kan väljas och kontrolleras i walletens historik.
  En tappad sändning kan avstämmas som utgången först efter den ursprungliga
  RPC-källans finaliserade blockhöjd och en ny, färsk historisk signaturkontroll.
  Äldre obundna utkast eller läsfel låses inte upp genom en gissning.
- Walletoperationer har ett separat engångsflöde genom befintlig chatt med
  vanligt ja/nej. Godkännandet binds till exakt operation, konto/mottagare,
  granskning, tillståndsrot, endpoint eller krypterad backupfil. Lösenord och
  callbacks stannar i processens RAM och skickas inte vidare till en modell.
- Tokenupptäckt bevarar senaste saldo vid läsfel och visar felet. Nya
  upptäckta innehav kan prissättas i samma uppdatering. Oprissatta sökresultat
  får inte radera eller föryngra en tidigare verifierad prisobservation.
- MP:s kvittointegritet kan inte kringgås genom att ändra/ta bort versionsfält.
  Bevarade äldre kvitton kontrolleras med sin ursprungliga hashmodell.
- MEDIA:s enskilda speldiagnostik använde en AV-kontroll. Den använder nu
  spelresurskontrollen med biblioteksgräns, formatkontroll och skydd mot att
  källan byts under kontrollen. Läslig ROM är inte bevis för emulatoruppspelning.

## Beslut

Koncept finns i [designunderlaget](design/crypto-space-v1/README.md). De skapades
före denna layoutändring och är tydligt fiktiva. Native Qt/QML byggs från
riktiga kontroller; rasterbilderna är enbart referenser. Layouten granskas
visuellt vid smal och bred storlek och kompletteras med geometri- och
interaktionstester. Aktiva indikatorer följer faktiskt arbete. Ingen
syntetisk prishistorik, onlineindikator, omsättning eller framstegsprocent.

Publik bevakning, lokal signerare, krypterad backup, simulering, sändning och
nätverksbekräftelse är separata tillstånd. En synlig tillgång ger ingen
signeringsbehörighet. Känsliga effekter kräver sitt konkreta godkännande;
en allmän utvecklingsuppgift godkänner inte en ekonomisk överföring.

## Verifiering och antaganden

Automatiska kontroller använder isolerat tillstånd och kontrollerade
RPC-fixturer. Native UI-prov kör faktiska QML-komponenter, klick, scrollning,
smala/breda vyer och 2 000 katalograder. Ett separat prov instansierar hela
WorkspaceSurface och mäter förälder, viewport och innehåll för CRYPTO och MP.
SPL-rundresor verifieras kryptografiskt i LiteSVM med separata testnycklar.
Det bevisar inte mainnetöverföring eller oberoende nätverkskonsensus.

En faktisk observation av den öppna appen användes som baslinje. De nya
vyerna verifierades i isolerad native Qt-rendering. Den pågående chatten
startades inte om för att uppdatera skalet. Skärmbilder av fixturer är
layoutbevis och innehåller inte användarens riktiga kontosaldon.

## Återstående arbete

Den egna GG-huvudboken är ett lokalt labb i en process. Distribuerade noder,
produktionskonsensus, mobil-/webb-/radiopeering och verifierade crosschain-
bryggor är inte implementerade. Tillgångar i samma UI ersätter inte deras
ursprungliga nätverk. Universell tokenupptäckt kräver ytterligare verifierade
familje- och indexeradaptrar. Token-2022 kan läsas men denna sändningsadapter
stöder SOL och vanliga SPL-token, inte godtyckliga överföringstillägg.

Ingen ny produktionsnyckel har skapats och ingen mainnettransaktion har
sänts inom denna granskning. Phantom → GG → Phantom återstår som ett
verkligt användarstyrt prov efter skapande och säker backup av GG-walleten.

Sessionens historiska X-kö är inte bevis för att varje post, kommentar och
underliggande repository lästs. Sparad källtext och verifierade fynd beskriver
sin faktiska omfattning. MEDIA:s ersättningssökning använder sparade alternativ;
den är inte en generell extern ersättningssökning för varje trasig källa.

## Referenser

- [Velo](https://github.com/bjarneo/velo): layoutroller, tema och visualisering.
- [Solana genesis](https://solana.com/docs/rpc/http/getgenesishash).
- [Solana CAIP-2](https://namespaces.chainagnostic.org/solana/caip2).
- [Solana bekräftelse och utgång](https://solana.com/developers/cookbook/transactions/confirmation).
- [Solana blockhöjd](https://solana.com/docs/rpc/http/getblockheight).
- [Solana wallet och överföringar i GG](solana-wallet-and-receive.md).
