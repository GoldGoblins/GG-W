# DAGoblin: postkvantum och lager som gör olika arbete

Datum: 2026-10-29. Status: krav och kandidater; ingen PQC aktiverad i GG.

## Fakta: postkvantum är flera olika skydd

NIST:s slutliga **FIPS 203** standardiserar ML-KEM för nyckeletablering;
det signerar inte transaktioner. Sidan har en erratanotis från 2025-11-17.
[FIPS 203](https://csrc.nist.gov/pubs/fips/203/final).
**FIPS 204** standardiserar ML-DSA-signaturer och har en mindre erratanotis
från 2026-07-31. [FIPS 204](https://csrc.nist.gov/pubs/fips/204/final).
**FIPS 205** standardiserar den stateless hashbaserade signaturfamiljen SLH-DSA.
[FIPS 205](https://csrc.nist.gov/pubs/fips/205/final).
Standardisering är inte ett löfte om skydd mot varje framtida attack.

Exakta storlekar från FIPS 204, tabell 2, tryckt sida 16:

| Variant | Publik nyckel, byte | Hemlig nyckel, byte | Signatur, byte |
|---|---:|---:|---:|
| ML-DSA-44 | 1 312 | 2 560 | 2 420 |
| ML-DSA-65 | 1 952 | 4 032 | 3 309 |
| ML-DSA-87 | 2 592 | 4 896 | 4 627 |

NIST anger kategorier 2/3/5, inte ett enda direkt jämförbart bitmått. Standarden
kräver dessutom hantering av sidokanaler och känsliga mellanvärden.
[Originalstandard, §§3.6, 4](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.204.pdf).

**Egen byteberäkning:** 100 000 transaktioner/s med illustrativ 256-byte body
och en 64-byte Ed25519-signatur är 32 MB/s för en enda kopia. Med både den
klassiska signaturen och en ML-DSA-65-signatur blir det **362,9 MB/s**. Protokoll,
bevis, nycklar och omsändningar ingår inte. Detta är ingen kryptobenchmark och
visar inte att ML-DSA är långsamt; det visar att bandbredden inte är gratis.
Aggregering, nyckelcache och batcher måste analyseras utan att hitta på en
kompakt PQ-tröskelsignatur som ännu inte är implementerad eller granskad.

## Beslut och föreslagen migreringsyta

Nuvarande GG-prototyp använder **Ed25519 och SHA-256**. Den är inte en
postkvantumsäker signeringskedja. Varje framtida profil måste täcka:

| Yta | Krav före ett PQ-påstående |
|---|---|
| Konton/transaktioner | Versionsbundet signaturschema, domän, adresser, säkra uppgraderingar och bibliotek med testvektorer. |
| Validatorröster/checkpoint | Alla nödvändiga signaturer och eventuell aggregation/coin/VRF måste omfattas; klassisk BLS får inte gömmas bakom en PQ-etikett. |
| Transport | Granskad autentisering och nyckeletablering; KEM är inte ensamt identitetsbevis. Downgrade måste avvisas. |
| Wallet/recovery | Dokumenterad härledning, algoritmidentifierare och portabel backup. Befintliga BIP39-/Ed25519-vägar får inte tyst tolkas om till PQ-nycklar. |
| Bridge/L2 | Verifierarkontrakt, bevis, administratörsnycklar och värdkedja måste ingå i hotmodellen. |
| Programleverans | Uppdateringssignaturer och återställning måste stödja samma övergång. |

En hybridprofil kan undersökas där båda signaturerna måste godkännas. Det är
ett designförslag; längder, sidokanaler, nyckelrotation, felhantering och kostnad
måste provas i en granskad implementation. Inga egna latticeprimitiver byggs.
En SHA-baserad Merkleadress gör inte underliggande Ed25519-signatur PQ-säker.
GG:s gränssnitt kan heller inte uppgradera Solanas eller Bitcoins underliggande
konsensus eller signaturer åt deras användare.

## Fakta: fler lager är inte automatiskt fler säkerhetsnivåer

L2-rollups kan flytta exekvering och publicera underlag/bevis till L1.
State channels flyttar uppdateringar till deltagarna. En sidechain eller ett
validium har andra tillgänglighets-/tillitsantaganden än en rollup.
[Ethereum: scaling](https://ethereum.org/developers/docs/scaling/).
För en ZK-rollup räcker ett giltighetsbevis inte för att användaren ska kunna
återskapa tillstånd och lämna systemet: data måste också kunna hämtas.
[ZK-rollups, Data availability](https://ethereum.org/developers/docs/scaling/zk-rollups/#data-availability).

L3 kan ge specialisering, integritet eller särskild exekvering. Upprepad stapling
ger inte obegränsad kompression av samma data. Även L4 behöver beskrivas genom
funktion och beroenden; numret i sig är ingen säkerhetsgaranti.
[Vitalik Buterin: What kind of layer 3s make sense?](https://vitalik.eth.limo/general/2022/09/17/layer_3.html).

## Kandidat för GG, ännu inte implementerad

| Del | Funktion | Vad måste fortsatt kontrolleras? |
|---|---|---|
| Bas/checkpoint | Medlemskap, tillgänglig ordnad historia och slutliga tillståndsrötter. | Kvorum, epochbyte, dataåterhämtning och nycklar. |
| Exekverings-/batchlager | Parallella oberoende övergångar och eventuellt granskade giltighetsbevis. | Konflikter, datatillgänglighet, verifierarkostnad och forced inclusion/exit. |
| Applikationslager | Marketplace/trading, avgifts- och integritetsregler. | Orderrättvisa, MEV, behörigheter och felaktiga tillgångsbeskrivningar. |
| Klient-/automationslager | Wallet och valfri AI-assistans med uttryckliga belopps-/signeringsregler. | Ägaren behåller kontroll; AI-policy är inte nätverkets konsensus. |

Att namnge de sista två L3/L4 är möjligt, men produkten ska visa vilken
säkerhetsrot och vilket exitförfarande som faktiskt används. Cross-domain-
överföringar kräver bundna kedje-/epoch-/meddelande-ID:n, replaykontroll,
slutlighetskontroll och definierat beteende vid källkedjans omorganisation.
Detta är våra konstruktionskrav, inte färdigtestade bridgefunktioner.
