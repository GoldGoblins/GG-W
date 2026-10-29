# DAGoblin v0 — kandidat, inte ny bevisad konsensus

Datum: 2026-10-29. Dokumentet specificerar nästa provbara konstruktion. Endast
delarna i kolumnen **finns nu** är implementerade. `Ska` anger konstruktionskrav,
inte en produktionsgaranti.

## Avsikt och faktabaserad avgränsning

Målet är parallellism och avsändararbete utan onödiga globala flaskhalsar.
Varje nod ska kunna använda verklig nät-, beräknings-, minnes- och diskkapacitet.
Slutliga kvitton beror också på oberoende validatorer och tillgängliga data;
ingen säkerhetsregel får hoppas över för att en ensam maskin är snabb.

| Del | Finns nu | Kandidat som återstår att bygga och verifiera |
|---|---|---|
| Förslags-DAG | Fyra lokala samtidiga arbetare, signerade data, upp till sju verkliga föräldrar. | Fjärrtransport med autentiserade peers och kapacitetsbudgetar. |
| Avsändarbevis | Kontomedlemskap mot betrodd lokal rot; nonce, signatur och exakt belopp verifieras. | Färskhet, vittnesuppdatering och eventuellt granskat bevis för dyrare exekvering. |
| Ordning | Deterministisk lokal preview; noll kanoniskt finaliserat. | Oförändrad granskad checkpointkonsensus med specificerad DAG-/DA-bindning. |
| Mobil | Headless Termux-export; fysisk telefon oprövad. | Lätt klient, frivillig förberäkning och begränsat reläarbete. |
| Hastighet | Ändliga lokala testjobb med hårda gränser; separat analytisk planerare. | Adaptiv scheduler inom verifierade nod-/kvorumbudgetar. |
| Postkvantum | Krav och standardparametrar; klassisk prototyp. | Biblioteksval, testvektorer, profilförhandling och verifierad migrering. |

## Modulgränser

1. **Client/preflight:** signera exakt transaktion och förbered vittnen. Privata
   nycklar skickas aldrig till relä, validator eller kapacitetsanalys.
2. **Admission:** begränsad inläsning och schema-/domänkontroll före dyr krypto;
   byte-, försök-, CPU- och lagringskrediter även för korrekt signerad trafik.
3. **Dissemination/availability:** separata headers och payload; explicit
   hämtning, kvittens och återhämtning. En headerrot är inte ett DA-bevis.
4. **Ordering/checkpoint:** välj exakt tillgänglig mängd och ordning inom ett
   definierat epoch-/medlemskapssystem. Kompositionen behöver ett safetybevis.
5. **Execution:** parallellisera deklarerat oberoende läs-/skrivmängder;
   serialisera konflikter deterministiskt. Fler GPU:er löser inte två samtidiga
   uttag av samma saldo utan konfliktregel.
6. **Receipt/clients:** skilj mottagen, validerad, tillgänglig, ordnad, exekverad
   och slutlig. Varje kvitto ska ha verifierbar proveniens.
7. **Telemetry/UI:** verkliga räknare med begränsad historik. 60 Hz ritning är
   separat renderbudget och skapar aldrig nätverksblock.

Narwhals lagerseparation och Starfishs header-/payloadarbete är förebilder,
inte ärvda säkerhetsbevis för vår sammansättning.
[Narwhal/Tusk](https://arxiv.org/abs/2105.11827),
[Starfish](https://eprint.iacr.org/2025/567).

## Adaptiv takt och begränsade köer

Inget godtyckligt globalt TPS-tal ska stoppa bättre hårdvara. Varje mottagare
behöver ändå verifierbara storleksgränser, arbetskrediter, timeout och minnestak.
Blockstorlek och algoritmprofil ändras genom specificerad versions-/epochregel;
en producent får inte ensam höja andra noders parsergräns.

En framtida scheduler behöver uppmätt uthållig kapacitet, svanstider och
köbeteende. En förenklad planeringsmodell jämför resursleden:

`R_plan = min(R_signering, R_verifiering, R_nät, R_disk, R_exekvering, R_DA/kvorum)`.

Invers p95-signeringstid är ett scenarioestimat, inte ett matematiskt övre tak
eller en bevisat stabil schedulerhastighet. De långsammaste fem procenten kan
dominera köerna. Strikta bytegränser gäller bara under den angivna byte-/kopie-
modellen; säker körtakt kräver separat belastningsprov och kö-/resursvakter.

Alla termer måste avse samma transaktion och antal nödvändiga kopior. CPU-kärnor,
GPU:er och extra maskiner räknas genom uppmätt end-to-end-kapacitet, inte FLOPS.
Delade resurser får inte räknas flera gånger. Okänd kapacitet är okänd, inte oändlig.

Föreslagen reglerloop: börja konservativt; samla begränsad statistik; höj takt
och batch försiktigt vid låg köålder och verifierade kvittenser; sänk snabbt
vid växande kö, timeout, temperatur-/minnestryck eller DA-/kvorumfördröjning.
Hysteresis och minsta omvärderingsintervall motverkar oscillation. Reglerloopen
får inte sänka säkerhetströsklar eller starta obegränsade bakgrundsarbetare.

Mottagarkredit ska avse begränsade bytes/arbete och en giltighetsperiod. Förlorad
anslutning stoppar ny admission, inte skapar en evig retrykö. Återhämtning ska
kunna ske från checkpoint och tillgänglig historik utan evig RAM-lagring.

### Länkbudget och 3 000 block/s

Egna råa räkneexempel med **1 000 × 250 byte/block**. Här är 250 byte den
angivna totala transaktionsstorleken, exempelvis 186 byte body + 64 byte
klassisk signatur i planeraren. Headers, ytterligare bevis, omsändningar och
extra kopior ingår inte. Om body ensam är 250 byte tillkommer signaturen.

| Användbar länk | Byte/s | Rått övre tak, block/s |
|---|---:|---:|
| 1 Gbit/s, decimala bit | 125 000 000 | 500 |
| 1 Gibit/s, binära bit | 134 217 728 | 536,870912 |
| 1 GiB/s, binära byte | 1 073 741 824 | 4 294,967296 |
| 6 Gbit/s | 750 000 000 | 3 000 |

3 000 × 1 000 ger 3 miljoner TX/s och minst **750 MB/s** rå nyttolast. En
6-Gbit/s-länk är då redan på 100 % innan protokollkostnaden. Vid 80 % budget
behövs minst 7,5 Gbit/s för enbart detta exempel. Full replikering, synkron disk
och kryptokontroller kan kräva mer. Modellen kan visa en högre gräns med mer
kapacitet; den är inte en nätverksbenchmark. Planeraren i
`support/dagoblin/analyze.py` håller enheter och antaganden åtskilda.

### Långsamma apparater och säker omsändning

En transaktion per signeringstid beskriver **lokal kapacitet**, inte garanterad
nätverksminimihastighet. Vid tomgång är takten noll. En partition kan behöva
stoppa slutlighet även om signering går fort.

En långsam enhet ska kunna ha högst en pågående signeringsbegäran, visa status
och välja lätt klient eller extern signerare. Cirka tio sekunder kan vara en
UX-tröskel för kontroll/avbryt. Det är ingen regel som gör korrekt signatur
ogiltig, kräver ny seed eller automatiskt skapar en andra ekonomisk transaktion.

Omsändning ska vara idempotent: kontrollera samma avsikts-/transaktions-ID och
nonce; återutsänd samma signerade bytes när det är giltigt och nödvändigt.
Om giltighetsperioden löpt ut utreds tidigare status/låsta belopp och eventuell
ersättare granskas enligt kedjans regler. Ny hash eller nonce får inte skapas
blint. Avbruten vy återkallar inte en redan skickad transaktion. Detta är
designkrav, ännu inte en ny signerarrutin.

## Roller och skalning

| Roll | Kan bidra med | Gräns som kvarstår |
|---|---|---|
| Telefon/lätt klient | Egna transaktioner, proofkontroll och begränsad hämtning. | Ingen full global verifiering utan globala data-/konsensusantaganden. |
| Dataarbetare | Parallell distribution, lagring och kodning av batcher. | Fler kopior gör inte konfliktberoende exekvering linjärt snabbare. |
| Full verifierare | Relevanta data, regler och checkpoint. | Snabb sändare kan inte tvinga upp mottagarens verifieringstakt. |
| Validator | Röster enligt autentiserad vikt och lås-/epochregler. | Fem processer på samma dator är inte fem oberoende operatörer. |
| Exekveringspartition | Oberoende objekt/tillgångar med specificerad ägarmodell. | Cross-partition atomicitet och säkerhet är inte gratis. |

Fem bakåt/fem framåt kan prövas som diversifierad peerpolicy med slumpade
reservvägar. Senast **lokalt känd** topp kan ingå i gossip. Alla ska inte
behöva fråga samma nya telefon direkt. Peers, föräldrar och röster är separata.

## Invariants före nätverksintegration

- Signatur/data binds till kedja, version, epoch, konto och nonce. Peerindex
  är inte autentisering. Samma nonce exekveras högst en gång.
- Två ärliga noder ska få samma slutliga tillstånd för samma certifierade mängd
  även vid olika leveransordning. Lokal preview får ändras och visas som sådan.
- Checkpoint finaliserar endast payload som är tillgänglig enligt definierad
  regel. Röster räknas per unik giltig validator/vikt och rätt epoch.
- Partition ger väntande status, inte påhittad slutlighet. Restart och epochbyte
  ska inte möjliggöra dubbelröstning eller replay av gamla certifikat.
- Giltig och ogiltig överlast ska hålla varje resurs inom budget. Mindre legitima
  aktörer ska inte svälta bakom tunga avsändare.
- Pruning ska bevara det som krävs för korrekt bootstrap, exit och exekvering.
  Disk, köminne och hela processträdets RSS mäts separat.
- PQ-profiler provas genom hela kvittokedjan; ingen tyst klassisk downgrade.

Första internetförsök kräver modelltester för equivocation, split view,
double spend, förlorade/omordnade meddelanden, långsamma noder, withholding,
restart och epochbyte. Sedan flera oberoende maskiner/operatörer med WAN-
fördröjning. En-datorprototypen uppfyller inte det genom sin graf.
[Mätkontrakt](benchmark-contract.json).

## Kvarvarande beslut

Öppet Sybil-/medlemskapsskydd, incitament, beständig tillgänglighet,
objektmodell, cross-domainregler och formell komposition är ännu inte lösta.
Högre lokal provgräns ersätter inte dessa beslut. Förbättra arbete per byte/röst
och rollfördelning; göm inte kostnad eller sänk kontroller.
