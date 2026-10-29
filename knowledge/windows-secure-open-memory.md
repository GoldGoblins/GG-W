# Windows: permanent typcacheläcka vid skyddad filöppning

Användaren såg GG-processens arbetsminne växa från ungefär 3,5 till 3,7 GiB.
Nodpanelens ungefär 101 MiB avsåg en separat Hardhat-process och förklarade inte
GG-processens förbrukning.

## Bekräftad orsak och korrigering

`platform_files.secure_open()` skapade tidigare en lokal `FileInformation`-klass
vid varje anrop och använde `ctypes.POINTER(FileInformation)` i Windows-API:t.
ctypes behåller pointer-typer i en processglobal cache. Varje öppning, även ett
misslyckat öppningsförsök, lade därför till en ny permanent struktur-/pointertyp.

WEB-operatörens befintliga 100 ms-pollning använder flera skyddade filöppningar
även när ingen webbuppgift väntar. Tiotals öppningar per sekund kan därför
ackumulera hundratusentals typer. Detta var en faktisk läcka, inte en förklaring
baserad på stora DLL- eller fontmappningar.

Windows ABI-klasserna återanvänds nu från modulnivå. Filhandtag,
säkerhetsdeskriptorer och informationsinstanser är fortfarande separata per
anrop. ACL, reparse-skydd, exklusiv skapning, truncering och handtagsstängning
behåller samma beteende.

| 10 000 öppningar av en syntetisk fil | Före | Efter |
|---|---:|---:|
| Nya permanent cachade pointer-typer | 10 000 | 0 |
| Kvarhållen Python-data efter GC | 75,45 MiB | cirka 22 KiB |
| Ökad privat minnesreservation | 129,22 MiB | 1,84 MiB |
| Tid i den isolerade körningen | 3,08 s | 1,75 s |

Även terminalens färgcache är begränsad till 1 024 färger. Ett separat
100 000-färgtest minskade kvarhållen privat ökning från 56,26 till 0,786 MiB.
Detta tillskrivs inte den stora aktiva läckan utan separat bevis.

Grok-telemetrin läser dessutom nu högst den efterfrågade svansen av en loggfil
via seek/read i stället för att läsa hela filen först. Dess cache skiljer på
läslängder och behåller högst 32 poster. Ett separat 64 MiB-fixturtest läser
256 KiB en gång och håller uppmätt Python-topp under 1 MiB. Detta är en skyddad
transient minnestopp, inte en tillskriven förklaring till den bekräftade typläckan.

## Den redan körande sessionen

En avgränsad kompatibilitetskorrigering aktiverades genom appens befintliga
källuppdatering för operatörsmodulen. Den byter endast den exakta gamla
`secure_open`-funktionens kod med oförändrat anropskontrakt, så redan importerade
referenser följer korrigeringen. Säkerhetsregler eller effektbehörigheter ändras
inte. Samtidiga gamla anrop behåller sina aktiva typer tills de returnerar.

Endast gamla pointer-cacheposter med exakt modul och klasskvalificering tas
bort. Hela ctypes-cachen töms aldrig. En andra begränsad passering fångar typer
från eventuella gamla pågående anrop. Korrigeringen accepterar inga indata,
target eller kommando och ger ingen generell kodexekveringskapacitet.

I den verkliga sessionen frigjordes **643 414** gamla typer. Privat reservation
föll från **6 332,742 till 2 308,625 MiB** efter två passeringar. Under följande
60 sekunder var förändringen **−0,05 MiB**. Chatten och användarens befintliga
testnod fortsatte vara igång.

En senare 60-sekunderskontroll av samma fortfarande öppna session mätte RSS
471,93→472,16 MiB, USS 441,15→440,96 MiB och privat commit
2 195,12→2 193,11 MiB. Det visar stabilitet under denna kontroll, inte att
den gamla sessionens historiska minnesreservation redan är borta.

Före korrigeringen gjordes en akut working-set-reclaim för fysisk marginal.
Den stoppade inte läckan och räknas inte som korrigering eller minnesvinst.
Efter den verkliga korrigeringen frigjorde en dokumenterad Windows-optimering
av oanvända heapcacher ytterligare cirka 88 MiB privat reserverat minne. Säker
QML-garbage collection och trimning av oanvända komponenter gav ingen väsentlig
ytterligare minskning i den gamla sessionen.

## Grundförbrukning och mätgränser

Den gamla processen behöll fortfarande betydande historiska allokeringar efter
korrigeringen. Detta är inte bevis för att 200–300 MiB redan uppnåtts.
En separat native-uppstart före optimering av förladdning mätte cirka 383 MiB
RSS för huvudprocessen och 518 MiB som högsta summerade RSS för dess ägda träd.
Det är en avgränsad tom uppstart, inte alla funktioner eller maximal last.

Elva tunga arbetsytor laddas nu via URL först när de används. Stängda inställningar
och EXT skapas också först vid första användning och behålls sedan för att bevara
utkast och sessioner. Startgrafen minskar från 125 QML-filer/2 394 305 källbyte
till **15/225 104**. Alla skapningsegenskaper
och deras levande bindningar finns före respektive komponents `onCompleted`.
Spelbackendens modul och värld initieras också först vid verklig användning.
Huruvida hela programmet håller ett minnesmål måste mätas efter dessa ändringar,
med ägda barnprocesser och tillgångarnas storlek tydligt angivna.

En sista separat native-körning med produktionsfonter, Direct3D och 1707×912
klientyta mätte följande efter tio sekunder per vy, utan externa uppdateringar
eller startade testnoder. Värdena före manuell GC används; GC ändrade dem inte
väsentligt. Alla fixturprocesser avslutades efter körningen.
Native-proben räknade två Qt-varningar men sparade inte deras text; den körningen
får därför inte beskrivas som varningsfri. De separata layout-/livscykeltesterna
sparar varningstext och avvisar nya produktionsvarningar.

| Vy | Huvudprocess RSS | Huvudprocess USS | Huvudprocess privat commit | Ägt träd USS |
|---|---:|---:|---:|---:|
| CODE | 356,88 MiB | 246,53 MiB | 774,58 MiB | 287,32 MiB |
| CRYPTO / wallet | 412,21 MiB | 300,11 MiB | 830,14 MiB | 340,69 MiB |

Summerad RSS för trädet var 480,53 respektive 535,71 MiB och kan dubbelräkna
delade bibliotekssidor. Privat commit för trädet var 849,91 respektive 905,04 MiB.
Detta är ärliga baslinjer för två tomma vyer, **inte ett uppnått tak på
200–300 MiB med alla funktioner under belastning**. CLI utan Qt är separat mätt
till cirka 42–47 MiB RSS för hela sitt ägda processträd i tomt terminal-/engångsläge.

RSS/arbetsmängd, USS och privat reserverat/committat minne är olika mått.
Windows storlekar från `memory_maps()` är regionstorlekar och får inte beskrivas
som verkligt residenta font-/DLL-kostnader. Sidbyte, cachetrimning eller att bara
visa nodens minne får inte användas för att hävda att appens läcka är åtgärdad.

## Verifiering

Regressionskontroller omfattar oförändrat antal typer och handtag efter 10 000
öppningar, korrekta Win64 ABI-storlekar, privata ACL:er och avvisad Everyone-ACL,
exklusiv skapning, append/truncate och icke ärvbara handtag. En verklig symlink-
kontroll kräver Windows-behörighet som denna testtoken saknade och hoppades över.
Kompatibilitetstestet bevarar gamla funktionsreferenser under samtidiga läsningar,
lämnar främmande pointer-typer orörda och kontrollerar fortsatt filpolicy.

Referenser: [ctypes.pointer och typcache](https://docs.python.org/3/library/ctypes.html#ctypes.POINTER),
[Windows HeapOptimizeResources](https://learn.microsoft.com/en-us/windows/win32/api/heapapi/nf-heapapi-heapsetinformation),
[säker trimning av oanvända QML-komponenter](https://doc.qt.io/qt-6/qqmlengine.html#trimComponentCache).
