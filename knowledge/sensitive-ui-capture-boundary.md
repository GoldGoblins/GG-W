# Lokal hemlig UI och GG:s observationsvägar

`backend/sensitive_ui_guard.py` håller högst 64 lokala ägare med ett kort
återinträdbart lås. `enter(owner)` publicerar spärren innan befintlig GG-fångst
stoppas. `leave(owner)` tar bort ägaren utan att återstarta någon fångst.

Windows delar en 4 KiB RAM-mappning inom den aktuella inloggningssessionen.
Namnet härleds från processens verkliga användar-SID, inte miljövariabler,
walletkatalog, profil eller `STATE_ROOT`. Därför gäller spärren även mellan
desktop och CLI med separata walletprofiler. Linux använder verifierad
tmpfs under en fast katalog för det verkliga användar-id:t. Termux saknar
vanligen dessa tmpfs-kataloger och använder då appens privata `usr/tmp`,
härledd från den verkliga Python-installationen och kontrollerad mot ägare
och symboliska länkar. Den reservvägen är inte RAM-baserad. Delad metadata
består av process-id:n och en generation; inga fraser, lösenord, kontoadresser
eller bilder skrivs dit. Döda ägare rensas vid nästa kontroll.

`capture_token()` vägrar när spärren är aktiv. En ny ägare ökar generationen.
`require_capture_allowed(token)` vägrar även om den hemliga vyn både öppnats och
stängts under en redan påbörjad observation. Saknad eller trasig spärrkanal
ger avvisad fångst.

GG:s Windows-/Pillow-fångst kontrollerar före och efter inhämtning, före
bildlagring/progress och före leverans. FrameRing, bilddelar, export och
Linux portal-/KWin-vägar kontrollerar samma spärr. Blockerade portalprov
hämtas inte från sinken och köar stopp; KWin-avkodning stoppas och lämnar inte
ut ett prov från en tidigare generation. Ny fångst efteråt kräver en ny
uttrycklig observation.

`gg-desk` avvisar SNAPSHOT/FIND innan ett kommando skrivs och kontrollerar
generationen före leverans. Resultatkonstruktion redigerar dessutom bort
bildreferens, text och UI-namn när spärren är aktiv. Hostens egna insamlings-
och sparvägar måste använda samma för-/efterkontroll. Hemliga textfält har
`sensitiveInput` och ordgrider `privateSensitive`, så UI-trädet kan undanta
dem även oberoende av pixelspärren.

Återvisningen accepterar bara den synliga vyns egen väntande förfrågan och
valt konto. På stängning rensas UI-ord och förfrågnings-id **före** anropet som
släpper backendens spärr. Ett försenat eller felmatchat svar visas aldrig.
Ingen tidtagare stänger ordvyn åt användaren. Lösenord och fullständiga ord
går aldrig genom dess publika actionsignaler.

Detta avgränsar **GG:s egna** fångst- och inspektionsvägar. Det är ingen garanti
mot andra program, externa fotograferingar, operativsystemets bildpipeline
eller minnesforensik. Att rensa Qt-/JavaScript-referenser innebär inte ett
påstående att alla tidigare minneskopior är fysiskt överskrivna.

Tester använder offentliga BIP39-vektorer och syntetiska bildmarkörer. De
kontrollerar korsprocesspärr med skilda profiler på Windows, generationsbyte,
uteblivna grab/progress/buffert/exportresultat, redigerad UI-text, portal/KWin-
stopp samt återvisningens matchning, stängning och layout. Ingen verklig fras
eller verklig användarskärm fångas i dessa tester. Windows skärminhämtningens
två verkliga skärmtester ingår inte i den syntetiska kompatibilitetskörningen.
