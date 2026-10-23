# 08 — Test, felsökning, Code Gate och acceptans

**Version:** 3.2.0

## Grundprincip

Testa den sak som faktiskt kan fallera på rätt nivå. Syntax, sandbox och målmiljö är olika bevis.

## Felsökningsmetod

1. beskriv reproduktion;
2. lås källfil och hash;
3. samla versioner och miljö;
4. separera förväntat från faktiskt;
5. skapa minsta reproduktion;
6. kontrollera syntax och statisk analys;
7. testa transport, argv och citering;
8. kör i isolerad sandbox;
9. klassificera felkälla;
10. ändra en faktor;
11. kör regression;
12. verifiera cleanup och mål separat;
13. dokumentera rotorsak.

## Felklasser

- **source:** fel i källkod;
- **transport:** newline, encoding, quoting eller argv;
- **dependency:** fel version eller saknat beroende;
- **harness:** testverktyget är fel;
- **sandbox:** policyn blockerar eller läcker;
- **target:** programmet misslyckas i avsedd miljö;
- **integration:** gränssnitt mellan komponenter;
- **external:** nätverk eller tredje part;
- **rollback:** återställningen är inte komplett.

Skyll inte på målsystemet innan harness och transport är bevisade.

## Bevisnivåer

1. fil integritetskontrollerad;
2. syntax godkänd;
3. lint/statisk analys godkänd;
4. unit/fixture godkänd;
5. sandbox runtime godkänd;
6. integration i lokal målklon godkänd;
7. negativ säkerhetstest godkänt;
8. restore/rollback godkänt;
9. mänsklig acceptans;
10. först därefter automation.

## Språkmatris

### Shell

Minst:

- `bash -n`;
- `sh -n` när relevant;
- ShellCheck;
- transporthash;
- argv-test;
- `set -Eeuo pipefail`-beteende;
- cleanup på signal och fel;
- sandboxkörning;
- negativtest för nätverk, sudo och hostskrivning.

### Python

Minst:

- parser/compile;
- linter;
- unit-/fixturetest;
- typkontroll när projektet kräver;
- ingen nätverksinstallation under test;
- sandbox och timeout;
- kontroll av skapade filer.

### PHP

Minst:

- `php -l`;
- WordPress Coding Standards;
- PHPStan med projektspecifik konfiguration;
- PHPUnit/fixturetest;
- kontroll av namespaces/funktionsprefix;
- escaping, sanitization, capability och nonce där relevant;
- efter CP4: lokalt WordPress-integrationstest.

### JSON/YAML

Minst:

- parse;
- schema;
- typ- och enumkontroll;
- förbjudna nycklar;
- sökvägs- och URL-policy;
- deterministisk serialisering när hash används.

## Code Gate-acceptans

Code Gate är inte klar efter ett enda grönt script. Minst:

- ett känt gott test per språkprofil;
- ett syntaxfel;
- ett lintfel;
- ett timeoutfall;
- ett minnes-/processgränsfall;
- ett nätverksförsök;
- ett förbjudet mount-/sökvägsförsök;
- ett hemlighetsmönster;
- ett transport-/quotingfel;
- ett harnessfel;
- ett cleanupfel;
- reproducerbar rapport;
- tom Podman-baslinje efter körning.

## Rapport

```markdown
# Code Gate-rapport

- Gate-ID:
- Profil/version:
- Datum:
- Källfil:
- SHA-256:
- Språk/tolk:
- Checker-versioner:
- Sandbox-image/digest:
- Nätverk:
- Mounts:
- UID/GID:
- Resursgränser:
- Fixtures:
- Syntax:
- Statisk analys:
- Unit/fixture:
- Sandbox:
- Negativtest:
- Skapade filer:
- Cleanup:
- Status: PASS / CONDITIONAL / FAIL
- Villkor:
- Målmiljötest:
- Bevis/loggar:
```

## Vad “fungerar” får betyda

- **Syntax fungerar:** parsern accepterar filen.
- **Sandbox fungerar:** definierade fixtures passerar i låst miljö.
- **Målmiljö fungerar:** faktisk målutdata visar rätt effekt.
- **Produktion fungerar:** endast efter separat produktionsplan och bevis.

Använd inte dessa formuleringar som synonymer.

## Regressionstest

Varje rotorsak ska ge ett reproducerbart test. Särskilt:

- shellcitering;
- `PIPESTATUS`;
- Git porcelain;
- `network_mode=none`;
- timeout;
- cleanup;
- XDG-rättigheter;
- hemlighetsskanning;
- agentens diffgräns.

## Incident

1. stoppa utan att förstöra bevis;
2. blockera extern effekt;
3. spara sanerade loggar och tidslinje;
4. skilj kod, harness, sandbox och mål;
5. rotera credentials vid risk;
6. återställ från verifierad punkt;
7. lägg till regression;
8. uppdatera regelkort och checkpoint.

## CP6A verifierad acceptans — 2026-08-07

Följande är nu bevisat:

- agent core build `PASS`;
- generated-file Code Gate `PASS`;
- synthetic acceptance tests `PASS`;
- independent candidate audit `PASS`;
- lokal fast-forward-promotion till `main` `PASS`;
- fysisk CP6A Code Gate-total `19`;
- Podman tom efter slutkontroll;
- modell oförändrad;
- ingen push/publicering;
- CP6B inte exekverad.

### Klart inför CP6B

CP6B-planering får använda låst CP6A-agentkärna, Code Gate och delat kunskapspaket som beroenden.

CP6B-build kräver fortfarande separat plan, Code Gate, rollback, reviewer-separation och exakt godkännande.

## Verifierad CP5C-acceptans — 2026-07-31

Följande är bevisat:

- Code Gate-profiler för shell, Python, PHP, JSON/YAML och containerdefinitioner;
- Debug Runner-kandidat publicerad;
- positiva och negativa testfall för bland annat transport, timeout, process, minne, output, nätverk, hosthemlighet, sudo/root, hemlighetsmönster, cleanup och harness;
- final testmatris `PASS`;
- publiceringscommit och status verifierade;
- Podman-runtime tom efter slutkontroll.

CP5C behöver inte köras om enbart inför CP6B så länge de låsta CP5C-filerna och evidensen är oförändrade; CP6B har egna nya Code Gate- och målverifieringskrav.

## Nya permanenta regressioner

### Inspectrepresentation

Testa både:

- JSON-objekt;
- enobjektslista.

Säkerhetskontroll ska jämföra exakta fält och mängder, inte söka globalt efter strängen `none`, värdet `true` eller ordet `ALL`.

### CapDrop

När `--cap-drop=all` exponeras som expanderad standardmängd ska validatorn:

- kräva `CapAdd=[]`;
- kräva exakt låst CapDrop-mängd;
- kräva `Privileged=false`;
- kräva read-only root;
- kräva `no-new-privileges`;
- kräva nätverk `none`;
- kräva avtalad UID/GID och user namespace.

### Nullfält

`EffectiveCaps=null` och `BoundingCaps=null` betyder att dessa inspectfält inte ger användbar lista. De får inte omtolkas till vare sig tom eller icke-tom capabilitymängd.

### Backupmode

Skapa fixture där källfilen är `0644`, processen har `umask 077` och kopieringsfunktionen måste återställa mode explicit. Innehållsfingerprint och full trädfingerprint ska testas separat.

### Resume utan omkörning

En stoppad publicering ska återuppta från låst PASS-evidens. Testet ska verifiera:

- inga tidigare tester körs om;
- ny controller kodgrindas separat;
- tidigare evidence-hashar är oförändrade;
- Git och status ändras först efter full precheck.
