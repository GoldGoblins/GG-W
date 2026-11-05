# DAGoblin: samma signaturprofil med mindre dubbelarbete

## Ursprunglig avsikt

Minska verklig verifieringskostnad utan att ändra vilka signerade block och
transaktioner som godkänns. Alla meddelanden ska fortfarande verifieras och
alla nonce-, saldo-, föräldra-, ägar- och beständighetsregler ska behållas.

## Fynd och matematisk slutsats

Den tidigare Go-koden kontrollerade både författarpunkten A och signaturpunkten
R:s grupptillhörighet separat före standardverifieringen. Den granskade
Go 1.27.3-verifieraren kräver kanonisk S och jämför signaturens R-bytes med
den kanoniska kodningen av `R = [S]B - [H(R,A,M)]A`, utan kofaktormultiplikation.
Den exakta kompilatorkällan lästes från den pinnade, lokala Go-distributionen:
`src/crypto/internal/fips140/ed25519/ed25519.go`.

Vår slutsats från denna kod är att när A redan är kanonisk och ligger i den
primtalsordnade undergruppen, ligger det rekonstruerade R i samma undergrupp.
Bytejämförelsen binder också dess kanoniska kodning. Identitetspunkten behöver
fortfarande avvisas uttryckligen enligt GG:s strängare profil. Detta resonemang
gäller den granskade exakta ekvationen; generell Ed25519-verifiering kan använda
en kofaktormultiplicerad ekvation.
[RFC 8032, verifiering](https://www.rfc-editor.org/rfc/rfc8032.html#section-5.1.7).

## Beslut och kod

- Endast den granskade Go-versionen 1.27.3 använder den härledda R-egenskapen.
  Andra kompilatorversioner behåller den tidigare fulla R- och S-kontrollen.
- Författarpunktens fulla profilkontroll finns kvar. Dess tidigare cache håller
  högst 256 validerade publika punkter. Inga meddelande-, signatur- eller privata
  verifieringsbeslut läggs i någon cache.
- Publik nyckel och signatur kopieras till egna fasta 32-/64-bytebuffertar.
  Samma bytes används genom hela kontrollen. Identitets-R avvisas uttryckligen.
- Varje i övrigt godtagbar signatur går fortfarande genom standardbibliotekets
  faktiska verifiering av hela meddelandet och signaturen. Signaturprofilens
  namn, signerade bytes och SDK:ns separata röstregler ändras inte.

## Verifierad omfattning

Den isolerade kandidaten passerade 206 Go-prov utan överhoppningar. En separat
referens använder den tidigare fulla kontrollen av båda punkterna och S.
Jämförelsen omfattar 1 000 deterministiska giltiga meddelanden samt ändrade
nycklar, meddelanden, signaturer och felaktiga längder. Alla åtta torsionsklasser
prövas i 192 konstruerade fall. Åtta identitetsfall uppfyller standardekvationen
men måste fortfarande avvisas av GG-profilen; 168 övriga torsionsfall avvisas.

Samma 210 externa Wycheproof-fall och fyra explicita kofaktorfall gav identiska
beslut i aktuell Python, native Go och faktiskt körd Go/WASM. Både den nya
ekvationsvägen och den fulla kontrollvägen provades.
[Wycheproofs originaldata](https://github.com/C2SP/wycheproof/blob/main/testvectors_v1/ed25519_test.json).

Ett lokalt fasprov använde en verklig signerad 5 000-TX-batch som återexekverades
vid de nödvändiga ABCI-faserna. Antalet unika transaktioner är fortfarande
5 000. Processen hade samma två Go-processorer, 256 MiB mjuk minnesbudget och
512 MiB hård barnprocessgräns. Ett par körningar gav:

| Fas | Före, sekunder | Kandidat, sekunder |
|---|---:|---:|
| CheckTx | 0,484 | 0,327 |
| PrepareProposal | 0,481 | 0,335 |
| ProcessProposal | 0,478 | 0,322 |
| FinalizeBlock | 0,484 | 0,328 |

Detta är cirka 30–33 procent kortare faser i just detta lokala prov, inte en
uthållig nätmätning eller statistisk garanti. Observerat toppminne var nära
oförändrat. Canoniskt tillstånd publicerades fortfarande först vid Commit och
full signerad historik återöppnades till samma tillstånd.

Kandidaten passerade även det verkliga fyr-SDK-provet med en 50 000-TX-payload,
undanhållen LAN-källa, skadade svar, exakt återhämtning till annan ägare/replika
och återöppning av alla tre nod- och fyra validatorprofiler. Den ursprungliga
90-sekundersgränsen per väntesteg behölls. Milstolparna var cirka 58,4, 95,8
och 139,3 sekunder från provets början. Hela körningen tog alltså 139,3 sekunder;
det är inte ett påstående om en total 90-sekunderskörning. Alla processer körde
på en ägd Windows-värd. Native-kandidaten och dess källinventering valdes
uttryckligen endast inom det isolerade provets process.

## Efter sammanförandet och kvarstående krav

Ordinarie Go-indata jämförs byte för byte med den provade kandidaten innan
komponentresultat återanvänds. Fulla native-/WASM-byggen, Python-/UI-integration,
SDK-roller/fel, beroendeskanning och det oförändrade stora provet för ordinarie
kod förseglas separat. Den öppna appen och fysiska noderna startas inte om här.

5 000 TX/block vid hundratals block/s är fortfarande inte verifierat eller
uppnått. Historik-/diskpolicy, lång partition och disktryck, fysisk fel- och
uthållighetsacceptans, offentligt medlemskap, monetär modell, mining/pooler
och oberoende säkerhetsacceptans återstår. Ingen fullständig leverans eller
huvudnätsberedskap följer av den här optimeringen.
