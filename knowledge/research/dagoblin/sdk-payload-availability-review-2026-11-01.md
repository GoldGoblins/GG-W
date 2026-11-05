# DAGoblin: verklig payload från alternativ SDK-källa

## Avsikt och fynd

En full replika ska kunna exekvera certifierade block även om den ursprungliga
LAN-peeren undanhåller sin kopia. Ett certifikat får fortfarande inte förvandlas
till påstådd lokal payloadvalidering eller till en grafnod utan faktisk data.

SDK-validatorerna hade redan committad payload, men vanlig LAN GET läste endast
Python-nodens egen DAG-journal. En annan ägare kunde därför ha rätt SDK-data
utan att kunna erbjuda den till replikan. Dessutom delade standardklientens
ABCI-frågor SDK:ts globala klientlås med konsensus. Prov direkt på Ledger räckte
inte för att bevisa isolering genom den verkliga klientkopplingen.

## Beslut och implementation

Ett internt läsgränssnitt returnerar högst 32 KiB committade payloadbytes per
anrop. Selektorn består endast av blockhash, kanoniskt index och justerad
offset. Kontexten binds till begärd höjd, tillståndsrot och genesis. Förberedd
eller enbart staged data kan inte hämtas som committad; historiska frågor får
inte se senare index. Varken godtycklig sökväg, extern URL eller signerare ingår.

Frågan fångar en matchande tillståndsvy och en oföränderlig exekveringsreferens
under applikationens läslås. Kopiering av en begränsad chunk sker därefter utan
konsensuslåset. Två samtidiga payloadläsare tillåts, separat från fyra läsare
för det historiska bevisindexet. SDK-klientens vanliga ordning för muterande
ABCI-anrop behålls; endast Query går genom Ledger:s egen trådsäkra läsväg.

En separat återhämtningsarbetare läser ägda SDK-processer över loopback.
Den återanvänder en lokal HTTP-anslutning, kontrollerar lyssnarens processägare
vid anslutning/återanslutning och avvisar ändrad processgeneration. Den väntar
inte på kontrollerns lås för signering eller checkpointarbete. Processbyte,
stopp och konflikt kontrolleras under läsningen. Publika felkoder saneras.

En komplett SDK-verifierad ordning ger bara **hämtningsauktoritet**. Den ger
ingen lokal exekveringskvittens. Arbetaren går i föräldraordning, kontrollerar
sammanhängande offsets, längd och wire-digest, och kör sedan samma fullständiga
signatur-, TX-, konto-, föräldra- och noncevalidering som övrig antagning.
Först synkron journalantagning gör payloaden tillgänglig för vanlig autentiserad
LAN GET. Mottagaren verifierar i sin tur riktiga bytes och jämför exekveringen
med certifierade konto- och ordningsrötter innan komplett medlemskap publiceras.

TCP-handlers läser befintliga block och köar saknade hashreferenser; de gör
ingen SDK-RPC eller lång kryptografisk återhämtning. Köerna begränsas till åtta
poster per fast rosteridentitet och roterar mellan identiteter. En arbetare
hämtar högst åtta poster och 32 MiB per jobb med åtta sekunders deadline.
Minnesreservation och befintliga CPU-/RAM-/historikgränser gäller fortfarande.
Delvis antagen prefixhistorik överlever; ofullständiga block blir aldrig poster.
Lättklienten skapar ingen payloadarbetare och hämtar fortfarande ingen global
payload. CLI och desktop visar faktiska återhämtningsräknare separat.

## Verifieringens omfattning

Riktade Go-prov omfattar byteexakt chunkhämtning av ett committat 5000-TX-block,
återöppning, historisk pinning, avvisad förberedelse/staging, ogiltiga selektorer,
avbrott, samtidighetskvot och ändrade bytes. Ett särskilt prov använder den
verkliga SDK-klientfabriken: en pausad Query får inte hindra FinalizeBlock/Commit.

Arbetar-/transportproven använder riktiga signerade block, krypterade disponibla
ägarprofiler och autentiserad TCP. Deras quorumgräns är uttryckligen mockad.
De testar chunkändring, digestfel, avbrott, begränsade roterande köer,
föräldraordnad beständig framdrift, processbyte och CLI/QML-fakta.

Det separata processprovet använder fyra verkliga SDK-validatorbarn och tre
LAN-profiler på en Windows-värd. Originalpeeren vägrar lämna blocket via GET.
Den andra ägaren börjar utan Python-payload och får först manipulerade chunkbytes
efter verklig SDK-RPC. Ingen payloadjournal, lokal exekvering eller lokal
finalitet får då uppstå. När felinjektionen släpps hämtar den exakt det
committade 5000-TX-blocket från SDK:t och replikan får det via autentiserad LAN
GET, exekverar det och jämför de certifierade rötterna. Alla nod- och
validatorprofiler återöppnas med samma identitet och faktisk historik.

Felmodellen är avsiktlig injektion i disponibla processer, inte ett observerat
angrepp. Slutlig körkvittens binder resultaten till oförändrad kod, bred
regression, nybyggda verktyg och granskade källarkiv. Detta är inte fysisk
Linux-/telefonacceptans, maximal historikåterställning eller en BPS-mätning.

## Primärkällor och slutsatser

CometBFT beskriver separationen mellan committat tillstånd, kandidatdata och
återexekvering av det redan lagrade beslutade blocket. Vår slutsats är att
payloadtillgång måste bindas till verklig committad data och rätt rot, medan
klientens lokala fullständiga exekvering förblir ett separat verifieringssteg.
[ABCI++-krav](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md).

Den använda SDK-versionens klientfabrik delar en mutex mellan standardklienter.
Vår smala Query-överkoppling behåller ordningen för alla muterande anrop och
använder applikationens egna lässkydd för frågor. Det verifieras även genom
den faktiska klientfabriken, inte enbart direktanrop till applikationsmetoder.
[Klientfabrikens primärkälla](https://github.com/cometbft/cometbft/blob/v0.40.0/proxy/client.go).
Källorna och den lokala versionspinnade modulkoden kontrollerades 2026-11-01.

## Kvarvarande krav och antaganden

En tillgänglig ärlig källa och tillräckliga lokala resurser behövs fortfarande.
Ett certifikat kan inte skapa förlorade bytes. Alla källors samtidiga förlust,
långa partitioner, maximal 32 MiB-payload/full historik, fysisk bandbredd och
uthållighet kräver ytterligare acceptans. Det interna ABCI-/RPC-gränssnittet är
ägt och lokalt; ingen ny publik åtkomst eller produktionsaktivering tillförs.

Den committade historiken prunas inte här. Prototypens 4095-poster- och
512 MiB-gränser kvarstår. Äldre oförenliga ägargrenar, monetär modell,
mining/pooler, publikt medlemskap, mållast och oberoende säkerhetsgranskning
återstår. Inget huvudnät, ingen uppmätt miljon TX/s och ingen slutlig
hundraprocentig säkerhet intygas.
