# 06 — Podman, WordPress och WooCommerce

**Version:** 3.2.0  
**Versionskänsligt:** Kontrollera aktuella Podman-, WordPress-, WooCommerce-, PHP-, databas- och hostingkrav.

## Aktuell beroenderoll

CP6A-agentkärnan är verifierad `PASS` och lokalt promotad. CP4 genomförs först efter godkänd CP6B-orchestrator. Den lokala agenten får senare hjälpa till med lokala verktyg, men produktionstillgång och one.com-export förblir användarstyrd och röd.

## Rootless grund

- separat nätverk och volym per miljö;
- inget `--privileged`;
- inget host network;
- inga råa `/dev`-mounts;
- read-only root och mounts när möjligt;
- capabilities bort;
- `NoNewPrivs`;
- inga publicerade portar utan plan;
- pinnade images och dokumenterade digests;
- inga hemligheter i image eller Git;
- verifierad cleanup och restore.

## WordPress-kodflöde

Rekommenderad väg för Code Snippets, plugin- och temakod:

1. skapa fullständig PHP-fil i Git;
2. lås SHA-256;
3. kör PHP-syntaxkontroll;
4. kör WordPress Coding Standards;
5. kör PHPStan med versionslåsta stubs;
6. kör enhets-/fixturetest;
7. kör i Code Gate utan nätverk;
8. efter CP4: kör i lokal WordPress/WooCommerce;
9. visa diff och acceptansrapport;
10. användaren kopierar eller deployar manuellt till one.com efter separat rött beslut.

Code Snippets i produktion ska inte vara den enda källan. Den versionshanterade PHP-filen är master.

## CP4.1 — källinventering

Samla sanerat:

- WordPress-, WooCommerce-, PHP- och databasversion;
- tema/child theme;
- plugins och versioner;
- Code Snippets-lista och exportmetod;
- cron;
- e-post;
- betalningar;
- webhooks;
- externa API:er;
- media- och databasstorlek;
- backup- och restoremöjligheter.

Visa inte credentials, cookies eller kunddata.

## CP4.2 — backup och sanering

- användaren hämtar eller skapar export med godkänd one.com-metod;
- rå produktionsbackup hålls utanför Git och ChatGPT;
- checksummor och manifest skapas;
- persondata minimeras/anonymiseras;
- produktionsnycklar ersätts;
- dummyadmin och testidentiteter skapas;
- saneringen verifieras innan import.

## CP4.3 — lokal stack

Versioner väljs från inventeringen. Stacken ska minst innehålla:

- WordPress/PHP;
- kompatibel databas;
- lokal mail catcher;
- separata nätverk och volymer;
- healthchecks;
- resursgränser;
- lokal-only bindning;
- visuell LOCAL/TEST-markering.

## CP4.4 — externa effekter

Bevisa:

- inga riktiga mejl;
- inga riktiga betalningar;
- inga produktionswebhooks;
- inga skrivande produktions-API:er;
- kontrollerad cron;
- inga produktionscredentials;
- noindex;
- ingen publik exponering.

Konfiguration räcker inte; kör negativa testfall.

## CP4.5 — URL-migrering

Använd serialiseringsmedveten metod och dry-run. Rå SQL-replace är förbjuden utan särskild bevisning.

Verifiera:

- `home` och `siteurl`;
- media;
- block och widgets;
- plugininställningar;
- webhook-URL:er;
- kvarvarande produktionsdomäner.

## CP4.6 — acceptans och restore

Testa:

- frontend;
- produkter och variationer;
- varukorg och kassa utan verklig betalning;
- admin;
- Code Snippets;
- media och permalänkar;
- mail catcher;
- negativa externa effektstest;
- restore till en andra separat testinstans.

## Agentgräns i CP4

Tillåtet:

- generera lokala inventeringsscript;
- validera exporter;
- skapa containerdefinitioner;
- köra sanering mot lokal kopia;
- skriva tester;
- analysera lokala loggar;
- skapa branch och commit.

Förbjudet:

- självständigt one.com-login;
- autonom export av produktion;
- läsning av riktiga credentials;
- produktionstestorder;
- extern webhook;
- deploy eller aktivering av snippet i produktion.

## Git

Versionshantera egen kod, manifest, containerdefinitioner, saneringsscript, tester och dokumentation.

Versionshantera inte rå databas, credentials, kunddata, uploadsarkiv, runtime-loggar eller lokala volymer.


## Aktuell spärr 2026-08-07

CP4 får inte startas enbart för att CP6A är klar. Följande saknas fortfarande:

- godkänd CP6B-orchestrator;
- verifierad one.com-källinventering;
- namngiven backup-, export- och saneringsplan;
- lokalt WordPress-specifikt Code Gate-kontrakt.

CP6A är däremot inte längre en blockerare: agentkärnan är verifierad och lokalt promotad.

Ingen kunskapsuppdatering eller CP6B-status ger agenten rätt att logga in på one.com, läsa produktionscredentials eller påverka produktion.
