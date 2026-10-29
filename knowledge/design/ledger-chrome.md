# Obsidian / Ledger: riktiga kantöppningar

## Avsikt

Behåll GG AI DESKTOPs TUI-uttryck och befintliga arbetsytor. Etiketter, flikar
och fönsterknappar ska ligga i faktiska öppningar i ramen, utan färgade
rektanglar som täcker en redan ritad kant. Bilder och diagram behålls.

## Fynd och beslut

Den tidigare GgFrame ritade en hel kant och fyra ogenomskinliga etikettplattor.
Workspace, kompositorn, TMOG, Utilities och popupfönster hade samma mönster.

LedgerBorder skiljer nu panelens inre yta från kantgeometrin. LedgerGeometry
klipper och förenar öppningarnas intervall. LedgerRule ritar enbart återstående
horisontella linjesegment med enkla Qt Quick-rektanglar. Sidorna är raka
rektanglar och de små hörnen är beständig vektorgeometri. Etiketternas
behållare är transparenta Items. Öppningarna följer verklig text-, flik- och
kontrollgeometri när fönstret eller texten ändras.

Små symboler i LedgerGlyph, ResearchAction, medieknappar och layoutens
storlekshandtag använder beständig Shape-geometri i stället för Canvas-bilder.
Hover och fokus ändras direkt; dessa kontroller saknar dekorativa övergångar.
Vanliga enkla knapp- och fältbakgrunder är faktiska kontrolltillstånd och
behåller sin funktion. Inga nya renderingslager eller kontinuerliga ritslingor
har införts. Upptagenindikatorn behåller kopplingen till verkligt arbete.

## Verifiering och gränser

Native Qt-prover kontrollerar mönstrad bakgrund genom öppningarna, dynamiska
etiketter, smala paneler, skalning 100/125/150/200 procent, programfönstrets
kontroller och Direct3D11 samt mjukvarurendering. Testdata är isolerade från
användarens konton. Stillastående ramprov får inte skapa nya frameSwapped.

Detta är en ändring av det befintliga Qt-gränssnittets ritning, ingen färdig
terminalport. Provets tomgångskontroll är inte en jämförande CPU/GPU-mätning;
ingen procentuell prestandavinst påstås. Velo-referensen inspirerar strukturen,
men dess terminalceller och Qt:s scen är olika renderingsmodeller.

Vid minsta programbredd delas den översta kontrollraden på två rader så att
CHAT/WORKSPACE och walletstatus inte överlappar programåtgärderna.

De statiska formerna begär GeometryRenderer. Vid native Direct3D11-kontrollen
saknades först symbolerna med CurveRenderer trots godkänt mjukvaruprov.
Pixelprov för samtliga tio symboler och ett rundat hörn fångar den skillnaden.
Qt:s [Shape-dokumentation](https://doc.qt.io/qt-6/qml-qtquick-shapes-shape.html)
beskriver geometrirendering och dess kostnad när geometri ändras; formerna här
animeras inte och kräver ingen separat bildyta.
