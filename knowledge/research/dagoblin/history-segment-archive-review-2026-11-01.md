# DAGoblin: originalsignerade segmentarkiv och lokal lagringsspärr

Datum: 2026-11-01. **Lokal komponent; den nya historikpolicyn är ännu inte
accepterad av den ordinarie SDK-källans avkodare.**

## Ursprunglig avsikt

Bevara verkliga blockskapare, signerade originaltransaktioner, saldon och
noncer när aktiv historik avslutas. Noden får inte fortsätta på en ny bas
enbart för att en fil finns eller för att ett arkiv påstår ett kontotillstånd.

## Genomförande och tillitsgräns

Det nya segmentformatet innehåller ursprungliga manifest och blockbytes,
brytpunktskropp och en avslutande innehållskontrollsumma. Storlekar och antal
kontrolleras före motsvarande allokering. Varje aktivt segment har kvar
gränserna 4 095 block och 512 MiB rådata; varje batch högst 32 MiB rådata.

Läsaren kräver en separat verifierad tom bas för rätt epoch, källa och ankare.
Alla manifest återspelas med samma exekveringskärna som vanliga signerade
block och TX. Konton hämtas inte som tillitsfull ögonblicksbild från arkivet.
Manifestordning, wire-hashar, föräldrar, saldo, nonce, producentsekvens,
brytpunkt, avslutande kontrollsumma och exakt filslut måste stämma.

Efter varje verifierad batch släpps ursprungliga rådata och avkodade TX ur
arbetsvyn. Den nya tomma basen behåller inte äldre segment, rådata eller en
gammal filinläsningsfunktion. Helkedjeverifiering kan följa arkiven från den
separat låsta genesis-basen, med nästa bas härledd av föregående fulla
återspelning. Ett segmentarkiv är ingen quorumkvittens eller SDK-finalitet.

Den lokala lagringsfunktionen använder ett eget källbundet OWNER-märke och
en verklig exklusiv OS-filspärr. En reserverad temporär fil skrivs, synkas,
stängs och återspelas helt. Publicering använder en hårdlänk som nekar ett
befintligt målnamn. Befintliga slutarkiv skrivs aldrig över eller raderas;
även en återförsökt befintlig fil måste återspelas och synkas före kvittens.
Okända filer och felaktiga ägarmärken bevaras. Endast känd temporär data i
den ägda namnrymden återtas, efter kontroll av filidentitet och typ.

Kvittensen blir användbar först efter filkontrollerna och stängd arbetslease.
Fel eller avbrott lämnar nuvarande exekvering orörd. Detta är en verifierad
**processkraschgräns**. Beständighet för katalognamn vid fysisk strömförlust
är inte bevisad eller aktiveringsgrund här. Filsystem utan hårdlänkar nekar
publicering i stället för att välja en svagare ersättningsmetod.

## Provomfattning

Komponentproven omfattar två riktiga signerade 5 000-TX-segment och oberoende
återöppning/återspelning av deras hela kedja, flera manifest med originaldata
lästa från disk, förvanskade/trunkerade/omordnade filer, ändrad tillitsbas,
rådatagräns före allokering, ogiltig TX med omräknade wire-/filkontrollsummor,
I/O-fel, främmande filer, exklusiv lease, publiceringskapplöpning och två
faktiska processavslut. Symlänkfall körs endast där testkontot faktiskt får
skapa symlänkar; oförmåga loggas uttryckligen och är ingen sådan testmerit.
Exakta körresultat finns i det separata versionsbundna lokala provunderlaget.

Den aktuella hela Go-körningen passerade 474 prov, inklusive samtliga tidigare
442 och 32 nytillkomna fall/delfall, utan fel eller överhoppningar. De 45
berörda Python-proven passerade. Den ombyggda gemensamma WASM-verifieraren
accepterade fyra riktiga certifikat-/bevisfall och nekade 15 förvanskningar.
Testkontot kunde inte skapa symlänkar: de negativa symlänkvägarna har därför
ingen faktisk körmerit på denna värd. Kodens länkkontroller finns kvar.
Hela UI-sviten och fyra plattformars releasebinärer är inte omkörda här.

## Återstår före aktivering och leverans

Kanoniskt SDK-beslut för exakt brytpunkt, motsvarande tillstånds-/lagrings-
och återstartsintegration, arkivhämtning, diskbudget, Python/CLI/UI-bevisomfång
och nätverksacceptans återstår. Kvittensen aktiverar ingen levande nod och
ändrar ingen gammal genesis. Ingen genomströmnings-, monetär-, mining-/pool-
eller huvudnätsberedskap följer av dessa komponentprov. Ingen Git-push eller
fysisk enhetsuppdatering ingår i detta steg.

## Primärkälla

[Go:s os-dokumentation](https://pkg.go.dev/os) beskriver `Link` som skapande av
en hårdlänk och `File.Sync` som synkning av filinnehåll till stabil lagring.
Slutsatsen att även filnamnets katalogbeständighet måste behandlas separat
är vår konstruktionsavgränsning; filsynkning är ingen allmän hårdvarugaranti.
