# DAGoblin: validatorer i vanlig CLI och Desktop

Detta fortsätter den lokala granskningen av signerad LAN-genesis och beständiga
validatorprofiler. Det är fortfarande ett privat LAN-experiment. Hela nätet,
publik tokenomics och kapacitetsmålet är inte färdiga eller godkända.

## Ursprunglig avsikt

CLI äger nodens faktiska arbete och kontotillstånd. Desktop ska visa samma
informationskälla med rätt skapare och verifieringsnivå. En långsam mobil ska
kunna delta utan att bli ett obligatoriskt konsensussteg för datorerna.

## Fakta och ändringar

Vanliga `TerminalService`/`LanDagRuntime` har nu explicita kommandon:

* `lan.validator_create profile=Namn` skapar en skyddad profil före genesis.
* `lan.validator_open profile=Namn` öppnar en befintlig profil.
* `lan.validator_start profile=Namn` startar dess ägda SDK-process först när
  den signerade kommittén är installerad och profilen tillhör kommittén.
* `lan.validator_stop profile=Namn` stoppar den processen.
* `lan.validator_invite profile=Namn` lämnar endast den publika inbjudan.
* `lan.session_create enable_dag_transactions=true enable_consensus=true`
  binder exakt fyra annonserade validatoridentiteter till LAN-genesis.

CLI-flaggorna `--validator-create Namn` och `--validator-profile Namn` kan
upprepas, högst fyra lokala profiler. De kräver en uttrycklig `--foreground`
LAN-start/anslutning/återupptagning. Start sker en gång när den signerade
kommittén finns; ingen omstart eller upprepad sändning sker automatiskt.
Vanlig `lan.resume` utan dessa flaggor startar inga validatorprocesser.
Linux/Termux låser upp profiler via den befintliga privata terminalfrågan.
Lösenord skickas inte som kommandoargument, JSON eller observationer.

Publika validatorinbjudningar följer befintlig LAN-parning i signerad invite
v5. Koordinatorn accepterar bara tillägg i samma ordning; ägare, endpoint,
producentnycklar, nonce och deltagarpolicy förblir bundna. Inbjudningarna
sparas i nodens signerade profil före annonsering. Även en återstart före
genesis bevarar ordningen, oavsett i vilken ordning profiler senare öppnas.
Tidigare profiler utan detta val fungerar fortsatt utan automatisk migrering
eller ny identitet. Inbjudningar, bootstrap och profildeskriptorer är begränsade
till ändliga storlekar; validering är fortsatt strikt.

Windows Desktop kan uttryckligen välja beständig LAN-profil, återuppta den
och skapa/öppna/starta/stoppa dess validatorprofiler. Windows-kontots DPAPI
skyddar privata nycklar. POSIX Desktop hämtar observationer från den CLI som
äger profilen; det skapas ingen lösenordsruta eller parallell nyckelägare.
Koordinatorns checkbox väljer uttryckligen om fyra offentliga identiteter
ska bindas vid sessionsskapandet. Standardläget binder ingen kommitté.

SDK-verifiering sker i en avbrytbar observationsarbetare för uttryckligen
startade validatorer. Certifikatet sparas före publicering. Status/GUI läser
ett sammanhängande publicerat par av tillstånd och verifieringsresultat utan
att vänta på RPC, verifieringsprocess, diskskrivning eller arbetslås.
LAN-stopp avslutar även dess ägda validatorprocesser.

Desktop visar signerade validatornamn, LAN-ägare, lokal ägare, observerad roll,
kommitténs fyra nycklar/kvorum tre, certifikathöjd och certifierat DAG-antal.
En fjärrvalidator vars process inte observerats lokalt visas som `UNOBSERVED`.
Antalet nycklar innebär inte fyra oberoende operatörer. En certifierad
DAG-rot gör inte automatiskt alla ritade block finaliserade; individuellt
medlemsbevis och canonical visning återstår.

## Verifiering

Riktade tester omfattar verklig TCP-parning och distribution, strikta argument,
förändrad identitet/endpoint, omordning/borttagning av annonser, misslyckad
beständig skrivning, återstart före/efter genesis, privata upplåsningskontexter,
CLI-flaggornas startsekvens och status under upptaget validatorlås.
Riktig Qt/QML körs offscreen och prövar certifikatvisning, ägarnamn,
uttryckligt genesisval och skrivskydd för en observerad CLI-nod.

Ett separat, temporärt prov använder de vanliga CLI-servicekommandona för
tre LAN-ägare och fyra riktiga SDK-processer på en fysisk Windows-värd.
Det verifierar ett faktiskt producentägt block med 5 000 signerade TX,
publicering till båda CLI-ägarnas observationer och Desktops läsare,
processavslut vid LAN-stopp och återstart med samma kontrollpunkt/certifikatgolv.
Det är ingen fysisk Linux-/Androidkörning eller kapacitetsmätning.
Exakta antal/resultat för den breda frysta testomgången och paketen sparas
i den privata lokala verifieringsrapporten; inga bootstrapuppdateringar eller
Git-pushar ingår i denna interna etapp.

## Beslut, antaganden och öppet arbete

Beslut: behåll befintlig parning och filöverföring. Aktivera inget i den
redan körande operatörsappen. Samla den färdiga leveransen före fysisk acceptans
och gemensam publicering av de två Git-repona.

Antagande: fast privat kommitté om fyra identiteter med SDK-kvorum tre.
Det är inte beslutad publik medlemskapspolicy eller decentralisering.

Checkpointselektion, verifierad ordningspaginering, beständig väntande begäran
och grafmedlemskap har därefter lagts till i
[checkpointgranskningen](canonical-checkpoint-flow-review-2026-10-31.md).
Öppet: fullreplikans offentliga certifikatflöde,
genuin lättklientroll, kandidatinsamling/pruning, maximal historikåterhämtning,
partition/equivocation, monetär policy/mining/pooler och uthållig fysisk
kapacitet. Målet 5 000 TX/block vid hundratals block/s är inte uppnått.
Publikt testnät och mainnetberedskap är fortfarande inte godkända.
