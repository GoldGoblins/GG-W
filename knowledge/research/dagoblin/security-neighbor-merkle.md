# DAGoblin: 5 framåt, 5 bakåt, Merklebevis och faktisk kontrollkostnad

Datum: 2026-10-29. Status: forskningsunderlag och ett kort, offline mätprov.
Ingen produktionsregel, nätverkstransport, ekonomisk modell eller appkod ändras.

## Ursprunglig avsikt

Låt varje deltagare kontrollera ett litet antal andra deltagare, exempelvis fem
framåt, fem bakåt och den senast kända, och låt avsändaren förbereda sina egna
transaktioner med bevis. Målet är låg kostnad per nod, deltagande från telefoner,
parallellt arbete och att felaktig trafik ska bli dyr för angriparen och billig
att avvisa. Den riktningen är provbar. Påståendena att varje attack därmed blir
omöjlig eller att kontrollen blir gratis följer däremot inte av konstruktionen.

## Fakta: fyra olika egenskaper måste bevisas

| Kontroll | Vad ett godkänt resultat visar | Vad det inte visar ensamt |
|---|---|---|
| Hash och Merklemedlemskap | Dessa bytes hör till det träd vars rot kontrollanten jämför mot. | Att roten är betrodd, att hela blocket finns eller att en transaktion är giltig. |
| Signatur | Den som har den aktuella privata nyckeln har godkänt exakt meddelande under angivna kryptografiska antaganden. | Att signatären är ärlig, unik, solvent eller överens med andra signatärer. |
| Giltig tillståndsövergång | Regler, saldo och nonce följs från en autentiserad ingångsstat. | Att samma övergång blivit globalt vald och slutlig. |
| Tillgänglighet och gemensam ordning | Nödvändiga data kan hämtas och konfliktregler ger överensstämmande resultat. | Detta uppstår inte automatiskt genom fler hashreferenser. |

Merklemedlemskap och konsistens mellan loggversioner är separata bevis i
[RFC 9162, §§2.1.3–2.1.4](https://www.rfc-editor.org/rfc/rfc9162.html#section-2.1.3).
Samma RFC varnar uttryckligen för att en logg kan ge olika klienter motstridiga
vyer. Att varje klient får en korrekt beviskedja mot sin mottagna rot räcker
alltså inte för en gemensam sann historia.
[RFC 9162, §11.3](https://www.rfc-editor.org/rfc/rfc9162.html#section-11.3)

Avsändarens förberäkning kan flytta verkligt arbete från blockproducenten.
Ett konkret föredöme är att PeerDAS lägger framtagandet av cellbevis på
blobavsändaren. Mottagarna behöver fortfarande kontrollera bevis och ordna
gossip, provtagning och dataförvaring.
[EIP-7594, specifikation och nätverk](https://eips.ethereum.org/EIPS/eip-7594#specification)

## Fynd: vad betyder ”framåt”, ”bakåt” och ”senaste”?

Tre tal får inte blandas ihop:

- **Peergrad:** antal nätverksanslutningar till andra maskiner eller processer.
- **Föräldragrad:** antal äldre block som ett nytt block refererar till.
- **Kvorum:** oberoende röster eller vikt som ett faktiskt konsensusprotokoll kräver.

Elva anslutningar innebär inte elva oberoende operatörer. Elva blocklänkar är
inte ett kvorum. En DAG har en partiell ordning och kan ha flera samtidiga
toppar. Ett block kan referera till redan kända föräldrar; fem ännu okända
framtida block kan bara bli senare observerade efterföljare eller kvittenser.
En lokalt senast observerad topp är inte automatiskt globalt senast eller slutlig.

Narwhal skiljer datadistribution från ordning och använder faktiska
tillgänglighetscertifikat. Dess modell antar färre än en tredjedel felaktiga
parter och förbindelser mellan ärliga parter som så småningom levererar data.
`2f+1` kvittenser har betydelse genom dessa antaganden och reglerna för vilka
block som får signeras; antalet godtyckliga grannkontakter ger inte samma skydd.
[Narwhal/Tusk, §§2.1, 3.1–3.2](https://arxiv.org/pdf/2105.11827)

**Öppen definitionsfråga:** avser 5+5 ID-ordnade nätverksgrannar, geografiska
grannar, blockföräldrar/efterföljare eller ett slumpat urval? Varje tolkning
ger olika säkerhets- och spridningsegenskaper. Underlaget antar inte ett svar.

## Konkreta motexempel, utan aktiva attacker

| Situation | Varför alla kontrollerade hashvärden ändå kan stämma | Nödvändig ytterligare regel |
|---|---|---|
| Samverkande grannar visar en annan rot | De bygger ett internt konsekvent träd och ger korrekta bevis för just den roten. | Autentiserat checkpoint och definierad konsensus-/tillitströskel. |
| Ett block annonseras men merparten av innehållet hålls undan | Rot och ett fåtal blad kan visas utan att resterande innehåll lämnas ut. | Datahämtning, lagringsåtagande, återhämtning och vid behov erasure coding med provtagning. |
| Två signerade syskon använder samma nonce | Båda kan ha korrekta medlemskapsbevis från samma ursprungssaldo. | En gemensam konflikt- och ordningsregel; ”signerad” får inte betyda ”finaliserad”. |
| Ett gammalt korrekt svar återanvänds | Innehållet är äkta men säger inget om att noden svarar nu eller känner aktuell historia. | Färsk utmaning, sessions-/kedjebindning, timeout och kontroll mot relevant checkpoint. |
| Alla anslutningar isoleras | En nod kan få gamla men korrekt signerade data, eller inga data alls. | Flera vägar, återanslutning och uttryckligt beteende under partition. Säkerhet och fortsatt produktion får inte blandas ihop. |
| Korrekt signerad men onyttig trafik fyller köer | Varje meddelande kan vara syntaktiskt och kryptografiskt giltigt. | Även giltig trafik behöver arbets-, byte-, lagrings- och rättvisekvoter. |

Det lokala mätprovet demonstrerar första raden: ett ändrat saldoblad verifieras
mot det ändrade trädets egen rot och avvisas mot den ursprungliga betrodda roten.
Samma prov verifierar medlemskap med ett enda blad i kontrollantens indata trots
att roten omfattar 512 blad. Det är ett logiskt motexempel mot slutsatsen
”ett giltigt medlemskapsbevis bevisar hela datamängdens tillgänglighet”, inte ett
angrepp på en levande nod.

## Fakta och egen beräkning: samverkan, Sybil och urval

Sybilproblemet är att samma aktör kan uppträda som många identiteter; redundans
behöver därför ett uttryckligt antagande om oberoende eller begränsad angriparvikt.
[Douceur, The Sybil Attack](https://www.microsoft.com/en-us/research/wp-content/uploads/2002/01/IPTPS2002.pdf)
Eclipseforskningen visar hur kontroll över en nods anslutningar kan begränsa
dess vy utan att bryta blockkedjans hashfunktion. Resultaten gäller den studerade
Bitcoinversionen, inte en uppmätt attackkostnad mot DAGoblin.
[Heilman m.fl., USENIX Security 2015](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-heilman.pdf)

**Egen beräkning under starka antaganden:** om varje peer väljs oberoende,
likformigt och med återläggning ur en redan autentiserad population där andelen
angriparkontrollerade identiteter är `q`, blir sannolikheten att alla elva är
angriparens `q^11`.

| Antagen `q` | Alla 11 valda kontakter illvilliga |
|---:|---:|
| 25 % | 0,00002384 % |
| 50 % | 0,048828 % |
| 90 % | 31,3811 % |
| 100 % | 100 % |

Utan återläggning, med `m` illvilliga av `n` och elva distinkta val, är det
exakta uttrycket `C(m,11)/C(n,11)` när `m>=11`, annars noll.
Det är sannolikhet för **detta urval**, inte för alla tänkbara attacker.

Formeln gäller inte automatiskt för fem närmaste ID:n framåt och bakåt, en
förgiftad adresslista, flera identiteter hos samma operatör eller en angripare
som kan korrumpera valda grannar efter urvalet. Om den senaste peer:n alltid
kan kontrolleras av angriparen återstår i bästa fall tio slumpade skyddande val,
inte elva. Vid okänd Sybilandel finns inget verifierat numeriskt `q` att stoppa
in i formeln. En miljon deltagare gör inte ett dåligt urval säkert av sig självt.

## Egen beräkning: upptäckt av undanhållen data

Anta `M` lika stora datadelar varav `m` är fast undanhållna och att kontrollanten
väljer `s` distinkta positioner likformigt. Sannolikheten att upptäcka minst en
saknad del är:

`P(upptäckt) = 1 - C(M-m,s)/C(M,s)`.

För stora populationer eller prov med återläggning används approximationen
`1-(1-β)^s`, där `β=m/M`. Elva prov ger cirka **95,78 %** upptäckt om 25 % saknas,
men bara **10,47 %** om 1 % saknas. Cirka 299 oberoende prov behövs för 95 %
upptäckt vid 1 % saknad data. Om allt efterfrågat kan lämnas ut selektivt ändras
modellen; flera klienters prov och vidarebefordran behöver analyseras tillsammans.

Forskningsschemat för fraud/data-availability proofs kombinerar erasure coding,
Merklebevis, slumpad provtagning och återutsändning. Dess §5.4 behandlar just
selektiv utlämning. Ett giltigt hashprov ersätter inte dessa nätverksantaganden.
[Al-Bassam, Sonnino och Buterin, §§5.3–5.7](https://arxiv.org/pdf/1809.09044)
PeerDAS använder i sin tur kodade dataceller, datacustody och diversifierade
peers. Att kopiera bara antalet prov kopierar inte hela dess säkerhetsmodell.
[EIP-7594](https://eips.ethereum.org/EIPS/eip-7594)

## Uppmätt: kontrollen är liten men inte gratis

Det korta provet kördes på befintlig Windows-/AMD64-utvecklingsdator med
Python 3.13, GG:s riktiga 512-bladsfunktioner och befintlig PyCryptodome Ed25519.
SHA-proven omfattar Python-anrop och skapande av inmatningsobjekt, inte en
isolerad hårdvaruinstruktion. Alla proof-/signaturprov använder varma lokala fixturer.
Det tog **0,2375 s** i den mätta arbetsfasen. Processens högsta arbetsminne var
cirka **26,9 MiB**. Python-allokering mättes separat från tiderna. Ingen användarnyckel,
wallet, publik nod, nätverkslast, disklogg av hemligheter eller appinställning användes.

| Operation | Median | p95 |
|---|---:|---:|
| SHA-256, 64 byte | 0,550 µs | 0,605 µs |
| SHA-256, 1 024 byte | 1,130 µs | 1,150 µs |
| Merklemedlemskap, 512 blad, redan avkodat objekt | 19,350 µs | 60,100 µs |
| JSON-avkodning + samma Merklebevis | 24,600 µs | 27,700 µs |
| Ed25519-signering med befintlig nyckel | 283,400 µs | 339,900 µs |
| Ed25519-verifiering, återanvänt publikt verifierarobjekt | 784,000 µs | 981,700 µs |
| Import av publik nyckel + Ed25519-verifiering | 1 109,200 µs | 1 768,000 µs |
| Bygga hela 512-bladsträdet | 2 086,150 µs | 2 093,400 µs |

Nio syskonhashar à 32 byte är **288 byte råa hashvärden**. GG:s fulla JSON-bevis
med blad, riktningar och fältnamn är **950 byte**. En rå Ed25519-signatur är
ytterligare 64 byte och publik nyckel 32 byte om dessa behöver överföras.
Ett 112-byte heartbeatutbyte är därför inte samma meddelande som detta bevis.

Mottagaren behöver fortfarande läsa bytes, avkoda, slå i cache, verifiera och
hantera konflikter. Avsändarens förberäkning befriar inte mottagaren från dessa
steg. I just detta prov var Ed25519-verifiering dyrare än signering; det är ett
lokalt resultat, inte en universell kvot för alla bibliotek och processorer.
Telefon, batteri, postkvantumsignaturer, TLS, databas, nätverksköer och konsensus
ingick inte. Korta varma prov på en delad dator får inte räknas om till utlovad TPS.

Reproducerbar källa i arbetsytan:
`.runtime/dagoblin-research/proof_cost_microbench.py`.
Råresultat: `.runtime/dagoblin-research/proof-cost-result.json`.
Kontrollerna för falsk rot respektive ändrat signerat meddelande passerade.
Gränsen 64 MiB kontrollerades före/efter provet; inget OS-jobb eller cgroup-tak påstås.

## Egen kostnadsmodell: elva kontakter skalar lokalt, inte till noll

Låt `D` vara distinkta peerutbyten per nod och intervall, `f` intervall/s,
`Rq` requestpayload och `Rs` responsepayload, båda i byte. För `N` noder:

`B_nod = D × f × (Rq + Rs)` byte/s.

`B_nät = N × D × f × (Rq + Rs)` byte/s i sammanlagd skickad payload.

För hypotesens högst elva distinkta peers är `D=11`. Överlappande senastepeer
dedupliceras. Varje request och response räknas en gång; om båda ändpunkterna
initierar egna ping är det två riktiga utbyten. Inkommande och utgående bytes
summerade över alla ändpunkter skulle ge dubbla nätpayloaden.

| Räkneexempel, `N=1 000 000`, `f=1/s` | Per nod | Sammanlagt nätverk |
|---|---:|---:|
| 112 byte totalt per heartbeatutbyte | 1 232 byte/s | 1,232 GB/s |
| 64-byte request + illustrativ 1 024-byte response | 11 968 byte/s | 11,968 GB/s |

Detta är **räkneexempel på payload**, inte uppmätt P2P-trafik. IP/TCP/QUIC/TLS,
ack, omsändning, discovery, reparation, blockdata och konsensus tillkommer.
Aggregerade GB/s fördelas normalt över noder och länkar; de belastar inte
automatiskt en enda dator. Konstant peergrad är därför en verklig möjlighet
att hålla varje deltagares grundtrafik begränsad.

Om däremot alla bokstavligen frågar **samma senast tillkomna nod** en gång/s
kan den noden få `N` förfrågningar/s och svara med ungefär `N×Rs` byte/s.
Den extra senaste-länken skapar då en hot spot. Om ±5 avser bara närmaste
grannar i en ring är det största avståndet i stället ungefär `ceil(N/10)` hopp.
Detta är två villkorliga topologiexempel; båda motiverar att definiera overlayn
innan man lovar kort fördröjning. De säger inget om en redan implementerad P2P-motor.

60 Hz grafik behöver inte 60 peerprover/s. I det andra räkneexemplet ovan
multiplicerar 60 pings/s den rena payloaden med 60. Mät- och grafikklockorna
bör vara separata från block-, bevis- och heartbeatfrekvens.

## Designalternativ för en avgränsad DAGoblin-prövning

Följande är **förslag att testa**, inte införda eller bevisade protokollregler:

| Alternativ | Vinst | Kvarstående kostnad eller antagande |
|---|---|---|
| Behåll några stabila grannar men lägg till slumpade, roterande långvägar | Bättre chans att få en annan vy och lägre beroende av samma granngrupp. | Urvalspopulationen får inte kunna fyllas gratis med Sybiler; rotation behöver hysteresis mot churn. |
| Reservera egna utgående förbindelser och sprid över oberoende operatörer/nät | Inkommande anslutningar kan inte ensamma ersätta alla betrodda vägar. | IP-/ASN-spridning är kostnadsfriktion, inte bevis på oberoende människor. |
| Använd signerade checkpoint-ID:n och färska challenges | Kopplar bevis till rätt kedja, epok, rot och aktuellt utbyte. | Nyckel-/kvorumval, uppgradering och återhämtning måste definieras. |
| Cache per full meddelandehash + autentiserat checkpoint och schema | Identiska redan verifierade objekt slipper upprepade signaturkontroller. | Bytes måste fortfarande tas emot; cache är begränsad och får inte göra ändrade eller gamla objekt betrodda. |
| Tak per peer **och** totalt för bytes, signaturarbete, kön och lagringen | Ett giltigt eller ogiltigt flöde kan inte äta obegränsat appminne. | Bandbredden fram till processen och nätverksleverantörens länk skyddas inte av en kögräns. |
| Betald/kvoterad admission, exempelvis begränsad PoW, insats eller känd testmedlemslista | Gör identitets- eller arbetsmängden mätbar och angriparens budget explicit. | Varje val ändrar tillits-, energi-, kapital- och censurmodellen; inget är gratis Sybilskydd. |
| Belöna bara unikt efterfrågat arbete efter bevisad leverans/acceptans | Kan styra förberäkning mot nyttiga data. | Måste hindra självsändning, dubbla belöningar och att verifieringskostnaden överstiger arbetsvärdet. |

Gossipsub v1.1 är en användbar primärspecifikation för utgående kvoter,
beteendebaserad scoring, återanslutningshistorik och begränsning av upprepade
datasvar. Det är en katalog av konkreta skydd att jämföra med, inte ett bevis
för att just DAGoblin blir oangripligt.
[libp2p Gossipsub v1.1](https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.1.md)

## Ett falsifierbart första hotkontrakt

1. **Omfattning:** separat test-DAG och nytt, explicit P2P-experiment. Befintliga
   wallets och verkliga tillgångar ger ingen testbehörighet.
2. **Angripare:** får duplicera, fördröja, undanhålla och skicka felaktiga eller
   giltiga men överflödiga testmeddelanden från sin begränsade andel registrerade
   identiteter. Korruption, churn, partitionslängd och nätbudget anges i provfilen.
3. **Antaganden:** autentiserad initial checkpoint/medlemslista och angiven
   kryptografisk säkerhet. Någon tillräckligt oberoende ärlig väg måste kunna
   leverera data inom det nätverksantagande testet använder. Detta är inte ett
   antagande som ett lokalt hashprov själv kan bevisa.
4. **Säkerhetsinvarianter:** ingen slutlig kvittens utan rätt checkpointregel;
   samma nonce exekveras högst en gång i vald historia; ändrat bevis eller
   fel domän avvisas; osäker eller saknad data visas som okänd/icke slutlig.
5. **Resursinvarianter:** hårda konfigurerade tak på accepterade bytes, kölängd,
   aktiva peers, samtidiga kontroller och cacheposter; avvisad trafik debiteras.
6. **Mätetal:** ärliga meddelandens leveransandel och p95/p99-fördröjning,
   verifierings-CPU, byteförbrukning, högsta minne, återhämtningstid och lyckad
   detektion per scenario. Grafik-FPS redovisas separat.
7. **Kontrollgrupper:** jämför 5+5+senaste med slumpat/roterande urval under
   samma budget. Testa både fasta och adaptiva avsändare samt selektiv leverans.
   Simulerade korruptionsfall får inte beskrivas som bevis mot alla internetattacker.

## Olösta frågor och beslut som inte är fattade

- Vilken sorts granne och vilken definition av ”senaste” ska gälla?
- Hur begränsas antalet identiteter eller deras vikt, och hur ser bootstrap ut?
- Vad autentiserar en ny checkpoint, inklusive vid nyckelbyte och partition?
- Vilka data måste faktiskt finnas var, hur länge, och hur återhämtas de efter pruning?
- Vilket arbete är nyttigt nog att belöna och vem betalar verifiering/lagring?
- Vilka minnes-, trafik- och batteribudgetar gäller för faktisk Termux-telefon?
- Hur förändras byte- och CPU-budgeten när en vald postkvantumsignatur läggs till?

**Arbetsbedömning:** behåll idén om liten lokal grad, avsändarförberäkning och
billiga tidiga avvisningar. Utvärdera dem som delar av ett tydligt hotkontrakt
med autentiserade rötter, dataåterhämtning och global konfliktregel. Ett kontrollerat
hashvärde är en stark byggsten; det är inte ett fullständigt säkerhetsprotokoll.
