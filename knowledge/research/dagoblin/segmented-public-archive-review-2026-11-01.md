# DAGoblin: portabel originalhistorik över segmentgränser

Datum: 2026-11-01. Lokal komponentgranskning; detta aktiverar ingen ny
LAN-session, byter ingen nodidentitet och publicerar inget nät.

## Ursprunglig avsikt

CLI är den verkliga noden och Desktop ska visa verifierat nod- och
kontotillstånd från samma underlag. En långsam nod ska kunna återhämta sig
utan att få nya nycklar, förlora sin nonce eller lita på någon annans
kontosnapshot. Granskning och kodfas ska avslutas före den gemensamma pushen
och nästa fysiska acceptansprov.

## Research och egen slutsats

CometBFT:s [ADR 042 om state sync](https://github.com/cometbft/cometbft/blob/main/docs/references/architecture/tendermint-core/adr-042-state-sync.md)
skiljer konsensusens förmedling från applikationens ansvar för
tillståndsformat och validering. Egen slutsats för vår implementation:
ett SDK-certifierat commitment och ett giltigt kontobevis ger inte i sig
bevis för att en full nod har spelat upp alla signerade original.

[Taverna och Paterson, USENIX Security 2023](https://www.usenix.org/system/files/usenixsecurity23-taverna.pdf)
undersökte praktiska attacker mot Geths dåvarande PoW-synkronisering.
Arbetet beskriver bland annat hur ofullständig blockverifiering under
synkronisering kunde utnyttjas. Det är historisk forskning om en annan
implementation och konsensusmodell, inte belägg för samma sårbarhet i vår
kod eller dagens Ethereum. Den konkreta granskningsfrågan här är om någon
återhämtningsväg hoppar över signerade original eller accepterar ett
intermediärt kontoläge som egen tillitskälla.

## Konstruktion

Det uttryckliga v2-formatet börjar med `GGDAGAR2` och ett SDK-certifikat
under anroparens separat låsta native-genesis v4. Varje stängt segment
kommer därefter i ordning från genesis som en längdbegränsad, strömmad
underfil. Ingen hel segmentfil allokeras i RAM. Samma befintliga verifierare
kontrollerar varje originalblock, varje TX-signatur, föräldrar, sekvenser,
noncer, belopp, segmentgräns, inre slutpost och exakt filslut.

Nästa tomma segmentbas härleds från föregående fullständigt verifierade
segment. Den aktiva svansen spelas upp med samma exekveringskärna. Dess
manifest- och råbytesbudget kontrolleras före varje payloadallokering.
Slutligt commitment måste vara exakt det SDK-valda tillståndet. En yttre
slutpost binder räknare och alla föregående filbyte; extra data nekas.

`archive-export` och `archive-verify` väljer format efter den uttryckliga
genesisen. Äldre v1-historik uppgraderas inte. Export öppnar en stoppad
noddatabas skrivskyddat under samma exklusiva OS-lease som noddriften.
Destinationen måste ligga utanför nodroten, skapas exklusivt och synkas
före lyckad kvittens. En ofullständig egen fil tas bort endast om dess
filidentitet fortfarande stämmer; befintliga mål skrivs aldrig över.

Python-anropet använder det ägda, fingerprintkontrollerade SDK-verktyget,
processbegränsning, avbrottskontroll och tidsbudget. Det kräver rätt
genesis, bevisomfång, båda verifierade konto-/nonceuppsättningarna och deras
rötter. En andra strömmad filhash binder native-kvittensen till den redan
öppnade filen hos anroparen. Både tidsgräns och avbrottskontroll gäller
även den passagen. Funktionen startar ingen nod och ändrar ingen journal.

Kvittensen skiljer uttryckligen full originalsignerad DAG-historik från
native-valutans separata transaktionshistorik. Konto- och skaparbevis som
bara visar medlemskap behåller sitt snävare bevisomfång.

## Prov och öppna krav

Riktade prov täcker full kedja genom flera stängda segment och aktiv svans,
tom genesis, SDK-vald tom segmentbas, nonce och producentidentitet,
oförändrad källdatabas, exklusivitet och utebliven överskrivning. Negativa
fall omfattar saknade, dubbla och omkastade segment, ändrade signaturer,
manifest och slutposter, falskt certifikat, otillräckliga SDK-röster,
fel genesis eller certifikatgolv, extra data, avbrott, ramstorlek och
misslyckad utmatning. Kontrollerade checksummor på ett manipulerat hölje
ersätter aldrig kryptografisk återspelning.

Aktuella körresultat och källfingerprint sparas i den privata
`segmented-public-archive-v1`-granskningen. Ett SDK-processprov på samma
Windowsvärd är fortfarande inte fysisk Linux-/Androidkörning eller ett
genomströmningsprov. Kompilerade mål är inte bevis på körning på målen.

På denna kod passerade 557 Go-prov, inklusive samtliga tidigare 532.
Fyra färska native-mål kompilerades. Nio faktiska SDK-processinstanser
(fyra initiala, en återhämtning och fyra efter hård återstart) hanterade
10 001 unika signerade TX och en SDK-vald segmentgräns. Tre validatorer
fortsatte medan den fjärde var avstängd. Efter stopp exporterade alla fyra
identiska portabla arkiv och Python verifierade deras fulla signerade
kedja och aktiva svans mot samma riktiga SDK-certifikat.

Den nya verifieringsfunktionens faktiska maskinkod i Windowskandidaten
disassemblerades och dess 4 272 byte/898 instruktioner importerades till
Ghidra 12.1.4 för avgränsad statisk dekompilering. Go-disassemblyn visar
anrop till certifikatkontroll, segment- och svansåterspelning samt den
slutliga kvittensfunktionen. Go:s register-ABI, alla anropade funktioner
och globala data återskapades inte i denna delanalys. Pseudokod och
källjämförelse är granskningsstöd, inte bevis för hela binärens säkerhet.

Full LAN-versionsförhandling, Python-producentens fortsättning över en
SDK-vald segmentgräns, atomisk NodeProfile-import/aktivering och Desktop-
bindningar återstår. Formatet hämtar inte arkiv över nätet och beslutar
ingen global lagringsbudget. Strömförlustbeständighet för katalogposter,
monetär modell, mining/pooler, målkapacitet och fysisk acceptans är fortsatt
öppna krav. Ingen absolut säkerhetsgaranti eller oföränderlig mainnet-
beredskap följer av komponentproven.
