# DAGoblin: aktuell cut, lagring och återstart under monetär last

## Ursprunglig avsikt

En långsam eller frånkopplad nod ska behålla sin identitet och sina riktiga
original. Övriga producenter ska fortsätta när konsensus fortfarande har quorum.
Konton, blockägare och monetära utfall ska komma från samma verifierade källa
i CLI och Desktop. Lagring, omstart och återhämtning måste provas med riktiga
signerade betalningar.

## Fynd

Det första utökade source-v3-provet dödade en av fyra röstprocesser vid
50 000 genomförda betalningar. De tre andra genomförde ytterligare 10 000.
En efterföljande begäran om den aktuella cut-transaktionen avvisades.

`Ledger.Query` hämtade först ett tillstånd under sitt läslås. Därefter släpptes
låset innan `CutTransaction` tog ett nytt läslås och kontrollerade den gamla
höjden mot den aktuella. Även ett tomt SDK-block kunde flytta höjden mellan
läsningarna. En begäran om senaste tillstånd kunde därför behandlas som en
uttrycklig begäran om en föråldrad höjd. Det var inte ett bevis för att de tre
validatorerna hade slutat exekvera pengar.

Ett deterministiskt test flyttar nu den riktiga applikationen ett tomt,
committat SDK-block mellan läsningarna. Före rättningen misslyckades de tre
fallen för senaste höjd i source-v1/v2/v3. Efter rättningen klarar även de fallen
kontrollen. Uttryckligen gamla höjder och avbrutna anrop avvisas fortfarande.

## Kodbeslut

En begäran med höjd noll behåller betydelsen aktuell höjd genom hela anropet.
Cut-läsaren hämtar transaktionens bytes och svarshöjd under ett och samma
läslås. En uttrycklig höjd förblir bunden till exakt den höjden. Kodningen av
cut-transaktionen, signaturkontrollerna, monetära reglerna och konsensusens
validering ändras inte. En hämtad transaktion är fortfarande ingen kvittens
på SDK-urval eller monetär exekvering.

Den större återhämtningen hittade även ett separat SDK-startfel. Efter en
första start utan nätkontakt fanns det verifierade SDK-tillståndet vid höjd
195 och rätt seen-commit, men blocklagringen var fortfarande tom. SDK:s
konstruktor hade nollställt sin offline-markör. En upprepad start behövde
fortfarande den markören. Läsning med den riktiga, pinnade SDK-koden visade
att övriga SDK-poster stämde exakt mot arkivets härledda tillstånd. Den enda
ytterligare posten var SDK:s normala, kanoniska genesisdokument.

Startup återställer därför endast den konsumerade markören för en uttryckligen
icke röstande, ännu ej ansluten återställd observatör. Full applikationsreplay,
det exakta ursprungliga certifierade tillståndet, den autentiserade SDK-kedjan,
dess quorum-commit och båda SDK-databasernas poster måste stämma. Okända eller
ändrade poster avvisas. När verkliga SDK-block har hämtats används den vanliga
startvägen. Ingen ekonomisk post, signerarnyckel eller rösträtt återställs här.

Kall replay av 170 000 betalningar tog ungefär tolv sekunder redan utan övriga
validatorer. Den tidigare fasta tolvsgränsen var för knapp under last. Nya och
små lager behåller 12 sekunder. För lokal filvolym över 16 MiB tillkommer en
sekund per påbörjade 4 MiB, med ett absolut tak på 180 sekunder. Inventeringen
begränsas till 4 096 poster och 16 nivåer, följer inte länkar och läser inga
filinnehåll. Den är ingen validering av datan. Samma ägarskap, exakta ready-pipe,
RPC-kontroll, avbrott, signeringsavsikt och minnesgränser gäller fortfarande.

Två separata vanliga CLI-starter av det verkliga 170 000-betalningslagret klarade
den ändrade koden utan diagnostisk timeout-override. De tog cirka 14,4 respektive
13,2 sekunder med en beräknad budget på 51 sekunder, samma nodidentitet och
oförändrade konton. Detta är kall återläsning av tidigare utförd trafik, ingen
ny kapacitetsmätning eller bekräftelse av nätkontakt.

## Lagrings- och avbrottsprovets kontrakt

Det isolerade provet behåller de två fördröjda originalen med 5 000 betalningar
vardera och fortsätter med 32 riktiga block från den snabbare producenten.
SDK måste bekräfta varje planerat epokavslut. Vid två punkter dödas en exakt
ägd röstprocess. De tre kvarvarande måste genomföra minst 10 000 ytterligare
betalningar innan processen startas igen.

Återstarten måste behålla nodidentitet och signerarens beständiga position.
Den får inte nollställa signeringstillstånd, skapa nya nycklar eller byta
original. Ett gammalt monetärt kvitto ska därefter hämtas från den omstartade
nodens egen native-applikation och verifieras.

Alla provtagningar kontrollerar det fasta testutbudets summa och att varje
kontos nonce är icke minskande. Native-processernas faktiska minne och fysiska
filstorlekar mäts. Löpande minnes- och filprov avser aktiva processer. Efter stopp inventeras
också samtliga kända native-noders kataloger, inklusive den stängda källan.
Egna producentjournaler, arkiv, den fristående applikationsåterställningen
och OS-temp ingår inte i den summan. Filinventering medan LevelDB arbetar
är ingen atomisk disksnapshot. Kompaktering kan både öka och minska uppmätt filstorlek.

Varje native-process behåller sin befintliga minnesgräns. Testprocessen som
håller tre logiska Pythonägare redovisar sin större budget separat. Den ändliga
diskgränsen för testets native-kataloger bestäms efter mätt lagringskostnad;
den ändrar inte produktens lagrings- eller säkerhetsregler. Minnesprov från
ett ändligt förlopp bevisar inte en konstant kostnad under obegränsad drift.

## Återhämtning och säkerhet

Provet kräver full originalbaserad arkivverifiering, återställning av
applikationsdata och uttryckligen icke röstande SDK-återhämtning. Den återställda
observatören ska ansluta genom den vanliga CLI-vägen, följa 5 000 nya betalningar,
kunna läsa ett gammalt kvitto ur sin egen applikation och behålla samma identitet
över en kall återstart. Slutliga kontovyer måste följa det nya SDK-tillståndet.

En publik historikfil återställer inte en validators signeringstillstånd.
CometBFT kräver att signeraren bevarar sin senaste höjd, runda och meddelandetyp
för att hindra motsägande signering. [CometBFTs signeringsregler](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/consensus/signing.md).

## Kvarvarande gränser

Ett ändligt lokalt prov omfattar inte strömavbrott på verklig hårdvara,
hel-disk-rollback, flerårig lagringskostnad eller fysisk Termux-prestanda.
En granskad Ghidra-funktion motsvarar inte en granskning av hela binären.
Go-, Linux- och klientprov överlappar och deras antal får inte summeras som
om samtliga vore oberoende försök.

De fyra kontonas fasta testallokering är fortfarande ingen publik monetär
modell. Generella konton, emission, avgifter, mining, poolers bokföring,
Sybilskydd, medlemskap bortom laboratoriets sex producenter och fyra validatorer,
uppmätt slutkapacitet och oberoende säkerhetsacceptans kvarstår
som egna leveranskrav. Hundratals block/s med 5 000 verkliga betalningar per
block är fortfarande ett mätkrav och får inte härledas ur en UI-räknare.
