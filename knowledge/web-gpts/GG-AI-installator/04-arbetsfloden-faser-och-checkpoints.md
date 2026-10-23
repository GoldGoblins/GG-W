# 04 — Arbetsflöden, faser och checkpoints

**Version:** 3.2.0


## Aktuell verifierad fas — 2026-08-07

| Fas | Status |
|---|---|
| CP1–CP3 | historiskt klara |
| CP5A | verifierad klar |
| CP5B | verifierad klar i 4096-scope |
| CP5C | `PASS_PUBLISHED` |
| CP6A | `PASS`; independent audit `PASS`; local promotion `PASS` |
| CP6B | scope/contract inventory `PASS_READ_ONLY`; build ej påbörjad |
| CP4 | väntar på CP6B |
| CP6C | ej påbörjad |

Nästa atomiska steg är att formulera en namngiven CP6B-byggplan från de låsta kontrakten. Ingen CP6B-build, CP4 eller extern produktionseffekt är godkänd ännu.

## Standardflöde

1. **Orientera:** mål, aktuell checkpoint, verifierat och saknat.
2. **Klassificera:** risk, miljö, effekt och reversibilitet.
3. **Researcha:** officiella och versionsaktuella källor.
4. **Förkontrollera:** komplett läsande block före gul/röd plan.
5. **Analysera:** faktisk utdata innan plan.
6. **Planera:** mål, beroenden, Code Gate, verifiering, rollback och stopp.
7. **Godkänn:** exakt plan-ID och version.
8. **Förvalidera kod:** syntax, statisk analys och sandbox.
9. **Genomför:** ett fullständigt atomiskt steg.
10. **Verifiera mål:** separat funktionstest i verklig miljö.
11. **Dokumentera:** journal, beslut och checkpoint.

## Princip: checkpoint-ID är inte körordning

CP-numret bevaras för historisk spårbarhet. Efter CP3 följer arbetet beroenden, inte numerisk ordning.

## Avslutade faser

### CP1 — systembaslinje

Historiskt klar.

### CP2 — backup och restore

Historiskt klar.

### CP3 — säker utvecklingsgrund

Historiskt klar med Git, rootless Podman, miljöseparation, policyer och CP3-checkpoint.

## Reviderad fortsättning

### Fas A — CP5A: aktuell AI-kapacitetsinventering

Samla:

- GPU och drivrutin;
- CUDA/compute-stöd;
- RAM och ledigt minne;
- diskbudget;
- temperatur- och throttlingverktyg;
- CPU-egenskaper;
- nätverks- och sekretesskrav.

Ingen runtime väljs på historisk profil ensam.

### Fas B — CP5B: runtime och modell

- välj minsta modell som klarar testbatteriet;
- dokumentera licens, källa, hash och resursbudget;
- installera med gul plan;
- testa stabilitet, temperatur och lokal bindning.

### Fas C — CP5C / CP5.5: GG Code Gate och Debug Runner

Bygg ett separat deterministiskt verktygslager som:

- tar emot en låst källfil;
- väljer språkprofil;
- kör secret scan, syntax, lint och statisk analys;
- kör fixtures och negativa tester;
- exekverar i disponibel rootless sandbox;
- saknar nätverk och hosthemligheter;
- samlar stdout, stderr och exitkoder;
- skapar signerbar rapport;
- stoppar på `FAIL` och oförklarad `CONDITIONAL`.

Code Gate måste ha egna regressionstester innan en agent får skriva kod.

### Fas D — CP6A: agentkärna

Agenten arbetar endast i syntetiska projekt och får:

- läsa avtalad projektmapp;
- skapa task-branch;
- ändra begränsat antal filer;
- anropa Code Gate;
- visa diff;
- skapa lokal commit om regelkortet tillåter.

Ingen WordPress-, one.com- eller produktionsåtkomst.

### Fas E — CP6B: lokal orchestrator

Orchestratorn:

- skapar uppgifts-ID;
- väljer specialistroll;
- delar versionsmärkt kontext;
- samlar handoff och evidens;
- kräver Code Gate och reviewer;
- stoppar rättighetsutökning;
- gör ingen merge eller deploy.

### Fas F — CP4: agentassisterad WordPress/WooCommerce-klon

Agenten får hjälpa med lokala script, manifest, sanering, containerdefinitioner och tester.

Användaren styr:

- one.com-åtkomst;
- backup/export;
- credentials;
- godkännande av produktionsrelaterade steg.

CP4 är klar först när klonen är sanerad, isolerad, URL-migrerad, acceptanstestad och restore-testad.

### Fas G — CP6C: agent kopplad till lokal WordPress

Först efter CP4 får agenten:

- läsa lokal WordPress-kod;
- ändra versionshanterade snippets/plugins/tema;
- köra WordPress-specifik Code Gate;
- köra lokal acceptans;
- skapa branch och commit.

Ingen automatisk produktion eller one.com-deploy.

### Fas H — gradvis automation

Börja med:

- dokumentationskontroll;
- kodgrind;
- backupverifiering;
- versionsbevakning;
- lokala rapporter.

Högre risk kräver flera reproducerbara körningar, kända felvägar, rollback och nytt regelkort.

## Kodleveransformat

Varje kodleverans ska ange:

- språk och målmiljö;
- fullständig fil;
- källhash;
- utförda lokala analyser;
- saknade målberoenden;
- Code Gate-profil och resultat;
- exakt körblock;
- separat målverifiering;
- rollback.

## Arbetsjournal

```text
Uppgifts-ID:
Datum:
Checkpoint/fas:
Mål:
Riskklass:
Plan-ID/version:
Godkänd av:
Källhash:
Code-Gate-profil:
Checker-versioner:
Sandbox:
Fixtures:
Resultat:
Målmiljö:
Branch:
Ändrade filer:
Tester:
Avvikelser:
Rollbackstatus:
Nästa steg:
```

## Checkpoint

Skapa checkpoint när:

- runtime eller modell låses;
- Code Gate godkänns;
- agentens behörighet ändras;
- orchestratorn godkänns;
- CP4-klonen accepteras;
- ett nytt regelkort tas i drift.

Historiska checkpoints skrivs inte om. Nya beslut läggs i beslutspost eller ny checkpoint.


## Publicerings- och resume-flöde

Vid en stoppad publicering:

1. bevara controller, staging, rapporter och inspect-data;
2. verifiera att ingen automatisk omkörning skett;
3. kör en läsande audit av faktisk delstatus;
4. klassificera felet som källa, gate, validator, backup, Git, status eller mål;
5. formulera amendment med exakt ändringsyta;
6. kodgrinda endast ny controllerkod;
7. verifiera rollback före Git- eller statusändring;
8. fortsätt från låst evidens;
9. slutverifiera Git, status, kandidat, evidens och tom runtime separat.

## Verifierade CP5C-lärdomar

- Podman inspect kan returnera en enobjektslista.
- `HostConfig.CapDrop` kan exponeras som expanderad mängd i stället för bokstavlig `ALL`.
- `EffectiveCaps` och `BoundingCaps` kan vara `null` och får då inte användas som positivt säkerhetsbevis.
- Strict `umask` kan ändra kopierade filmoder.
- Ett säkert stopp före Git ska inte “städas bort”; evidensen ska bevaras och auditeras.
