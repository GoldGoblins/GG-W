# Nodroller och gränsen till kanonisk konsensus

Datum: 2026-10-31. Lokal implementation och riktad källgranskning.

## Ursprunglig avsikt

Telefoner och långsamma noder ska kunna delta efter sin förmåga. Ett visat
block ska ha en verklig unik skapare. En verifierande nod är inte därmed
skapare, ägare, miner eller konsensusvalidator. CLI och Desktop ska visa samma
faktiska roll och kontotillstånd.

## Implementerade roller

| Val | Faktiskt beteende | Verifieringsomfattning |
|---|---|---|
| `producer` | Två egna signernycklar kan anslutas till nodens DAG-motor; lokala ändliga jobb startas uttryckligen. | Alla lokalt godtagna DAG-testtransaktioner eller signerade tomma förslag, beroende på vald session. |
| `replica` | Hämtar, verifierar och lagrar; inga producentsignerare ansluts till motorn. | Samma mottagarvalidering som producentrollen; ingen påstådd lättklientbesparing. |

Rollen ingår i replikans signerade inbjudan och sessionens signerade roster.
Den tillåtna producentmängden läggs på den nyckellösa motorn före historik och
före lokala signerare. Admission, orphankontroll, återläsning och separata
verifierarkopior följer samma policy. En korrekt signatur från en spärrad
producentplats accepteras därför inte som ett nytt block.

Den äldre sexplatsgenesisen bevarar sina index och testkonton. Reserverade
platser för en replika räknas inte som aktiverade producenter i CLI/Desktop.
Det är inte en ny myntfördelning. Rollbyte under en bunden session tillåts inte.
Äldre inbjudningar och profiler betyder fortsatt producent, vilket bevarar
deras ursprungliga funktion. Inga roller börjar rösta om kanonisk finalitet.

Verifierade lokala fall omfattar falsk rolländring i signerad inbjudan,
korrekt signerade otillåtna block, små/stora parsern, verifierarkopior,
profilåterstart och otillåten historik i en annars integritetssignerad journal.
Tre separata TCP-processer provar dessutom två producenter och en nyckellös
full replika, fortsatt produktion när replikan stoppas och exakt catchup efter
dess återstart. UI-provet kontrollerar rätt roll, fyra tillåtna producenter,
noll egna producenter och avstängda produktionskontroller på replikan.

## Fakta om befintlig konsensus och lätt verifiering

Detta avsnitt beskriver utgångsläget före den efterföljande v2-prototypen.
Den nya lokala konsensusbindningen och dess faktiska gränser redovisas i
[DAG-konsensusbindningens granskning](dag-consensus-binding-review-2026-10-31.md).
Den ordinarie LAN-vyn och en färdig DAG-lättklientroll återstår även där.

`support/gg-consensus` använder CometBFT v0.40.0. Den separata ledgerns
genesis/state/proof-format har fyra konton, fyra fasta testvalidatorer och
oförändrat testutbud. `verify.go` kontrollerar SDK-certifikat, kopplingen mellan
header och applikationsrot samt eventuellt kontobevis och exekveringsbevis.
`knowledge/gg-consensus-web/proof-policy.js` låser paketet till en förankring
från den egna kontrollern; paketet får inte välja sin egen validatoruppsättning.
WASM-koden verifierar publik data och har ingen wallet-/signerfunktion.

DAG-roster och DAG-förslagens mängd/ordning finns inte i detta tillståndsrotformat.
Ett giltigt native-certifikat kan därför inte användas som bevis för en godtycklig
DAG-graf. Dagens DAG-testtransaktioner är heller inte samma transaktionsformat
eller samma testtillgång som native-ledgerns betalningar. Dessa format får inte
kopplas ihop genom ett UI-tal eller genom att bara skicka en hash som memo.

Den officiella v0.40.0-releasen anger ändrad tidsberäkning som bortser från
Nil/Absent-röster i MedianTime. Detta är relevant till CSA-2026-001/Tachyon,
som visar att kontroll av commit-signaturer och härledning av tid måste följa
samma regel. Här används ingen slutsats att alla CometBFT-versioner automatiskt
är likvärdiga eller att befintlig DAG redan är konsensussäker.
[Pinnad release och ändringslista](https://github.com/cometbft/cometbft/releases/tag/v0.40.0),
[pinnad ändringslista](https://raw.githubusercontent.com/cometbft/cometbft/v0.40.0/CHANGELOG.md),
[Tachyon-rapport](https://github.com/cometbft/cometbft/security/advisories/GHSA-c32p-wcqj-j677).

## Nästa beroende och acceptanskrav

En verklig DAG-lättklient kräver först ett specificerat certifierat DAG-ankare.
Arbetet med lättklienten beror därför på den underliggande konsensusbindningen:

1. En autentiserad genesis/epoch anger konsensusmedlemskap och vikt separat från
   anslutna klienter och producenter. Telefonrollen skapar ingen obligatorisk röst.
2. Konsensus väljer en exakt tillgänglig payloadmängd och deterministisk ordning.
   Den befintliga finalitetsregeln får inte bytas mot samtliga anslutna peers.
3. De röstande verifierar och lagrar nödvändiga data före sitt godkännande.
   En rot ensam intygar inte tillgänglighet och en lagringskvittens är inte ett
   kanoniskt exekveringsbevis.
4. Det certifierade applikationstillståndet binder DAG-mängd, ordning, föregående
   checkpoint och faktisk deterministisk exekvering. Konflikt, upprepad nonce,
   utebliven payload eller okänd förälder får inte bli slutligt godkännande.
5. Klienten verifierar ett förankrat certifikat och eget medlemskaps-/kontobevis
   inom ändliga budgetar och utan att ta emot varje global transaktion. Gamla
   eller motstridiga ankare får inte återställa ett redan accepterat tillstånd.
6. Uppdelning, equivocation, withhold, omordning och processkrasch provas innan
   `canonical_finalized`, validator- eller lättklientflaggor kan aktiveras.

Detta är krav för nästa kodlager, inte implementerade garantier. Kanonisk
DAG-finalitet är fortfarande noll; DAG-lättklient, offentlig antagning,
monetär huvudnätsmodell och mining/pooler är fortfarande ofärdiga. Inget publikt
nät har startats och ingen Git-push ingår i den här delverifieringen.
