# DAGoblin: strikt JSON med färre tillfälliga värdekopior

## Avsikt och konstaterat problem

Behåll identiska signerade data, noncer, utbud och verifieringsregler samtidigt
som stora tillåtna nyttolaster kan hanteras under nodens befintliga resurstak.
Det tidigare fyrnodsprovet med 50 000 TX passerade inte efter SDK-loggfixen.
Denna ändring är en separat, mätbar allokeringsminskning, inte ett påstående
att hela nätfallet eller kapacitetsmålet därmed fungerar.

## Fynd och ändring

Den tidigare dubbelfältskontrollen gick genom varje JSON-token, inklusive
stora base64-strängar. `Decoder.Token` materialiserade värdesträngen även
fast kontrollen bara behövde fältnamn och struktur. Därefter läste den vanliga
typade avkodaren samma data igen.

Syntaxen kontrolleras nu först med standardbibliotekets `json.Valid`.
En separat begränsad strukturgång läser avkodade objektnamn och behåller
samma djupgräns. Värdesträngar hoppas över direkt i originalets byteföljd.
Fältnamn avkodas fortfarande med standardbiblioteket, så exempelvis `a` och
`\u0061` upptäcks som samma namn. Därefter körs den befintliga typade
`Decoder.DisallowUnknownFields` som tidigare. Kanonisk jämförelse och alla
block-, transaktions- och signaturkontroller ligger kvar.

Standardbiblioteket är syntaxauktoritet; strukturgången får endast köras
efter godkänd `json.Valid`. Metoderna är privata. Ingen egen allmän JSON-
avkodare eller ny extern parserdependency införs.
[Go JSON-dokumentation](https://pkg.go.dev/encoding/json),
[Go:s strömavkodare](https://go.dev/src/encoding/json/stream.go).

## Verifiering och gränser

Den tidigare oberoende tokenläsaren sparas endast som testorakel. Proven
jämför accepterande och avkodade resultat för strukturerade exempel,
djupgränser, escaped dubbletter, Unicode-/UTF-8-ersättningsfall, okända
typade fält, 20 000 deterministiska bytefall och varje enbytesmutation av
ett nästlat dokument. Ett separat 16 MiB-strängprov kontrollerar identiskt
resultat och högst 70 procent av den tidigare totala allokeringen.

I det första separata Windows-provet sjönk totalallokeringen från
167 779 984 till 83 897 520 byte för detta strängfall. Det är total tillfällig
allokering i ett isolerat JSON-prov, inte högsta processminne, nätkapacitet
eller en mätning av nya unika transaktioner. Slutliga regressionsresultat
och fyrnodsresultat binds separat till exakt byggda källor.

Det maximala SDK-nätfallet, full historik-/diskpolicy, fysisk uthållighet,
målhastighet, offentligt medlemskap, monetär modell, mining/pooler och
oberoende säkerhetsacceptans får inte markeras klara av denna optimering.
