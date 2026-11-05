# Generella konton: autentiserad lagringskärna under integration

Detta dokument beskriver det första separata kärnsteget. Den efterföljande
[native-integrationen](general-account-application-review-2026-11-03.md)
kopplar kärnan till en uttryckligt ny applikationsversion. CLI-/Desktop-
integrationen och fullständiga nätacceptansen är fortfarande egna krav.

## Ursprunglig avsikt

En användares riktiga signerade kontoaktivitet ska vara samma informationskälla
i CLI och Desktop. Ett konto ska inte vara begränsat till laboratoriets fyra
validatorägda startkonton. Nya konton får inte innebära gratis saldo, rösträtt
eller uppdiktade miningbelöningar.

## Fakta och fynd

Det befintliga finansiella nätet använder fyra konton, fyra validatorer och
sex producenter. Konto-Merkleträdet har fyra blad, kontobevis två syskon och
betalningskontrollen kräver avsändare och mottagare i genesislistan. Den
befintliga exekveringen räknar om hela fyrakontoroten efter en genomförd
betalning. Att bara ta bort längdkontrollerna skulle inte skapa en fungerande
allmän kontomodell.

`financial_accounts.go` tillför därför en separat, ännu ej aktiverad kärna.
Den ändrar ingen befintlig genesis, konto- eller transaktionskodning,
source-v1/v2/v3, native-applikation eller finansiell sessionsregel.

Kärnan har ett immutabelt AVL-träd med innehållsadresserade noder. Varje nod
binder kontonyckel, saldo, nonce, ordnade barnreferenser, höjd, kontoantal,
delsumma och hash av uttryckliga regler. Regelhashen binder i sin tur genesis,
maximalt kontoantal och maximalt totalsaldo. Även tomma rötter är bundna till
reglerna. Kontonycklar följer den befintliga kanoniska prime-order-profilen.

Nya noders nonce kodas som decimalsträng för att behålla hela uint64-värdet i
framtida JSON-klienter. Den äldre typen `Account` och signerade betalningarnas
befintliga bytekodning ändras inte. Beloppstext är kanonisk och högst 20 tecken;
addition och kontoräkning kontrolleras före beräkning så att de inte kan slå runt.

## Kodbeslut

Uppdateringar kopierar den berörda sökvägen. Äldre rötter förblir oförändrade.
Medlemskaps- och frånvarobevis innehåller högst 64 noder. Verifieraren kräver
en separat betrodd rot och regler från anroparen, kontrollerar varje nodhash,
metadata, grenval och nyckelintervall samt avvisar ofullständiga och extra vägar.
Ett saknat eller trasigt lagrat barn är ett fel, aldrig ett frånvarobevis.

Verifierad frånvaro förutsätter att den betrodda roten härrör från ett giltigt
ordnat träd. Ett självvalt hashvärde från en motpart är inte en betrodd rot.
Det överensstämmer med kravet på ordnade nycklar och positionsbindning i
[ICS-23-specifikationen](https://github.com/cosmos/ibc/blob/main/spec/core/ics-023-vector-commitments/README.md)
och dess [referensimplementations begränsningar](https://github.com/cosmos/ics23).
GG-koden använder sitt eget uttryckliga nodformat och påstår inte ICS-23-kompatibilitet.

Den rena överföringsfunktionen kräver föregående autentisering av
kontosignaturen. Den ersätter inte den kontrollen. En lyckad överföring
debiterar, ökar avsändarens nonce, krediterar och bevarar totalsumman i en
privat ny rot. Fel eller avbrott lämnar den tidigare roten intakt. En ny
mottagare skapas först genom en sådan finansierad överföring. Nollsaldo med
förbrukad nonce tas inte automatiskt bort.

Ett särskilt test hittade en felklassning i den första versionen av denna nya
kärna: fullt kontoantal gav ett lagringsfel när en betalning ville skapa en ny
mottagare. Det ska vara ett deterministiskt utfall, så att övriga överföringar
mellan befintliga konton kan fortsätta. Kärnan ger därför
`REJECTED_ACCOUNT_LIMIT` utan ändrat saldo eller nonce. Det ursprungliga röda
testet och motsvarande källkod behålls i den privata granskningshistoriken.
Detta nya utfall är ännu inte infört i något befintligt nätprotokoll.

Lagringsgränssnittet lämnar endast nya nåbara noder till en anropsägd
skrivtransaktion, med uttrycklig nodbudget och ett absolut tak på 262 144 nya
noder per sådant anrop. En fryst rot behåller inga pekare till den privata
nodgrafen utan använder en läsare som verifieras vid varje uppslag.
Detta är ingen färdig beständig kontodatabas: adaptern måste atomiskt spara
noder och auktoritativt huvud, ha begränsad cache och kontrollerad livstid,
samt återspela och verifiera original vid återhämtning. Ingen sådan
lagrings-/konsensusintegration påstås av callback-gränssnittet.

## Verifieringsomfång

De lokala Go-proven omfattar de fyra AVL-rotationsfallen, bevarade gamla rötter,
förfalskade konto- och frånvarobevis, fel kontext/rot, trasig eller saknad
lagring, skrivfel, kontogräns, nonce- och beloppsgränser samt avbrott efter
privat debitering före mottagarens uppdatering. Ett annat prov jämför ett
förlopp av överföringar mot en separat vanlig kontomapp.

Det ändliga större provet finansierar 5 000 olika mottagare och kontrollerar
5 001 nåbara kontonoder, oförändrad totalsumma, gamla rötter och bevis från
den frysta läsvägen. Det är ett prov av den rena kontokärnan: det producerar
inga kontosignaturer, SDK-certifikat, nättrafik eller kapacitetssiffror för
ett live-nät. Go-proven på Windows och Linux redovisas separat; underfall
och samma test på olika system överlappar.

## Primärkällor och slutsatser

[Ethereums kontobeskrivning](https://ethereum.org/developers/docs/accounts/)
skiljer konto, nonce, nyckel och plånboksgränssnitt. Det stöder kravet att
Desktop visar verifierat kontotillstånd och inte blir den ekonomiska auktoriteten.
[EIP-161](https://eips.ethereum.org/EIPS/eip-161) visar att kontolivscykel och
städning behöver uttryckliga konsensusregler; lokal borttagning av ett konto
får inte återställa dess replay-skydd. Detta är härledda designkrav för GG,
inte ett påstående att Ethereumregler har implementerats.

[Bitcoins ursprungliga artikel, avsnitt 6](https://bitcoin.org/bitcoin.pdf)
beskriver utgivning och avgifter som incitament för sitt säkerhetsarbete.
En pool eller en ny peer skapar ingen sådan säkerhetsbudget automatiskt i GG.
Laboratoriets fasta allokering är fortsatt skild från offentlig emission,
avgifter, mining och poolutbetalningar.

## Kvar innan generella konton är klara

Kärnsteget ensamt ger ingen körbar allmän kontofunktion. En uttryckligt
versionerad genesis och kontoregel, beständig adapter, full originalbaserad
replay och arkivåterhämtning behandlas i native-integrationen. Därefter
behövs certifikatbundna native/WASM-kontobevis, skyddad kontosignering,
kontohantering i CLI och samma verifierade vy i Desktop. Dessa delar får
inte ersättas av lokala testvärden eller självdeklarerade verifieringsflaggor.

Publik kontoskapandekostnad, lagringstillväxt, antagnings-/Sybilmodell,
avgifter, emission, mining och poolbokföring behöver sammanhängande regler
och adversariell acceptans. Kapacitetsmålet, oberoende säkerhetsgranskning
och fysisk Windows/Linux/Termux-acceptans återstår. Varken den här kärnan
eller föregående lagringsprov utgör godkännande för publicering eller huvudnät.
