# Wallet – kompakt följevy

## Ursprunglig avsikt

Walletpopupen ska bli lika genomtänkt som CRYPTO och MARKETPLACE. Mindre
knappar, tillgångarna högre upp och befintliga funktioner nära till hands.
Användarens tillägg: en liten prislinje mellan varje tokens namn och belopp.

## Koncept och beslut

`concept.png` är skapad med inbyggda imagegen. Exakta genereringsinstruktionen
finns i `prompt.txt`. Bildens siffror, konton och tokenbilder är illustrativa;
inget därifrån registreras som användarens innehav eller verifierad logotyp.

Popupens normala bredd 328px behålls. Kontoöversikten använder ett eget
kompakt läge: 26px kontroller, 28px ikoner, 52px tillgångsrader och fast
nederkant med Tillgångar, Aktivitet och Verktyg. Första tillgångsraden börjar
cirka 208px från popupens överkant. Sök och nätverksfilter delar en rad; totalsumma,
kontoval, Ta emot och Skicka ligger ovanför. CRYPTOs desktopproportioner
behålls. Detaljer och åtgärder använder samma befintliga walletmodell.

Kontoverktyg, publik bevakning, skapa/återställ/backup, nollsaldo, källstatus,
labb, överföringshistorik och marknad finns i menyerna. Verktyg och marknad
har en direktknapp tillbaka till tillgångarna. Expandera öppnar uttryckligen
WALLET i CRYPTO och väljer arbetsytan även i smalt programfönster.

## Fakta och visuell kontroll

Sparklines använder enbart tillgångens befintliga prisobservationer. Linjen
får plats mellan namnkolumnen och beloppens verkliga textbredd. Saknad historik
eller otillräckligt utrymme ger ingen ritad linje; ett långt saldo kortas inte
för att göra plats. Proven använder enbart tydligt syntetiska konton och
historik. Produktionsvyn får inga exempelkurvor eller exempelpriser.

Bildjämförelsen och native Qt-proven täcker 328/360/430px bredd och 520/600px
höjd, exakt långt saldo, filter, menyer, Ta emot, Skicka, återgång, tomt konto,
läsfel och väntande godkännande. Bevakningskonton får inte förbereda/sända en
överföring. Ingen verklig nyckel skapas och ingen transaktion sänds.

En kvarhängande symbol utanför popupen fångades vid mjukvarurendering när
åtgärdsvyn stängdes. Glypherna skapas nu bara när de ligger i sin scrollvy
och är synliga. Ett pixelprov utanför popupen kontrollerar att de försvinner.
Vektorgeometrin behålls; ingen täckplatta eller kontinuerlig omritning läggs
till. Direct3D11 och mjukvarurendering verifieras separat.
