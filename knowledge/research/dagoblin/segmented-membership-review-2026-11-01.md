# DAGoblin: verifierbara konton, skapare och ordning över segmentgränsen

Datum: 2026-11-01. Lokal komponentgranskning; gamla LAN-sessioner uppgraderas
inte automatiskt och publik ekonomi eller fysisk acceptans följer inte härav.

## Ursprunglig avsikt

CLI:s verkliga konto-/nodtillstånd ska gå att visa korrekt i Desktop. En
skapare måste vara identifierbar även när flera andra noder verifierar samma
block. En segmentövergång får inte förväxla lokala blocknummer med globala,
återställa nonce eller ge en gammal uppgift ett nytt bevisomfång.

## Konstruktion och bevisomfång

Nya konto-, block- och ordningsbevis binder hela det SDK-valda segment-
commitmentet, native-tillståndsrot, höjd och låst genesis. Kontots Merklebevis
verifierar verkligt saldo och nonce. Blockbeviset verifierar den valda
ordningsroten och härleder skaparnyckeln från den låsta producentlistan.

Ett block visar både lokalt index inom aktiv epoch och globalt index. Globalt
index och producentsekvens är decimalsträngar på den publika wire-nivån;
verifieraren återställer exakt heltal för den ursprungliga Merkleberäkningen.
Det undviker avrundning i JavaScript. Ett gammalt bevis kan inte flyttas till
en ny epoch, byta skapare eller få ett nytt globalt index utan att nekas.
Varje ordningssida innehåller hela sitt föreskrivna intervall, med samma
verifierade regel för duplicering av udda Merkle-noder.

Noden behåller fyra olika, oföränderliga verifierade DAG-vyer i RAM, med högst
4 095 metadataposter per vy och sex konton. Varken råpayload, gammal
exekveringsgraf eller en DB-lease följer med. Frågor fångar vyn kort under lås
och räknar sedan ut beviset utanför konsensus-/lagringslåsen. Fyra samtidiga
proof-frågor tillåts; ytterligare frågor nekas som upptagna. Ett borttaget
historiskt cacheläge ersätts aldrig med nuvarande saldo eller epoch.

Efter återstart byggs cachevyerna ur den fulla originalsignerade arkiv- och
aktiva återspelningen. Provisoriska data under läsning blir inte en publik
lyckad uppstart om filslut, kontrollsumma eller sparade tillstånd inte stämmer.

Python och webbläsarvärden använder en gemensam, headless verifiering av den
ägda genesis-låsningen. Python-adaptern kör därefter den riktiga SDK-
verifieraren själv och kräver de nya bevisflaggorna och samma commitment.
Den accepterar inte en inkommande `verified`-boolean som ersättning.
Generisk native-start/export kan hantera en uttrycklig v4-källa; befintliga
bundna källor byts inte genom ett nytt startanrop. CLI-export och browser-
värden använder samma bevisformat och tillitslåsning.

Den publika kvittensen säger **verifierat medlemskap i aktivt segment**.
Den säger inte full historikåterspelning, arkivtillgänglighet, globalt
blockmedlemskap i ett stängt segment eller finansiell slutlighet för en
publik valuta. Modellen är fortsatt producentägda icke-finansiella test-TX.

## Prov och kvarvarande integration

De riktade proven täcker riktiga signerade TX före/efter brytpunkt, konton,
skapare, globalt/lokalt index, fel epoch och beviskontext, borttagna/dubbla
ordningsposter, återstart, begränsad cache/frågekredit samt en blockerad
historisk fråga som inte får stoppa ett nytt commit. Ett stort heltal över
JavaScripts exakta talområde provas som **serialiseringsvektor**, inte som
återspelning av så många verkliga block. De distribuerade publika test-
vektorerna innehåller giltiga SDK-testsignaturer, inga privata nycklar och
ingen påstådd fysisk körmerit. Projektionens mockade enhetsprov är inte
bevis för konsensus; faktisk native-/WASM-/SDK-körning redovisas separat.

Egen kodgranskning gav också ett konkret allokeringsprov vid publik proof-
inläsning. Ett giltigt litet JSON-hölje med många tomma, ogiltiga vittnen
var 180 043 byte men allokerade 34 585 968 byte före semantisk avvisning.
Native- och WASM-ingångarna använder nu samma tidiga samlingskontroll:
högst 128 arrayposter och 64 fält per objekt före typad avkodning. Det
rymmer alla redan tillåtna format, inklusive 128 native-TX, 32 ordnings-
vittnen och högst 12 Merkle-syskon. Samma angreppsprov avvisades därefter
med 664 bytes allokering. Den ursprungliga misslyckade mätningen bevaras
separat och skrivs inte om till ett godkänt prov.

På den korrigerade koden passerade 532 Go-prov, inklusive samtliga tidigare
509. Fyra native-mål och WASM byggdes om utan att ersätta den aktiva appens
verktyg. Ett faktiskt fyra-SDK-processprov på Windows valde en segmentgräns,
fortsatte med en avstängd validator, återhämtade den och startade om alla fyra.
Totalt hanterades 10 001 signerade TX. Nya konto-/block-/ordningsbevis från
tre riktiga SDK-kvittenspaket verifierades även genom Python-adaptern.

62 riktade Python-/browserprov passerade, inklusive en localhost-värd med den
verkliga v4-låsningen och fyra-frågegränsen. Sex publika medlemskapspaket
godkändes i gemensam WASM/native/Python, och 49 mutationer nekades av alla
tre. Äldre giltiga proof-format och deras negativa fall provas separat på
samma bygge. Det är fortfarande verifierat medlemskap, inte en lätt klients
fulla återspelning, fysisk Linux/Termux-körmerit eller ett genomströmningsprov.

Full LAN-versionsförhandling, producentens nya exekveringskontext och
atomisk NodeProfile-aktivering genom en SDK-vald övergång återstår, liksom
Desktop-bindningar för det nya bevisomfånget. Hämtning av stängda arkiv,
lagringsbudget, strömförlustbeständighet, monetär modell, mining/pooler,
målkapacitet och den samlade fysiska acceptansen förblir öppna krav. Ingen
Git-push, bootstrapöverföring eller omstart av den aktiva Desktop-appen görs
av denna komponent.
