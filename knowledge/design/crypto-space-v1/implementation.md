# Från vald konceptbild till fungerande vy

## Avsikt och beslut

Användaren valde samtliga tre bilder och begärde samma upplägg, inklusive
sidopaneler, med befintliga funktioner och verklig information. Bildernas
struktur är därför målbilden för implementationen; en allmänt TUI-inspirerad
layout räcker inte. Native QML ligger fortsatt direkt i flikens arbetsyta.

Användarens förtydligade koppling mellan bilder och navigering:

- MP-bilden är marknadsplatsens ordinarie katalogvy.
- Bilden med totalvärde och tillgångslista är cryptoöversikten.
- Bilden med konton till vänster, tokenåtgärd i mitten och skydd/nätverk
  till höger är arbetsytan för ett eget innehav. Ett klick på en publik
  position öppnar denna vy direkt med exakt konto och tillgång valda.

Tokenarbetsytan samlar Ta emot, Skicka/uttag och Mellan konton i samma
struktur. Ett internt mottagarkonto är en annan ansluten adress på samma
kedja. Överföringen använder den vanliga nätverksadaptern med avgifter och
granskning. Att en mottagaradress bevakas i appen är inget ägarbevis.
Ett publikt bevakningskonto kan ta emot; lokal sändning kräver tillgänglig
signerare, backup och en stödd adapter. GG-labbets separata flöde bevaras.

## Visuell koppling

| Del | Referens och innehåll |
| --- | --- |
| Gemensam rad | ÖVERSIKT, MARKNAD, MARKETPLACE, BOTAR, NÄTVERK; diskret guldunderstrykning. Verktyg och global händelselista är nåbara. |
| Kontoöversikt | Stor exakt total, kompakt kontourval/ta emot/uppdatera och verkliga antal. Sökning och nätverksfilter ovanför tillgångstabellen. |
| Tillgångar | Identitetsbunden ikon eller ärligt bokstavsmärke; saldo, pris, värde och riktig historik. Ingen konvertering av exakta walletbelopp genom flyttal. |
| Översiktens sidopanel | Cirka 28 procent av bredden: konton med värde, källstatus med senaste avläsning, registrerade globala händelser. |
| Wallet | Vänster grupperade konton/tillgångar; mitten mottagaradress, mint, verkligt saldo och matchande överföringsunderlag; höger skydd, nätverk och händelser. |
| MP | Tunn sök-/källrad, hierarkiska kategorier med faktiska antal, visuell katalog och valt föremålspass. Bunden lokal händelselogg under katalogdelen. |
| Föremålspass | Bild, innehåll, ursprung och kvitto som utfällbara uppgifter; fördjupning och befintliga åtgärder förblir åtkomliga. |

På breda ytor matchas konceptets proportioner och läsbara textstorlek. Smala
ytor använder samma visuella ordning med scrollning och åtkomliga paneler.
Walletens meny och knappen Skydd öppnar samma faktapanel i en kompakt vy när
sidokolumnen inte ryms. MP:s kategorier kan öppnas separat och ett valt
objekt har alltid en väg till hela passet.
En separat appbakgrund eller inramad appkopia får inte läggas i arbetsytan.

Översiktens total, kontroller, ikoner och radhöjder följer konceptets
proportioner när arbetsytan är smalare än referensbildens 1586 px. Vid cirka
970 px total arbetsyta är totaltexten cirka 30 px, knapparna 27 px och
tillgångsraderna 41 px. Den fulla tabellen med saldo, pris, värde och små
grafer visas från 600 px faktisk huvudkolumn, även med sidopanelen öppen.
En smalare huvudkolumn använder samma kompakta värde-/saldoordning med
åtkomliga kontroller. Exakta belopp, saknade priser och verklig historik
behåller sina databetydelser.

Högerspalten är synlig som standard från 820 px faktisk cryptoarbetsyta.
Knappen Sidopanel i den gemensamma navigeringen visar eller döljer den utan
att ändra valt konto, underlag eller godkännande. På smalare ytor öppnar samma
knapp en läsbar faktapanel utan att pressa ihop tillgångslistan. Konton,
skydd, källstatus/nätverk och händelser kan fällas ihop var för sig. Aktuella
jobb och väntande godkännanden visas med sin verkliga status; inga
framstegsprocent eller nätverkssvarstider antas. En saknad eller avvikande
lokal nyckel får aldrig ge intryck av att lokal signering är tillgänglig.

MP:s föremålspass ryms från 860 px faktisk katalogbredd. Ett tomt lokalt
bibliotek visar samma struktur med vägledning för bild, innehåll, ursprung
och kvitto samt en registreringsknapp. Objektbilder kommer från registrerade
objekt. Tomläget skapar inga exempelobjekt och intygar inget ursprung.

MP startar i Lokalt och behåller samma sök-/källrad, kategorispalt,
trekolumnskatalog, pass och synliga händelselogg även för Publika samlingar.
Källknapparnas läge ändras inte när källan byts. Ett valt publikt objekt
uppdaterar samlingspasset; det ersätter aldrig hela katalogen med en stor
detaljbild. På smal arbetsyta öppnas pass och kategorier i paneler.

MARKETPLACE nås i CRYPTO:s övre meny. Den tidigare separata MP-fliken i
arbetsytans nedre flikrad och dess värdval i inställningarna är borttagna.
Äldre Marketplace-genvägar och objektvägar leder till samma inbäddade vy
under CRYPTO. Namnet MARKETPLACE skrivs ut helt även på smal arbetsyta;
menyn kan rullas horisontellt när alla val inte ryms samtidigt.

Den publika katalogens grundsvar saknar ofta bild. Därför återanvänds
identitetskontrollerade sparade detaljer och en begränsad bildläsning kan
behandla högst sex referenser i taget. En batch ändrar inte vald samling.
Synlig status visar verkligt antal behandlade referenser, tillgängliga bilder
och fel. Stoppa, sidbyte, källbyte och ändrad katalog spärrar sena resultat.
Katalogen går att använda under bildläsningen. Samlingsreferenser är inte
verifierade varor, säljorder eller ägarbevis; de visas med rätt typ av pass.

## Fakta, antaganden och datagränser

Konceptens konton, objekt och belopp är fiktiva. Samma visuella struktur får
innehålla färre rader när användaren har mindre material. Ingen exempelstol,
låtsaswallet eller syntetisk prisgraf registreras som riktigt innehåll.

Walletmodellen innehåller saldokällornas avläsningstid och felstatus, men
ingen universell uppmätt svarstid eller onlineanslutning. Motsvarande plats
visar därför avläsning/okänd mätning. De globala händelserna saknar konto-id;
de får inte presenteras som ett valt kontos kompletta transaktionshistorik.
Överföringshistoriken kan däremot filtreras på det sparade konto-id:t.

Inbyggda logomarkeringar kopplas till kanonisk tillgångsidentitet. Symboltext
ensam väljer aldrig en annan tokens logotyp. Utan konfigurerad tokenbild visas
ett neutralt bokstavsmärke. En ikon är aldrig ett äkthets- eller riskbevis.

Förhandsgranskningen använder endast ett faktiskt förberett underlag för
valt konto och vald tillgång. Skapande/backup/signering behåller sina befintliga
godkännanden. En tom förhandsgranskning visar hur ett riktigt underlag skapas.
Samtycket binds till både granskningsunderlag och överförings-id och nollställs
vid konto-, tillgångs-, åtgärds-, mottagar- eller beloppsbyte. Ett pågående
förberedelsejobb binds till sitt ursprungliga val och får inte öppna en annan
positions granskning när svaret kommer. En köad godkännandeåtgärd visar sitt
ursprungliga underlag och låser inmatningen tills chatten har avgjort den.
Nätverksnamnet visas läsbart tillsammans med
den tekniska kedjeidentiteten.

En deklarerad objektbild som inte kan läsas får en synlig felplatshållare.
Saknade delpass och tidigare liv visas som referenser utan en fungerande
öppningsknapp; en sådan knapp visas först när referensen kan hittas i katalogen.

## Visuell och funktionell kontroll

Jämför de frysta konceptbilderna med faktiska Qt-renderingar vid ungefär
1586 × 992 och vid smal arbetsyta. Kontrollera panelproportioner, läsbarhet,
rader, linjer, ikoner, scrollning och saknade uppgifter. Prova kontoval,
filter, utfällbara träd, öppning av objekt, mottagning och granskning med
kontrollerade fixturer. Geometriprov mäter den faktiska WorkspaceSurface;
funktioner verifieras med de befintliga tjänsterna. Inga skärmbilder av
verkliga användarsaldon tas med i källpaketet.
