# GG Terminal-palett

## Avsikt

GG ska använda samma sammanhängande färgfamilj i hela skrivbordet: mörkgrå
ytor, ljusgrå/vit text och flera tydliga accentfärger. Walletens användarvalda
tokenfärg och dess andel av totalvärdet använder samma färg.

## Källor och faktiska fynd

Den installerade Codex CLI-versionen är 0.165.0 och distribueras lokalt som
native-binär, utan temakällkod. Codex har valbara syntax-/diff-teman enligt
[OpenAI:s CLI-dokumentation](https://learn.chatgpt.com/docs/cli-customization).
Det finns därför ingen verifierad enda fast hexpalett som kan kallas alla
Codex-installationers färgpalett.

I GG:s terminal bestäms namngivna ANSI-färger av `backend/mini_vt.py`:
16 ANSI-färger, en 216-färgers kub och 24 gråskalor. Terminalens standardtext
är `#d8dee9` och bakgrund `#161616`. Ingen användares inloggning eller
sessionsinnehåll behövs för att fastställa dessa värden.

## Beslut

`config/gg-palette.json` är den gemensamma palettens data. Alla 64 valbara
färger kommer från exakta index i den befintliga xterm256-tabellen. De första
16 väljs för läsbara, dämpade accenter. De första32 indexen behålls. Den fulla
64-paletten innehåller dessutom starkt mättade färger, flera tydliga röda,
svart, vitt samt mörka och ljusa gråtoner. Tidigare hexval från gamla index32–63
behålls genom `legacy_colors`; de byter inte färg eller tappas ur sparade wallets.

`qml/components/GGPalette.js` är den statiska QML-spegeln. Den kräver ingen
filinläsning per bildruta, pollning eller animeringsklocka. Ett verkligt QML-test
kontrollerar att JSON, JavaScript, terminalindex och `LedgerTheme.js` stämmer.

`GGTheme.qml` är skrivbordets reaktiva singleton. Inställningar → Utseende
erbjuder tio separata funktionsroller med samma64 enkla färgval: markering,
information, klart, väntar, fel, blå, cyan, AI/lila, resurser/orange och rosa.
En ändrad roll målar om bundna kontroller direkt och sparas i `paletteRoles`
i användarens befintliga inställningsfil. Rollistan visar varje rolls aktuella
färg i både öppet och stängt läge. Nya rollval begränsas till de64
kanoniska färgerna; tidigare explicit sparade hexval behålls. Okända roller,
ogiltiga färger och godtyckliga strängar
avvisas. Befintliga uttryckliga accent-, ramgråton- och radieval behålls.
Återställ vald roll eller hela färgkartan separat. Tokenfärger är fortfarande
egna tillgångsval, med 16/32/64-paletten, och ändras inte av ett rollval.

Singletonen har inga timer-/diskanrop i ritvägen. En QML-motor delar ett
levande rollobjekt mellan sina vyer; nästa programstart läser sparade roller.

Rollerna är blå för information/aktivt val, cyan för transport, lila för
beräkning/verifiering, grön för godkänt, röd för fel, gul för uppmärksamhet och
orange/rosa som ytterligare serie-/kategorifärger. Färg kompletterar alltid
text, statusnamn och andra signaler.

Delade standardkontroller och arbetsytor använder dessa roller. Befintliga
uttryckliga färgval från användaren och färgparametrar från en anropare fortsätter
gälla. Originalfärger i externa tokenlogotyper och bildinnehåll behålls.

Tokenidentitetens standardfärg beräknas med FNV-1a över UTF-16-kodenheter och de
första tolv färgerna. Identiteten ska omfatta nätverk och tillgångens verkliga
referens; ett ticker-namn är inte tillräckligt. Ett sparat explicit färgval går
före denna standard. Funktionen väljer en färg, inte en ägande-/prisuppgift.

## Verifiering och gränser

`tests/test_gg_palette.py` kontrollerar exakta index, stabila16/32-prefix,
JS/JSON-överensstämmelse, standardidentiteter inklusive Unicode, avvisade
ogiltiga färger, minst 4,5:1 kontrast för text-/semantiska huvudroller på de
mörka ytorna samt att verkliga QML-kontroller bevarar uttryckliga färgval.

`tests/test_runtime_theme.py` klickar på den riktiga inställningsytans färgrutor,
följer signalerna genom SettingsSurface/SettingsPopup till en isolerad
inställningskontroll, verifierar ommålning av en annan vy utan återladdning,
ny läsning i en separat QML-motor, oberoende roller, tangentbord, återställning
och färgprover i den riktiga rollistan. Svart, vitt och mättat rött provas också.
Sparning sker bara i en tillfällig testfil; ingen användarinställning ändras.

Paletten är ett GG-val ur samma terminalfärgrymd som dess Codex-vy använder.
Den gör inga påståenden om att kopiera en ej observerad användares valda
Codex-syntax-/terminaltema.
