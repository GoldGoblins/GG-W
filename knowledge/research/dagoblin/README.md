# DAGoblin — forskningsunderlag och provbar arkitektur

Datum: 2026-10-29. Status: lokal prototyp, källgranskning och designförslag.
Detta är inte en lanserad konsensus eller ett intyg om postkvantumsäkerhet.

## Vad användaren ville från början

GG ska ha ett eget snabbt, säkert och lätt nätverk: parallella block med flera
föräldrar, avsändarförberäknade transaktioner, telefoner och datorer som kan
delta, riktig CLI på Windows/Linux/Termux och samma wallet-/marketplacefunktioner
som i skrivbordet. Arbetsnamnet för den egna DAG-konstruktionen är **DAGoblin**.
Ambitionen är att överträffa Kaspa, Solana och andra lösningar även i kostnad,
smidighet, lagerarkitektur, skalbarhet och skydd mot framtida kvantdatorer.

Den senaste preciseringen är **kapacitetsanpassad takt**: ingen godtycklig
global TPS-gräns; snabb utrustning ska kunna utnyttjas och långsamma enheter ska
kunna delta på en lämplig nivå utan växande köer eller osäkra omsändningar.
20–300 samtidiga block, senare tusentals block/s och tusentals transaktioner
per block är mål som ska prövas, inte redan uppmätta resultat.

## Vad undersökningen faktiskt visar

- En DAG är en datastruktur. Gemensam ordning, tillgänglighet, Sybilskydd,
  konfliktregler och slutlighet kräver ytterligare protokoll och antaganden.
- Kaspa har redan parallella valideringssteg. Dess GHOSTDAG, räckviddsindex,
  pruning och arbete per block kan inte ersättas med ett godtyckligt antal pilar.
  Aktuell release och DAGKnight-förslag har granskats separat.
- Avsändarbevis och distribution till flera arbetare är lovande sätt att flytta
  arbete. Mottagaren måste fortfarande läsa, kontrollera och kunna hämta data.
- Fem peers framåt, fem bakåt och en senast känd kan prövas som overlaypolicy.
  Det utgör inte ett kvorum eller ett bevis för att en mottagen rot är betrodd.
- Fler validatorer, fler dataarbetare och fler oberoende exekveringspartitioner
  har olika effekt. Antalet maskiner ger ingen generell linjär TPS-formel.
- Det finns inte ett verifierat protokoll som samtidigt gör all kontroll gratis,
  eliminerar alla attacker och förbättrar varje säkerhets-/resursmått tio gånger.
  Därför skiljs mätbara mål från beviskrav och ännu oprövade hypoteser.

Primärunderlag och avgränsning finns nära varje påstående i dokumenten nedan.
De breda jämförelserna är litteraturstudier; Kaspa har dessutom fått en riktad
källkodsgranskning. Det är inte en fullständig formell revision av alla system.

## Läsordning och leveranser

| Underlag | Innehåll |
|---|---|
| [Kaspa, GHOSTDAG och DAGKnight](kaspa-ghostdag-dagknight.md) | Versionsbunden algoritm-, kod- och antagandegranskning; öppna luckor. |
| [Verktyg och kodgranskning](tooling-code-audit.md) | Faktisk Ghidra-/LLVM-/disassemblyanvändning, omfattning och kostnad. |
| [Grannar, Merklebevis och säkerhet](security-neighbor-merkle.md) | Hotmodell, motexempel, sampling, nätkostnad och riktiga mikromätningar. |
| [Konsensusjämförelse](consensus-comparison.md) | Olika DAG-, kedje-, BFT- och betalningskanalmodeller. |
| [Postkvantum och lager](quantum-and-layers.md) | FIPS 203/204/205, migrering, L2–L4 och beroenden. |
| [DAGoblin v0](dagoblin-v0-spec.md) | Kandidatarkitektur, adaptiv takt, roller, invariants och acceptansgrindar. |
| [Mätkontrakt](benchmark-contract.json) | När en jämförelse får användas för ett 10×-påstående. |
| [Breda primärkällor](broader-primary-sources.json) | Källor och avgränsad läsomfattning utöver Kaspa. |
| [Körbar kapacitetsmodell](../../../support/dagoblin/analyze.py) | Exakta byte-/tidsberäkningar; inga nätanrop eller kryptografiska löften. |
| [Nuvarande prototyp](../../gg-parallel-dag.md) | Faktisk körbar implementation och dess hårda lokala gränser. |

## Beslut för detta arbete

**DAGoblin** betecknar utvecklingsspåret. Den nuvarande signerade förslags-DAG:en
är en lokal protokollprototyp. Hardhat och CometBFT behåller sina egna regler.
Ingen lokal förhandsberäkning eller animation ommärks till ekonomisk slutlighet.
Prototypens `canonical_finalized` är fortfarande noll.

Kapacitetsmodellen får planera högre takt, men ändrar inte testmotorns
resursgränser eller startar last. Detta skyddar den delade datorn. Produktion
behöver en validerad admission-/konsensusintegration innan högre takt kan
aktiveras. Ingen publik nätverkslansering eller GitHub-publicering är utförd.

## Antaganden och öppna frågor

Första decentraliserade försöket bör använda kända testvalidatorer och testmedel.
Öppet deltagande behöver ett uttryckligt, granskat Sybil-/medlemskapssystem;
vilken ekonomisk modell som ska användas är ännu inte beslutat. Fysisk telefon,
flera oberoende operatörer och postkvantumimplementation har inte testats här.
IACR:s fullständiga DAGKnight-PDF kunde inte hämtas; dess metadata, officiella
förslag och utvecklingskod får inte beskrivas som en genomförd full bevisrevision.

Förbättringsmålet kvarstår. Ett resultat får kallas bättre först när mätkontraktet
och de aktuella säkerhetsantagandena stödjer just det påståendet.
