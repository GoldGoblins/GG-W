# Beständiga certifierade konfliktbevis

Datum: 2026-10-31. Omfattning: det privata fasta SDK-kvorumet, lokala ägda
processer och autentiserad LAN-transport. Ingen publik nätaktivering.

## Ursprunglig avsikt och fynd

Kanonisk tillhörighet och konton ska bygga på riktig konsensusdata. En
motstridig certifiering får aldrig döljas av en cache, omstart eller en annan
lokal controller. Kodgranskningen fann att samma höjd kunde skrivas över i
beviscachen och att lagret sparade ett fel men förlorade det andra signerade
certifikatet. Validatorägare frågade dessutom alltid sin egen källa när den
fanns, och kunde därför missa en annan ägares konfliktbevis.

## Beslut och implementation

Det versionsmärkta beviset innehåller exakt två olika certifierade block på
samma höjd, under identisk fast genesis. Det är deterministiskt sorterat och
begränsat till mindre än 256 KiB inklusive utrymme för transportsvaret. Båda
certifikaten kontrolleras oberoende med SDK före en ny felspärr eller stopp.
En strukturell kontroll, en peers anklagelse eller bara texten FAULT räcker inte.

Nodprofilens golvformat v2 lagrar beviset tillsammans med det senaste golvet.
Validatorprofilen får ett versionsmärkt separat bevisfält. Äldre profiler och
äldre felspärrar bevaras utan identitetsbyte eller återställning av nonce.
En äldre giltig konflikt får stoppa även ett senare golv, men sänker inte det.
Lagringsgränserna är fortfarande explicita: 544 KiB för nodens konsensuspost
och 1 MiB för validatorns hela signerade profil, inklusive skyddade nycklar.

En controller försöker spara det verifierade beviset i både ägarens nodprofil
och sin egen validatorprofil innan den exponerar sparat bevis. Vid skrivfel
stannar den ändå och rapporterar lagringsfelet. Ett bevis som verkligen hann
sparas kan verifieras vid nästa öppning även om skrivreturen förlorades.
Nya eller tidigare ostarterade validatorprofiler kan inte användas för att
kringgå ägarens sparade verifierade konflikt.

Bevisarbetaren upptäcker olika certifikat från flera lokala controllers utan
att skriva över det första. Den autentiserade FAULT-responsen kan nu bära
det versionsmärkta beviset. Mottagaren verifierar båda certifikaten, sparar
beviset och stoppar sina relevanta validatorer. Ägare frågar växelvis sin egen
och de andra ägarnas källor. Cache-/TCP-låset hålls inte under SDK, skrivning
eller processstopp. Även en stannad controller kan bidra med ett redan sparat
bevis. Återöppning verifierar bevisen igen innan de annonseras.

Olika giltiga uppsättningar av commit-signaturer för samma block är samma
certifikatidentitet. Sidbevis jämför nu certifierat block och exakt tillstånd,
inte byteidentitet hos en legitimt varierande commit-signaturlista. Båda
varianterna måste fortfarande passera SDK-verifiering.

CLI-arkivets readinessmetadata skiljer nu den äldre stressmodens ACK från den
valfria SDK-certifierade privata DAG-modens ordnings- och kontobevis. Publikt
testnät, huvudnät, ekonomiska transaktioner och kapacitetsmålet förblir avstängda
respektive obevisade.

## Verifiering och dess gränser

Riktade policyprov täcker avvisad andra signatur utan felspärr, beständighet,
äldre konflikt under nyare golv, cacheöverskrivning, verklig autentiserad
transport till replika/lättklient, lagringsfel före/efter commit och oberoende
SDK-kontroll vid återöppning. SDK-gränsen mockas i dessa små policyprov;
separata processprov använder den verkliga native- och WASM-verifieraren.

Go-fixturen skapar två olika block med riktiga kvorumsignaturer från uttryckligt
disponibla testnycklar för samma signerade LAN-genesis och höjd. Den skapar
också en giltig variant med tre i stället för fyra signaturer för samma block.
Detta är avsiktlig felinjektion, inte ett påstått observerat angrepp mot
konsensus eller ett bevis på att ärliga validatorer producerar dubbla commits.

Processprovet använder tre ägda nodprofiler och fyra riktiga SDK-barn på en
Windows-värd. Det kontrollerar spridning till andra ägaren och observatören,
beständigt stopp av alla fyra barnen utan sänkta golv samt återöppning av både
nod- och validatorprofiler utan att felspärrade signerare startas. Bred regression,
vanliga replika-/lättklientflöden, WASM och källpaket kontrolleras separat mot
fryst kod före intern slutmarkering.

## Återstående krav

Detta löser certifierade kvorumkonflikter. Producenters konkurrerande
payloadgrenar, datatillgänglighet vid undanhållande, kandidatinsamling/pruning,
maximal payloadåterställning och fysisk uthållighet återstår. Det fastställer
inte publik medlemskapspolicy, tokenomics, mining/pooler, kapacitetsmålet eller
huvudnätsberedskap. Någon automatisk upplåsning eller grenreparation efter ett
giltigt säkerhetsbrott införs inte.
