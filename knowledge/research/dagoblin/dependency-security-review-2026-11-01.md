# DAGoblin: säkerhetsuppdateringar i Go-beroenden

## Ursprunglig avsikt

Behåll verkliga signerade transaktioner, producentidentitet, beständig historik
och samma CLI-/Desktop-källa. Granska också de bibliotek som faktiskt följer
med det byggda nätverksprogrammet innan nästa gemensamma publicering och prov.

## Fakta och fynd

Go-projektets officiella `govulncheck` 1.9.0 kördes mot de fyra nybyggda
native-målen. Databasen rapporterade senaste ändring 2026-10-27. De tidigare
beroendena matchade 18 publicerade rapporter. Symbolträffar kan omfatta vilande
kodvägar och bevisar inte att varje fel kan utnyttjas med vår konfiguration.
[Go:s metodbeskrivning](https://go.dev/doc/security/vuln/),
[verktygets omfattning](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck).

Den statiska importkedjan till gamla DTLS-v2 gick via SDK-node, libp2p,
WebRTC-udpmux och gamla STUN-paketet. Libp2p 0.48 använder STUN-v3 i samma
komponent. Det tar bort den gamla kryptobiblioteksvägen ur vårt native-bygge.
[Upstream-koden i 0.48](https://github.com/libp2p/go-libp2p/blob/v0.48.0/p2p/transport/webrtc/udpmux/mux.go),
[DTLS-rapporten](https://pkg.go.dev/vuln/GO-2026-4479).

Övriga träffar omfattade bland annat DTLS-/STUN-parsningsfel och HTTP/2-/gRPC-
minnes- och kraschfel. De berörda beroendena uppdateras från upstream; ingen
egen omskrivning av kryptografiska algoritmer görs här.
[DTLS-parser](https://pkg.go.dev/vuln/GO-2026-6165),
[gRPC-minne](https://pkg.go.dev/vuln/GO-2026-6348),
[gRPC-headerfel och versionsgrenar](https://pkg.go.dev/vuln/GO-2026-6443).

## Beslut och låsningar

| Bibliotek | Tidigare | Ny låsning |
|---|---|---|
| go-libp2p | 0.47.0 | 0.48.0 |
| pion/dtls/v3 | 3.0.11 | 3.1.5 |
| pion/stun/v3 | 3.0.0 | 3.1.7 |
| x/crypto | 0.54.0 | 0.58.0 |
| x/net | 0.57.0 | 0.62.0 |
| x/text | 0.40.0 | 0.43.0 |
| grpc | 1.82.1 | 1.83.2 |

Den valda x/net-versionens deklarerade beroenden kräver de högre x/crypto-
och x/text-versionerna. Gågrenens gRPC-fix är 1.83.2; den första kandidaten
med 1.83.1 hade fortfarande en säkerhetsträff och förkastades. Go:s normala
modul- och checksummehantering används. Källans modul- och sum-lås uppdateras
avsiktligt, medan SDK:n behåller 0.40.0 och sina två separat granskade
resurspatchar. Inga quorum-, signatur-, utbuds- eller ägarregler ändras.

Go-språknivån är nu 1.26. Installationskontrollen för lokal Linux-/Termux-Go
kräver minst den pinnade verktygsversionen 1.27.3, liksom Windows-byggets
versionslåsning. Äldre eller felaktigt rapporterade kompilatorer avvisas före
byggförsök. Detta är en verktygsgräns för den granskade versionen.

## Granskning av återstående modulvarningar

Den korrigerade privata Windows-kandidaten gav inga träffar på kända sårbara
funktioner i binären. En modulvarning för den övergivna OpenPGP-delen i
x/crypto kvarstår; den delen finns inte bland programmets importerade paket.
Varningen behålls i råresultatet och dess tillämplighet redovisas separat.

Den lokalt härledda SDK-modulen kan försvåra automatisk versionsmatchning.
Därför kördes en separat kontroll mot originalets 0.40.0-metadata, utan lokal
module-ersättning. Modulvarningen GO-2025-3442 omfattar dels gamla legacy-
blocksync före 0.38.17, dels `internal/blocksync` före 1.0.1. Vårt 0.40-bygge
importerar legacy-sökvägen och saknar den senare interna paketsökvägen.
Officiell paketbaserad scanning rapporterade inga kända sårbara importerade
paket, inklusive SDK:n. Modulvarningen tas inte bort ur originalresultatet.
[Rapportens separata paket- och versionsintervall](https://pkg.go.dev/vuln/GO-2025-3442).

## Verifiering och kvarstående krav

Den isolerade kandidaten passerade samma 204 Go-prov, utan överhoppningar,
inklusive fyra verkliga Python-signerade block med 5 015 TX. Kandidatens
byggfil, Go-prov och beroendeskanning bands till samma oförändrade källor.
Källändringarna förs därefter in i ordinarie kod. Nya fyrmåls-/WASM-byggen,
Python-/UI-regressioner och verkliga SDK-integrationsprov efter sammanförandet
måste förseglas separat. Fysisk Linux-/Termuxkörning följer inte av crossbyggen.

Scanning täcker publicerade databasrapporter och sina analyserade kodvägar.
Okända sårbarheter, protokollets ekonomiska modell och oberoende acceptans
kräver annan granskning. Det tidigare 50 000-TX-provet missade sin ursprungliga
90-sekundersgräns per väntesteg; det längre lyckade diagnosprovet ändrar inte
det resultatet. Uthålligt kapacitetsmål, historik-/diskpolicy, fysisk fel- och
uthållighetsacceptans, offentligt medlemskap, monetär modell, mining/pooler
och oberoende säkerhetsacceptans återstår. Ingen release- eller huvudnäts-
beredskap förklaras genom denna ändring.
