# DAGoblin: säkerhetsgranskning och faktisk leveransstatus

Datum: 2026-10-31. Status: **lokal granskningskandidat, inte mainnet-klar**.
Denna genomgång är en riktad egen granskning med reproducerbara lokala prov.
Den ersätter inte en oberoende protokoll- och implementationgranskning.

## Ursprunglig avsikt

Behåll GG:s nätverk och gränssnitt, men låt verkliga noder producera, signera,
transportera och verifiera verkliga data. Snabba noder ska fortsätta när en
annan nod är långsam. CLI och Desktop ska visa samma nod och konto. Varje
block har en identifierbar skapare; andra noders verifiering ger dem inte
äganderätt. Målet är 5 000 TX/block och hundratals block/s, därefter ett
testnät med samma implementation och regler som avsett huvudnät.

Alla nödvändiga kodändringar ska samlas före nästa fysiska prov och Git-push.
Ingen ny fysisk testkörning, bootstrapomgång eller publicering ingår i denna
lokala granskningskandidat.

## Fakta om det som finns

- LAN-DAG: tre uttryckligen parade noder, två egna producenter per nod,
  separata transportsignerare, verifierade block- och transaktionssignaturer.
  Utan profil är konton och nycklar disponibla RAM-tillstånd. Explicit valda
  krypterade nodprofiler har därefter fått verifierad journal och lokal
  processkraschåterhämtning; se den separata beständighetsrapporten nedan.
- DAG-saldon är en lokal testförhandsvy. **Kanonisk DAG-finalitet är noll.**
- Den separata CometBFT-ledgern har fyra fasta validatorer och SDK-verifierade
  certifikat. Dess lokala testprocesser är en operatör och en fysisk värd.
  Dessa certifikat certifierar inte automatiskt LAN-DAG:ens block.
- Node-identitet kommer från signerade nyckelbindningar. Namn som Linux eller
  Termux är rosterbundna visningsnamn, inte hårdvaruattestering.
- UI är en projektion av backendens observationer. Bash är inte i sig en
  konsensusmotor; verkligt arbete utförs här av Python-/native-noderna och Go.

## Konkreta fynd och ändringar

| Fynd | Ändring | Verifiering |
|---|---|---|
| Den tidigare verifieraren accepterade konstruerade svaga Ed25519-identiteter; en syntetisk inbjudan kunde passera. Detta är inte en förfalskning av en normalt genererad ärlig nyckel. | Gemensam applikationsprofil med kanoniska icke-identitetsnycklar i huvudundergruppen och strikt skalärgräns. Uppdaterad native-provider och självtester före nyckelskapande. | RFC-vektor, negativa nyckel-/signaturfall och externa Wycheproof-fall. |
| En naiv undergruppskontroll via en multiplikations-API kunde ge ett missvisande resultat för blandad ordning. | Den kontrollen används inte. Undergruppsinträde använder den underhållna, korrigerade native-primitiven. | Publicerade blandordningsfall och startup-test mot äldre felbeteende. |
| Pågående liten hämtning kunde få större block efter en samtidig kapacitetsändring. | Varje autentiserad begäran anger sin mottagargräns. Servern skickar bara en prefixmängd som ryms. | Deterministiskt övergångsprov och verkliga treprocessprov. |
| Samordnad provstart krävdes för lokal DAG-TX-produktion. | Varje ägare kan starta och pausa ett ändligt eget jobb utan samordnar-RPC eller lika peerhistorik. | Samordnare avstängd, långsam nod, separat stopp/återupptagning och exakt inhämtning. |
| Ansluten peer sade inget om dess hämtade historik. | Autentiserad loggobservation visar hämtade poster, återstående poster och block som överstiger lokal gräns, separat från kontaktstatus. | CLI-/QML-prov och negativa kvittensfält. |
| Saknad signerartillståndsfil kunde återskapas tom vid konsensusåterstart. | Endast en ny rot får initiera signerartillstånd. Återstart kräver den befintliga filen och kontrollerar signatur, nyckel, kedja och exakt höjd/runda/steg. | Saknad, skadad, partiell och tvetydig fil; fel nyckel/kedja; återstart och dubbelsignering. |
| En eftersläpande validator kunde backa kontrollerns senast certifierade kontovy. | Certifierad höjd får inte gå bakåt. Två olika SDK-giltiga certifikat vid samma höjd låser nya överföringar tills sessionen avslutas. | Negativa kontrollertester; ogiltiga RPC-påståenden får inte utlösa detta lås. |
| Native- och WASM-verifierarens källistor behövde följa den nya signaturprofilen. | Båda binder samma profilkälla. | Faktiska native-/WASM-byggen och samma externa kantfall på båda körmiljöerna. |

CometBFT:s röster behåller SDK:ns verifieringsregler. Den egna transaktions-
och nyckelprofilen ersätter inte SDK:ns konsensus med en egen signaturregel.

## Kryptografi och prestanda

PyNaCl 1.6.2 innehåller korrigerad libsodium för CVE-2025-69277. Startkontrollen
testar både huvudundergrupp och verifierarsemantik, även om en plattform länkar
en egen systemversion. Inkompatibel provider stoppar start utan osäker fallback.
[PyNaCl ändringslogg](https://pynacl.readthedocs.io/en/latest/changelog/),
[libsodium punktkontroll](https://doc.libsodium.org/advanced/point-arithmetic).

Signeringen använder native-biblioteket med oförändrade standardbytes för
samma nyckel och meddelande. I ett lokalt mikroprov var signeringen cirka nio
gånger snabbare än den tidigare adaptern. Verifieringen behåller samma
applikationsprofil: med en kontrollerad prime-order A rekonstruerar native-
verifieraren R i samma undergrupp och jämför kanoniska bytes. Dess separat
testade avvisning av låg ordning behålls. Detta undviker en extra
undergruppsmultiplikation för varje signatur.
[Verifierarens originalkod](https://raw.githubusercontent.com/jedisct1/libsodium/1.0.20-RELEASE/src/libsodium/crypto_sign/ed25519/ref10/open.c).

Alla 210 externa Ed25519-fall gav förväntat beslut: 117 giltiga accepterades,
64 ogiltiga avvisades och 29 valfria svag-/blandordningsfall avvisades enligt
GG:s strikta profil. Samma 210 fall plus fyra riktade R-kantfall gav samma
beslut i Python, native-Go och faktiskt körd Go/WASM.
[Wycheproof originaldata](https://github.com/C2SP/wycheproof/blob/main/testvectors_v1/ed25519_test.json).

Mikroprov är inte nätkapacitet. Det observerade 5 000-TX-blocket var cirka
2,46 MB redan före TCP-/ramkostnader. Arbetsantagandet 200 sådana block/s
kräver cirka 493 MB/s för en enda rå kopia; nuvarande base64-transport ökar
detta ytterligare. Detta är beräknad trafik för just denna kodning, inte en
universell nedre gräns för andra protokoll. Målet är inte uppmätt eller uppnått.

## Pengar, mining och pooler

| Befintlig del | Faktisk ekonomisk regel |
|---|---|
| DAG-testkonton | Initial testallokering, en atom per testtransaktion, signerade avsändarkedjor och exakt nonce. Ingen finansiell finalitet eller miningbelöning. |
| GG-LAN(TEST) | Tre testkonton med en miljard atomer var och sex decimaler. En uttryckligen parad koordinator ordnar kvitton. Inte decentraliserad ekonomisk konsensus. |
| GG-NET-TEST | Fast testutbud på en biljon atomer med sex decimaler, fyra initiala konton. Inga miningbelöningar eller nya mynt per block. |
| Publik ekonomi | Ingen beslutad och implementerad offentlig utbuds-, emissions-, avgifts-, mining- eller poolmodell finns i dessa delar. |

Deterministiska prov med 2 000 riktiga signerade överföringsförsök kontrollerar
utbudsbevarande och att replay eller otillräckligt saldo inte ändrar tillstånd.
Beloppsformat, heltalsgränser och uttömd nonce provas separat.

En signerad producent är inte automatiskt en PoW-miner. Poolandelar är inte
konsensusröster och en pool får inte kunna skapa egen emission. Bitcoin
kontrollerar blockets ersättning mot tillåten subvention och avgifter.
Kaspa knyter ersättning till sitt DAG-/DAA-system och hanterar ändrad blocktakt
i emissionsreglerna. Dessa regler kan inte kopieras som ett UI-tal.
[Bitcoin originalkod](https://raw.githubusercontent.com/bitcoin/bitcoin/v29.0/src/validation.cpp),
[Kaspa coinbase-kod](https://raw.githubusercontent.com/kaspanet/rusty-kaspa/v2.1.0/consensus/src/processes/coinbase.rs).

Stratum V2 skiljer arbetsfördelning från minerens val av jobb och poolens
andel-/utbetalningsbokföring. Det är en relevant förebild om GG väljer PoW;
det skapar inte en miningmodell åt dagens parade DAG. Valet mellan PoW,
röstvikter eller tillståndsgivna validatorer måste göras tillsammans med
Sybilskydd, säkerhetsbudget och monetära regler.
[Stratum jobbdeklaration](https://stratumprotocol.org/specification/06-job-declaration-protocol/),
[Stratum säkerhet](https://stratumprotocol.org/specification/04-protocol-security/).

## Incidenter som har påverkat granskningen

- Bitcoin CVE-2018-17144 visar varför en optimerad förkontroll inte får ersätta
  slutlig dubbelutgifts-/värdevalidering. Våra optimeringar provas mot samma
  negativa acceptansfall.
  [Bitcoin Core:s egen redogörelse](https://bitcoincore.org/en/2018/09/20/notice/).
- Nomads rotorsaksrapport visar hur ett standardvärde för en obestyrkt rot
  kunde bli accepterat tillstånd. Saknat bevis, saknad signerartillståndsfil
  eller okänt ankare får därför inte bli ett implicit godkännande i GG.
  [Nomads rotorsaksrapport](https://medium.com/nomad-xyz-blog/nomad-bridge-hack-root-cause-analysis-875ad2e5aacd).
- Binances uppdatering daterad 2026-10-30 fanns indexerad från den officiella
  tillkännagivandesidan. Direktöppning omdirigerade till en listningssida.
  Rotorsaken behandlas därför inte som färdigutredd här. En giltig
  kryptografisk signatur är inte i sig ett bevis på rätt mänsklig avsikt;
  GG:s exakta gransknings-/sändningsbindning och engångsregler har behållits.
  [Officiell uppdateringslänk](https://www.binance.com/en/support/announcement/detail/d3306d9dca5243548c813b605e1d1751).

## Ghidra och Reverse Engineer Anything: utfört omfång

Ghidra har statiskt dekompilerat valda funktioner i den verkliga tidigare
Ed25519-Pythonmodulen och den nya kandidatens native-modul. REA har kartlagt
den valda egna JavaScript-katalogen för ljusverifieraren. Målbinärerna
exekverades inte av analysverktygen.

En officiell Kaspa v2.1.0-release hämtades och dess publicerade tillgångsdata
kontrollerades. Ghidra-/REA-försöken på den riktiga wallet-binären nådde sina
resurs-/tidsgränser. **Detta är ingen genomförd full binärgranskning av Kaspa**,
Bitcoin eller andra nätverk. De andra protokolljämförelserna är riktad
originalkäll- och specifikationsgranskning.

## Beslut, antaganden och återstående leveranskrav

**Beslut:** behåll fungerande funktioner, oförändrade signaturbytes för vanliga
nycklar och ärliga mätgränser. Publicera inte lokal testtrafik som kanoniska
pengar eller en mainnet-färdig implementation.

**Antagande:** 200 block/s används endast som räkneexempel för användarens
hundratals block/s. Det är inte en godkänd benchmarkprofil eller ett resultat.

**Kvar:** beständig DAG-identitet och verifierad historik efter processkrasch;
offentlig peertransport och antagningsregler; specificerad och implementerad
bindning mellan DAG, datatillgänglighet, ordning och slutlig exekvering;
fungerande DAG-ljusklient; monetär modell och eventuell mining/pooldrift;
PQC-profil; fysisk fleroperatörs-/felprovning och uthållig mätning av mållasten.
Lokalt signerartillstånd skyddar inte mot återställning av en hel äldre giltig
diskbild; signerarrecovery kräver ytterligare operativa skydd.

Nästa fysiska prov och en mainnetlik testnätslansering har därför inte blivit
godkända genom dessa lokala tester. Hela leveransmålet är fortfarande öppet.

## Samlad lokal kontroll

Den första samlade körningen gjorde 290 tester: 289 passerade och ett gav
en QML-varning om förstörd laddningskontext. Båda livscykeltesterna passerade
vid isolerat omprov. Varningens intermittenta orsak är inte förklarad och
har inte dolts eller räknats som ett åtgärdat produktfel.

En separat färsk körning gjorde 31 godkända native-/WASM-/kontrollertester
utan överhoppade tester. Tio minuters treprocessprov gav 1 296 gemensamma
block och 41 472 verifierade testtransaktioner utan transportfel. Det provet
föregick den senare optimeringen av signaturverifieraren; det är därför inte
en slutlig uthållighetsverifiering av alla efterföljande ändringar.

Inga nya versioner har pushats till GG-W eller GG-CLI i denna arbetsomgång.
Det övergripande leveranskravet är inte färdigt. Arbetsfönstret överskreds.

## Senare verifiering av beständighet och roller

Den efterföljande kandidaten med explicita beständiga profiler passerade
321 lokala tester utan fel eller överhoppningar. Därefter har en signerad full
replikaroll införts med faktisk admissionpolicy och utan anslutna
producentsignerare. Den är inte en DAG-lättklient eller konsensusvalidator.
[Beständig nodprofil och kraschprov](durable-node-review-2026-10-31.md),
[roller, befintliga certifikat och återstående konsensusbindning](role-and-checkpoint-review-2026-10-31.md).

QML-varningen återskapades i det osynliga livscykelprovet vid borttagning av
den andra DAG-läsaren. Qt hade då fortfarande inkubering av tabellrader kvar
efter att båda Loader-objekten rapporterat Ready. Provet avser en färdigskapad
läsare; dess beredskapskontroll avslutar nu detta verkliga Qt-arbete före
borttagningen. Tolv upprepningar passerade utan filtrerade varningar.
Detta är en korrigering av provets offscreen-beredskap, inte en påstådd ny
garanti mot alla typer av UI-livscykelfel. Den följande samlade regressionen
passerade 331 tester med noll fel och noll överhoppningar, på oförändrade
källfiler under körningen. Sourcekontraktet och headless-paketgrafen passerade
också. Startaren kontrollerar att signaturmodulen finns innan den väljer
CLI-miljö. Fysisk Linux-/Termuxkörning och hela nätets återstående
leveranskrav är fortfarande öppna; inga nya Git-versioner har publicerats.

En efterföljande native-v2-prototyp binder nu fullständiga DAG-payloads,
verifierad exekvering och beständig manifestkedja till CometBFT-applikationsroten.
69 Go-testfall inklusive underfall passerade, liksom ett verkligt fyrprocessprov
med ett 5 000-TX-block, SDK-certifikat, WASM-medlemskapsbevis, processåterstart
och tre-/tvåvalidatorsfall. Tre första stora processprov föll på tidsgränsen;
den observerade budgetorsaken och rättelsen finns bevarade i granskningen.
Detta ersätter inte samlad regression, fysisk flerplattformskörning, den
ordinarie LAN-integrationen eller resten av leveranskravet.
[Prototypens bindning, bevis och kvarstående krav](dag-consensus-binding-review-2026-10-31.md).

Den samlade regressionen passerade därefter 337 tester utan fel eller
överhoppningar. Opulicerade CLI-källarkiv för Windows, Linux och Termux
kontrollerades med 118 granskade filer och ett separat headless-importprov.
Det senare tillägget till CLI:s explicita fillista är verifierat genom de
faktiska arkiven; inga Desktop-beroenden införs av DAG-källmodulen.

Nästa lokala lager binder nu en uttrycklig fyrkommitté till signerad LAN-v4-
genesis och ger varje validator en separat skyddad profil och ägd nodprocess.
Ett verkligt fyrprocessprov certifierade 5 000 TX och återöppnade både LAN-
och validatorprofiler med samma ankare, historik och certifierade gräns.
83 Go-testfall och 20 nya Python-prov passerade; kryptografi och faktisk
processkörning skiljs i rapporten från kontrollpolicy med mockad verifierare.
Ordinarie CLI/UI-integration och övriga leveranskrav är fortfarande öppna.
[Gemensamt LAN-ankare och beständiga validatorer](lan-consensus-anchor-review-2026-10-31.md).
