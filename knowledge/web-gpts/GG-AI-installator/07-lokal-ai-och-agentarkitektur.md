# 07 — Lokal AI, Code Gate och agentarkitektur

**Version:** 3.2.0


## Verifierad lokal implementation — 2026-08-07

### Runtime och modell

- Runtimeimage: `localhost/gg-llama-cpp-vulkan:b10182` — verifierad/använd i CP6A 2026-08-07.
- Image ID: `0a4db391fe04f0a5370ccc04bf2b9c3960180e569092a1e51a48d30ab425d178` — verifierad CP6A-låsning.
- Image digest: `sha256:61f81360fdf2d10c069cf183d1a8671f19977015d8fd42ef9868654c44697e44` — verifierad CP6A-låsning.
- Modellagring: `/home/GG/models`.
- Inventerad storlek `2889514341` byte — historisk inventering 2026-07-31.
- Host-CLI `ollama`, `llama-server` och `llama-cli`: senast verifierat saknade 2026-07-31; inte nykontrollerade i CP6A-slutsteget.
- Lyssnande AI-portar: senast verifierat inga 2026-07-31; inte nykontrollerade i CP6A-slutsteget.
- Runtimeklass för CP6A: containerbaserad llama.cpp/Vulkan-runtime; host-CLI ska inte antas aktuell utan ny kontroll.

CP6A verifierade och använde följande lås:

- modellfil: `/home/GG/models/qwen3-4b-q5_k_m/Qwen3-4B-Q5_K_M.gguf`;
- modell-SHA-256: `aca596860e8cb40af6539e3f2ea40df305f42515deac56d49c08d39a02e6533f`;
- rendernod: `/dev/dri/renderD129`;
- runtimeimage: `localhost/gg-llama-cpp-vulkan:b10182`;
- CP6A runtime starts: 2;
- modellinferens: 1;
- fysisk CP6A Code Gate-total efter slutförande: 19.

### Code Gate och Debug Runner

CP5C är publicerad på Git-commit `9cee2ad703cd516fc16746d8ad571ac30e6c0d3f`.

Publicerat:

- 24 Debug Runner-kandidatfiler;
- fem Code Gate-profiler;
- `CODE-GATE-MANIFEST.yml`;
- `CODE-GATE-ACCEPTANCE-REPORT.md`;
- `DEBUG-RUNNER-REPORT.md`.

Slutstatus: `PASS_PUBLISHED`.

## CP6A verifierad slutstatus

```text
CP6A_BUILD=PASS
CP6A_INDEPENDENT_CANDIDATE_AUDIT=PASS
CP6A_LOCAL_PROMOTION=PASS
MAIN_HEAD=1144492f17df1c749f734175c6a1e4742ff95a41
PROMOTION_TYPE=FAST_FORWARD_ONLY
PUSH_PERFORMED=NO
PUBLICATION_PERFORMED=NO
CP6B_EXECUTION_PERFORMED=NO
```

CP6A-agentregeln har fortfarande `cp6b_routing=false`. Multiagent-routing tillhör CP6B och måste byggas som separat, versionsmärkt orchestratorlager.

## Arkitekturlager

### 1. Modellager

Dokumentera runtime, modell, kvantisering, licens, checksumma, kontext, RAM/VRAM, disk, temperatur och svarstid.

### 2. GG Code Gate

Deterministiskt kontrollager mellan genererad kod och verklig körning.

Komponenter:

- intake och källhash;
- filtyp/encoding/line-ending-kontroll;
- hemlighets- och policyskanning;
- syntax och parser;
- lint och statisk analys;
- dependency- och versionskontroll;
- fixture- och regressionstest;
- disponibel sandbox;
- rapportgenerator;
- artefaktkvitto.

### 3. Debug Runner

Kör endast godkänd testprofil och samlar:

- exakt kommando och argv;
- arbetskatalog;
- mountlista;
- nätverksläge;
- UID/GID;
- process- och resursgränser;
- stdout och stderr separat;
- exitkod;
- signal/timeout;
- skapade filer;
- cleanupresultat.

Debug Runner ska kunna skilja:

- källfel;
- parser-/citeringsfel;
- argumenttransportfel;
- dependencyfel;
- testharnessfel;
- sandboxpolicyfel;
- målprogramfel.

### 4. Agentlager

Agenten planerar och redigerar men får inte själv markera kod som godkänd. Den måste lämna källan till Code Gate och acceptera resultatet.

### 5. Orchestratorlager

Lokal orchestrator hanterar:

- uppgifts-ID;
- rollval;
- handoffs;
- versionsmärkta kunskapsreferenser;
- policykontroll;
- Code Gate-körning;
- reviewerbeslut;
- stopp och rapport.

### 6. Verktygslager

Inledningsvis:

- avgränsad filåtkomst;
- Git;
- Code Gate;
- rootless Podman;
- dokumentation;
- syntetiska fixtures;
- read-only systeminventering.

WP-CLI och testdatabas läggs till först efter CP4.

### 7. Policylager

- allowlist/denylist;
- katalog- och mountgränser;
- kommandogränser;
- nätverkspolicy;
- diffgräns;
- timeout och maxsteg;
- resursgränser;
- godkännanden;
- rollback;
- kill switch.

### 8. Observability

Logga metadata och bevis, inte hemligheter:

- uppgifts-ID;
- modell/runtime/checkerversion;
- källhash;
- verktygsanrop;
- Code Gate-profil;
- exitkoder;
- testresultat;
- diff;
- resursanvändning;
- godkännanden;
- cleanup och rollback.

## Code Gate-profiler

### Shell

- `bash -n`;
- `/bin/sh -n` när POSIX krävs;
- ShellCheck;
- test av käll- och transporthash;
- exakt argv;
- sandbox med nätverk av;
- syntetiskt filsystem;
- timeout och negativtest.

### Python

- parser/compile;
- Ruff eller fastställd linter;
- unit-/fixturetest;
- inga paketinstallationer under test;
- sandbox utan nätverk;
- bytecode/cache utanför projektet eller avstängt.

### PHP/WordPress

- `php -l`;
- PHPCS med WordPress Coding Standards;
- PHPStan med versionslåsta stubs;
- PHPUnit/fixturetest;
- WordPress-hook- och capabilitykontroll;
- efter CP4: integration mot lokal klon;
- aldrig direkt mot one.com i grinden.

### Data och konfiguration

- JSON/YAML-parse;
- schema;
- förbjudna nycklar;
- sökvägsnormalisering;
- inga hemligheter;
- diff mot förväntat.

## Resultatnivåer

- **PASS:** definierad profil helt godkänd.
- **CONDITIONAL:** saknat målberoende eller integrationstest.
- **FAIL:** policy- eller testfel.

Ingen modell får omtolka `FAIL` till godkänt.

## Multiagentroller

- Idékompassen 2.0 är obligatorisk första mål-, nytto- och scopekontroll.
- Metaarkitekten skapar lösningsram och beroendegraf.
- Agentarkitekten definierar roller, verktyg, minne, handoffs och rättighetsgränser.
- AI installatör verifierar system, runtime och sandbox.
- Webmaster granskar WordPress/PHP.
- Reviewer äger oberoende acceptans.

Roller kommunicerar via strukturerade filer:

```text
TASK.yml
HANDOFF.json
EVIDENCE.jsonl
CODE-GATE-REPORT.json
REVIEW.md
```

Web-GPT:er kan manuellt läsa samma paket och skapa handoffs. Autonom samordning sker bara i den lokala/API-orchestrator som faktiskt byggts.

## Första agentbehörighet

Tillåt:

- ett syntetiskt repository;
- task-branch;
- dokumentationsmapp;
- Code Gate-input/output;
- godkända checkers;
- read-only systemprofil.

Blockera:

- hela hemkatalogen;
- `.ssh`, browserprofiler och lösenordshanterare;
- `/dev`, boot och systembus;
- sudo;
- produktion och one.com;
- extern nätverkstrafik;
- regelkort och policyfiler för egen modifiering;
- direkt terminalkörning utanför Code Gate.

## Första agentuppgift

Agenten ska:

1. läsa en syntetisk buggrapport;
2. skapa branch;
3. ändra högst avtalat antal filer/rader;
4. skicka ändringen genom Code Gate;
5. stanna på fel;
6. visa diff;
7. skapa commit om regelkortet tillåter;
8. lämna handoff och rollback;
9. inte mergea eller deploya.

## Modellutvärdering

Testa svensk teknisk dialog, kod, diffgranskning, felsökning, policyefterlevnad, lång kontext, svarstid, resursanvändning, temperatur och stabilitet.

Modellens förslag är rådgivande. Deterministiska checkerresultat och faktisk systemutdata har högre prioritet.


## CP6A-agentkärna kontra CP6B-orchestrator

### CP6A

En agentkärna med:

- en uppgift i taget;
- Idékompasskontrakt;
- syntetiskt repository;
- explicit task-branch;
- begränsade läs- och skrivpaths;
- Code Gate;
- diffgräns;
- lokal commit om regelkortet tillåter;
- stopp utan merge eller deploy.

### CP6B

En separat orchestrator med:

- rollval;
- specialist-handoffs;
- versionsmärkt delad kunskap;
- reviewerbeslut;
- policykontroll;
- samlad evidens;
- ingen självutökning av behörigheter.

CP6A får inte beskrivas som CP6B och får inte smyga in autonom rollrouting.
