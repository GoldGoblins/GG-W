# 03 — Riskmodell, godkännanden och stopp

**Version:** 3.1.0  
**Status:** Säkerhetskritisk referens

## Grundregel

Högsta tillämpliga riskklass styr. Ett godkännande gäller endast den namngivna planen och versionen. Ett grönt testresultat sänker inte automatiskt risken för den verkliga målåtgärden.

## Grön åtgärd

Typiska exempel:

- läsa systeminformation och loggar;
- inventera filer;
- statisk analys;
- syntaxkontroll;
- diff, simulering eller dry-run;
- skapa dokumentation i avtalat projektområde;
- köra syntetiska tester i en redan godkänd Code Gate-profil när:
  - nätverk är avstängt;
  - ingen hostskrivning är möjlig;
  - inga hemligheter eller produktionsdata används;
  - resurs- och tidsgränser är fasta;
  - sandboxen städas och verifieras.

Grön klass betyder inte att koden är godkänd för host eller produktion.

## Gul åtgärd

Typiska exempel:

- installera eller uppdatera paket;
- skapa eller ändra Code Gate-runtime;
- skapa rootless-containrar, volymer eller nätverk;
- köra främmande eller genererad kod med skrivbar testyta;
- ändra användarkonfiguration;
- starta lokal tjänst;
- skapa agent- eller orchestratorruntime;
- köra migrering i lokal testdatabas;
- skapa eller radera testresurser.

Krav:

1. exakt mål;
2. aktuell förkontroll;
3. beroenden och verktygsversioner;
4. Code Gate-plan;
5. backup eller annan rollback;
6. verifieringskommando;
7. stoppvillkor;
8. användarens exakta godkännande.

## Röd åtgärd

Typiska exempel:

- boot, UEFI, LUKS, Secure Boot, TPM;
- SELinux-policy eller systembrandvägg;
- privilegierade tjänster;
- rå diskåtkomst;
- produktion, one.com, kunddata eller produktionshemligheter;
- riktiga mejl, betalningar, publicering och webhooks;
- externa skrivande API-anrop;
- kostnader, radering eller overwrite-restore;
- agent som får produktionsåtkomst eller självändrande policy.

Code Gate kan hitta fel i röd kod, men kan inte göra den röda åtgärden grön.

## Code Gate-status

### PASS

Alla obligatoriska kontroller för den definierade profilen är gröna. Målmiljön kan ändå kräva separat test.

### CONDITIONAL

Koden klarar vissa kontroller men saknar representativ fixture, beroende, versionsmatchning eller integrationstest. Verklig körning stoppas tills villkoret är löst eller en särskild riskplan godkänns.

### FAIL

Syntax, lint, policy, sandbox, test, hemlighetsskanning eller resursgräns misslyckas. Koden får inte köras vidare.

## Godkännandeformat

```text
Plan-ID:
Version:
Mål:
Riskklass:
Miljö:
Tillåtna mål:
Förbjudna mål:
Code-Gate-profil:
Källhash:
Förkontroller:
Steg:
Verifiering:
Rollback:
Stoppvillkor:
Godkänd av:
Godkänd tid:
```

## Regelkort för Code Gate och agent

Ett regelkort måste ange:

- tillåtna språk och tolkar;
- checker- och runtimeversioner;
- läs- och skrivsökvägar;
- mountpolicy;
- nätverkspolicy;
- max CPU, RAM, processer, filer, bytes och tid;
- syntetiska fixtures;
- förbjudna systemanrop eller kommandon;
- obligatoriska teststeg;
- rapportformat;
- cleanup och rollback;
- manuell kill switch.

## Automatiska stopp

Stoppa när:

- källhash eller filinnehåll ändras efter granskning;
- syntax- eller statisk kontroll misslyckas;
- sandboxen får nätverk eller oväntad mount;
- kod försöker nå `$HOME`, SSH, browserprofiler, `/dev` eller systembus;
- kod begär sudo/root;
- test använder produktion eller riktiga credentials;
- kodgrindsrapport saknas eller är `FAIL`;
- `CONDITIONAL` inte är uttryckligen löst;
- agenten försöker hoppa över grinden;
- diff-, fil-, tids- eller resursgräns överskrids;
- cleanup inte kan bevisas;
- utdata avviker från planen.

## Avvikelsehantering

1. stoppa;
2. bevara relevanta loggar utan hemligheter;
3. skilj kodfel, testharnessfel, transportfel och målmiljöfel;
4. återställ bara egna resurser;
5. verifiera rollback separat;
6. skapa minsta reproduktion;
7. lägg till regressionstest;
8. begär nytt godkännande om planen ändras.

## Hemligheter och persondata

Visa inte värden. Rapportera endast typ, sökväg, radnummer eller träffklass. En exponerad credential ska spärras eller roteras. Produktionsdata får inte användas som bekväm testfixture.


## Amendment- och resume-regel

När en godkänd gul eller röd plan stoppar:

1. kör inte om automatiskt;
2. bevara hela evidensroten;
3. fastställ exakt var stoppet skedde;
4. verifiera om Git, status, runtime eller mål hann ändras;
5. använd grön forensisk audit när det räcker;
6. formulera ett namngivet amendment om planen måste ändras;
7. kräv ny exakt godkännandefras för amendmentet;
8. återanvänd endast låst PASS-evidens vars hash och semantik verifierats;
9. kodgrinda ny exekverbar resume-controller separat;
10. kringgå aldrig stoppet med en alternativ teknisk väg.

Ett amendment får inte retroaktivt utöka den ursprungliga planen utan att den nya skillnaden beskrivs.

## Eftervalidator och Code Gate

En Code Gate-rapport med `status=PASS` och korrekt källhash är bevis för den definierade grinden. En separat eftervalidator kan fortfarande stoppa publiceringen.

Om eftervalidatorn förväntar fel schema eller representation ska detta klassificeras som validator- eller harnessfel, inte som att Code Gate-körningen misslyckades. Den låsta rapporten och container-inspect-filen ska granskas utan omkörning.

## Filmoder och strikt umask

Backup och kopiering ska verifiera:

- pathmängd;
- typ;
- storlek;
- SHA-256;
- mode;
- symlinkfrånvaro;
- ägare när det är relevant.

`os.open(..., mode)` påverkas av processens `umask`. När exakt mode ingår i kontraktet ska kopian följas av explicit `chmod` och ny fingerprintkontroll.
