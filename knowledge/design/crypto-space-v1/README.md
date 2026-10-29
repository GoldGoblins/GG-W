# GG Crypto Space: visuell riktning

Användaren vill ha Velo-liknande informationshierarki i Obsidian/Ledger,
med riktiga kontroller i varje fliks faktiska arbetsyta. En extra inramad
dashboard ovanpå arbetsytan ska inte användas. Konceptbilderna togs fram
innan nästa layoutändring och granskades visuellt mot Velo-referensen.
Användaren har därefter valt just dessa bilder som bindande visuell mall:
proportioner, sidopaneler, tabeller, typografi och informationshierarki ska
återskapas i riktiga kontroller med programmets verkliga data och funktioner.
Se [kopplingen mellan koncept och implementation](implementation.md).

- [Kontoöversikt](overview.png)
- [Marketplace](marketplace.png)
- [Wallet / mottagning och granskning](wallet.png)

## Gemensam struktur

En enda värdarbetsyta äger bakgrund, ytterram och innehållets storlek.
Sektionsnavigationen ligger i en tunn horisontell rad. Innehållet förankras
i den riktiga flikens innehållsyta; höjden beräknas inte från en annan
förälders höjd med en fast pixelavräkning. Ingen ny app-sidomeny eller
inramad appkopia läggs innanför arbetsytan.

Primärt innehåll använder huvuddelen av bredden. En sekundär faktakolumn
kan visa riktiga konton, källstatus och händelser när utrymme finns. På smala
ytor prioriteras listan, formuläret eller grafen. Kontroller och viktiga
felstatusar måste förbli nåbara med scrollning och tangentbord.

Bakgrund: svart/mörkgrå. Text: vit/ljusgrå. Linjer: diskret grå.
Guld markerar fokus och sektion. Grön/röd används för faktisk status eller
prisriktning, alltid tillsammans med text. Källa, konto, nätverk och mint
är tydligt skilda uppgifter.

## Innehåll

Översikt: ett totalvärde över innehaven, kompakt konto-/nätverksurval,
riktiga saldon/priser och små grafer där data finns. Konto- och källstatus
ska gå att förstå utan dekorativa prestationsmätare.

MP: sökning och källa först, sedan visuellt bläddrande med föremålspass,
innehåll, ursprung och kvitto. Lokala varor/tjänster och publika
NFT-samlingsreferenser har olika betydelse och får inte likställas.

Wallet: tydligt valt konto och nätverk, mottagaradress, mint/kontrakt,
saldokontroll samt granskning av verkligt förberedd överföring. Bevakning,
lokal signerare, krypterad backup och nätverksbekräftelse är separata
tillstånd. Tidigare osäkra överföringar ska gå att återöppna och kontrollera.

## Sanning före bild

Bilderna är märkta koncept med fiktiva data. Belopp, grafer, svarstider,
namn och kontostatus i bilderna är inga produktionsvärden eller bevis.
Implementationen använder faktisk state och exakta beräkningar. Ett
okänt värde visas som okänt. Saknad prishistorik fylls inte ut, och
ingen källkontakt/signering/överföring visas som klar utan motsvarande
verifierat utfall. Genererade rasterbilder är referenser, inte ett UI
som klistras över den riktiga arbetsytan.

## Visuell verifiering

Jämför koncept, faktisk Qt-rendering och den riktiga appen efter ändringar.
Mät föräldrar/kanter och testa smal/bred storlek, menyer, val, scrollning,
status och återupptagning. En skärmbild bevisar layout; protokoll- och
behörighetskontroller verifieras separat med exekverbara tester.

Referens: [Velo](https://github.com/bjarneo/velo), dess arkitektur och
`assets/screenshot-download.png`. Velo-licensmeddelandet finns i
`knowledge/references/velo-LICENSE.txt`.
