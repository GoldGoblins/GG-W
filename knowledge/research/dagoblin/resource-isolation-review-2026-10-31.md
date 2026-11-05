# DAGoblin: ingressisolering och sann återhämtningsstatus

## Avsikt

En långsam eller överbelastande peer ska inte tömma de andra nodernas
arbetsutrymme. CLI äger den verkliga noddriften; desktop återger dess faktiska
status. Att läsa en signerad post innebär aldrig att dess transaktioner har
godkänts eller att dess data är tillgängliga för konsensus.

## Fynd

Transportens tidigare ackumulerade byte-, ram- och anslutningsräknare kunde
stänga hela sessionen. Motorns försöksbudget hade samma livstidsproblem.
PAGE stannade dessutom vid en avvisad kandidatvariant och kunde därmed hindra
senare, giltiga block från en annan producent i samma peers logg.

Peer-index och lokalt producentindex låg i samma numeriska namnrymd. Ett test
med varierad rosterordning visade att en fjärrpeers trafik därför kunde tömma
en lokal producents kredit. De två sorternas kreditkonton har nu skilda nycklar.

## Beslut och implementation

Beständiga NodeProfile-sessioner använder återfyllande krediter per ingress.
En nekad kredit stoppar den begäran och utarmar inte andra konton.
Räknarna behålls som verklig diagnostik. Ändliga RAM-labb behåller sina
uttryckliga sessionsbudgetar. Hårda gränser för lagring, blockstorlek,
minnesreservationer, antal jobb och deadlines gäller fortfarande.

Före autentisering begränsas trafik både totalt och per källadress. Efter
verifierad signatur binds råtrafiken till den parade peer-identiteten.
En källadress får högst två samtidiga handlers av totalt fyra; en aktiv
privat roster tillåter endast sina konfigurerade adresser. Utgående trafik
använder den valda lokala lyssningsadressen. Adresskontroll ersätter inte
kryptografisk identitet. Samlokaliserade profiler delar adressens kapacitet.

Föräldralösa, signerade kuvert har både en global RAM-gräns och en gräns per
peer: högst halva antalet och halva byteutrymmet. Ett överskridande i en
beständig profil kan skjutas upp utan att kuvertets payload sparas i RAM.
Det är inte validering, tillgänglighetskvittens eller finalitet. Fullständig,
föräldraordnad payloadhämtning behövs fortfarande.
Uppskjutna hashreferenser återhämtas från den beständiga observationen även
efter förlorat RAM. Begränsade GET-batcher roterar mellan dem och okända
föräldrar, så att en tidig olöslig hash inte svälter senare arbete.
Karantänavvisade grenar ingår inte i dessa vanliga återförsök.

Beständig PAGE skiljer nu mellan:

- **Observerad position:** autentiserade och klassificerade poster som lästs.
- **Validerat prefix:** sammanhängande poster med faktiskt antagen, beständig
  payload. Ett avvisat eller uppskjutet block lämnar ett hål.
- **Separat upplösning:** först när den riktiga payloaden senare antagits
  beständigt kan hålet räknas som validerat.

Endast ett korrekt autentiserat END får bevara sidans observationer.
Karantänkvotens specifika avslag får passeras; godtyckliga protokollfel gör
det inte. Status `SCANNED_WITH_REFUSALS` visar olösta hål. `CAUGHT_UP` får
inte dölja dem. Detta är loggstatus, inte ett konsensusbevis.
CLI och båda berörda desktopvyer visar lästa poster, sammanhängande validerat
prefix och olösta poster separat. En lyckad senare GET uppdaterar även den
senast observerade sidans status. Ofullständiga eller motsägande publika
CLI-räknare blir oobserverad status, aldrig ett nytt synkroniseringspåstående.

En separat append-only SQLite-tabell sparar observationer och upplösningar.
Små signerade huvuden binder position, prefix och händelsekedja till den
befintliga ägarprofilen. Befintlig DAG-/tokenjournal ändrar inte format.
Schema 1 migreras transaktionellt efter ägar- och containerkontroll, utan
återställning av nycklar, historik eller nonces. Full kryptografisk återspelning
av DAG-historiken krävs fortfarande före lyssning. Okänd skrivutgång kräver
återöppning; inget nytt antagningskvitto konstrueras från en observation.

## Verifieringens omfattning

De riktade testerna använder disponibla krypterade profiler och verklig
autentiserad TCP över tre separata loopbackadresser. De kontrollerar andra
peers och lokal produktion efter kreditavslag, ackumulerade räknare över
äldre livstidsgränser, handlerisolering, uppskjutet RAM, avvisat PAGE-block
följt av en ärlig producent, felaktigt END, omstart, manipulerad scan-historik,
schemaövergång och skrivfel både före och efter faktisk commit.

Det separata processprovet använder fyra riktiga SDK-validatorprocesser.
En replika läser först en kandidat som dess lokala karantänkvot avvisar.
Först efter verkligt SDK-val ska föräldraordnad GET, full payloadexekvering
och jämförda kontorötter kunna lösa hålet. Exakta resultat, oförändrad
källkod, bred regression och källarkiv förseglas i den privata körkvittensen;
beskrivningen i sig är inget godkänt testresultat.

## Primärkällor och slutsatser

Libp2p beskriver separata resursgränser för peer, anslutning, protokoll och
system. Vår slutsats är att samma uppdelning behövs i den egna privata
transporten; bibliotekets skydd har inte därmed införts automatiskt.
[Resurshanterarens dokumentation](https://github.com/libp2p/go-libp2p/blob/master/p2p/host/resource-manager/README.md).

Libp2p behandlar särskilt anslutningar före identifiering, begränsad
samtidighet och separering av resursdomäner. Vårt adressfilter och våra
kvoter är avgränsade till den fasta privata rostern.
[DoS mitigation](https://libp2p.io/docs/dos-mitigation/).

CometBFT 0.40 skiljer mottagning och lagringsgränser från applikationens
transaktionsvalidering. Vår observationstabell följer samma principiella
åtskillnad; den ersätter inte CheckTx, SDK-val eller egen exekvering.
[Mempool i den använda versionslinjen](https://github.com/cometbft/cometbft/blob/v0.40.0/docs/core/mempool.md).
Källorna kontrollerades 2026-10-31.

## Öppna krav och antaganden

Den fasta rostern har tre privata peers. Detta är inte en publik Sybil- eller
DoS-policy. Två peer-identiteter på samma maskin är inte oberoende felområden.
Delad CPU, disk och operativsystem kan fortfarande överbelastas; testerna
bevisar inte perfekt schemaläggningsrättvisa eller obegränsad drift.

Kandidatinsamling/pruning, maximal payloadåterställning, undanhållande,
ägaråterhämtning för gamla oförenliga signeringsgrenar, fysisk uthållighet,
publikt medlemskap, monetära regler, mining/pooler och oberoende
säkerhetsacceptans återstår. Prototypens 4095-postergräns finns kvar.
Ingen uthållig kapacitet på hundratals block/s, huvudnätsberedskap eller
hundraprocentig säkerhet intygas. Ingen appomstart eller enhetsuppdatering
ingår i denna lokala granskning.
