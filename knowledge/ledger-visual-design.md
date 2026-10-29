# Obsidian / Ledger – marknad, marketplace och KNOWLEDGE

## Avsikt

Användaren vill ha grått, vitt, ljusgrått och svart som gränssnittets grund.
Färg får hjälpa till med status, val och innehåll, men grundytorna ska vara
neutrala. CRYPTO behöver en liten historikkurva vid tillgångarna. Marketplace
ska gå att utforska som KNOWLEDGE: ett begripligt objekt i centrum med vägar
vidare till innehåll, ursprung, tidigare liv och transaktionskvitto.

## Genomförande

`qml/components/LedgerTheme.js` samlar grundpaletten. Marknaden, wallet,
OMNI, MP, KNOWLEDGE och kroppsvyn använder neutrala bakgrunder, textfärger,
kontroller och kanter. Objektbilder behåller sina färger. Guld används för
orientering, grönt/rött för riktning/status. Kroppsvyn behåller sina uttryckliga
färger för manuellt vald övningsallvarlighet; ingen medicinsk logik ändras.

Marknadens listanrop begär CoinGeckos sjudagarshistorik tillsammans med de
100 marknadsposterna. Inga ytterligare anrop görs per rad. Varje serie valideras
och begränsas till 128 punkter med bevarade ändpunkter och lokala extremvärden.
Saknad eller ogiltig serie visas som saknad, inte som en påhittad kurva.
Små Canvas-kurvor ritas i de skapade listdelegaterna. Oförändrade statussvar
behöver inte tolkas och bygga om listan igen.

Kurvans riktning gäller dess egna ändpunkter, medan procenttalet i priskolumnen
fortfarande gäller 24 timmar. De kan därför ha olika färger. DEX-poster kan visa
verkliga lokalt sparade observationer; de märks **Observerat**, eftersom de inte
utgör en komplett veckohistorik. CoinGeckos veckokurva är historisk och
uppdateras av leverantören med en annan takt än priset.
[Markets API](https://docs.coingecko.com/reference/coins-markets),
[uppdatering av sparkline](https://support.coingecko.com/articles/4100851507-how-often-does-the-price-data-update-for-the-sparkline-in-coins-markets-update).

MP:s två synliga huvudingångar är **Utforska** och **Registrera**. Material,
tidigare liv, aktivitet, wallet/nätverk och NFT-inspektion nås genom **Verktyg**.
Filter visas på begäran; knappen visar hur många filter som används. Ett
återställningsval rensar filtren. Den tidigare raden med alla kategorier är
flyttad till filterpanelen.

I bred vy visar MP ett virtuellt objektbibliotek bredvid ett större objektpass.
Passet använder KNOWLEDGE:s faktiska rasterkomponent för zoom, panorering och
återställning. Fyra tydliga val öppnar innehåll, ursprung, tidigare liv och
kvitto i inspektören. Valen är navigering till registrerade uppgifter; deras
placering på bilden är inte mätdata eller vetenskapligt belagda delpositioner.
Det finns inga nya genererade bilder eller påhittade egenskaper.

Rutnätet är ett separat visningsval med större bilder och färre textrader.
Smala fönster använder rutnät → objektbild → detaljer under bilden.
Tekniska identiteter visas på begäran. Övriga registrerings-, kvitto-,
NFT- och materialfunktioner finns kvar. Uppdelningen mellan sökning, objekt
och verktyg följer också etablerade marknadsflöden, utan att ansluta till
eller kopiera externa marknadsplatsers transaktionssystem.
[OpenSea sökning och upptäckt](https://docs.opensea.io/docs/search-and-discovery).

## Verifiering och gränser

Det publika provet den 27 oktober 2026 returnerade 100 coinposter med 100
giltiga veckokurvor, högst 128 punkter per kurva. Vyn renderades med dessa
publika data. Övriga UI-prov använder tydligt avgränsade testdata och samma
cellbild som programmets befintliga exempel, inte verkliga köp eller innehav.

Qt-proven kontrollerar både smala och breda vyer, grafdata, navigering till
innehåll, verktygsmenyn med Escape, separata NFT- och betalningsnätverk och
virtuell rendering av 2 000 katalogobjekt. KNOWLEDGE:s källor, citat, zoom,
panorering och kroppsvy testas separat. Inga kontrakt för signering, köp eller
produktion ändras av utseendearbetet.

Använd skillnaden mellan verklig publikt hämtad marknadsdata, registrerad
objektinformation och illustrativa exempel när nya bilder eller vyer läggs till.
Se även [sessionsgenomgången](crypto-session-review.md) för nätverksfunktionernas
befintliga avgränsningar. Ändringarna laddas vid nästa vanliga appstart.
