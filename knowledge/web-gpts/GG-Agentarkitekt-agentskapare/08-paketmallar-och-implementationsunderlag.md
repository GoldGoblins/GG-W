# Paketmallar och implementationsunderlag

## Standardpaket för en agent

```text
AGENTPAKET/
├── README.md
├── 00-behov-och-arkitekturbeslut.md
├── 01-agentinstruktioner.txt
├── 02-arbetsfloden-och-beslut.md
├── 03-knowledge-plan.md
├── 04-verktyg-och-integrationer.md
├── 05-risk-behorighet-och-godkannande.md
├── 06-testsvit.md
├── 07-installation-och-konfiguration.md
├── 08-antaganden-och-oppna-fragor.md
├── KALLOR.md
├── MANIFEST.json
└── knowledge/
```

## Tillägg för fleragentsystem

```text
agents/
    agent-a/
    agent-b/
system/
    ansvarskarta.md
    kommunikationskontrakt.md
    handoffs-och-eskalering.md
    konflikt-och-felhantering.md
    systemtest.md
```

## Mall: behov och arkitekturbeslut

```markdown
# Behov
## Problem
## Önskat resultat
## Användare
## Process
## Data och system
## Risker
## Vald lösningsnivå
## Bortvalda alternativ
## Förutsättningar
## Klart-kriterier
```

## Mall: riskkort

```text
Handling:
System:
Operation:
Data:
Mottagare:
Riskklass:
Självständigt tillåtet när:
Kräver godkännande när:
Inte tillåtet:
Loggning:
Felväg:
Ansvarig ägare:
```

## Mall: integrationsspecifikation

```markdown
# Integration
## Affärsbehov
## Systemägare
## Operationer
## Autentisering och scopes
## Datakontrakt
## Externa effekter
## Godkännande
## Idempotens
## Fel och retries
## Loggning
## Testmiljö
## Produktionskrav
```

## Mall: installationsunderlag

Inkludera:
- plattform och version;
- nödvändiga capabilities;
- filer och var de laddas upp;
- miljövariabler som platshållare;
- behörigheter;
- testdata;
- aktiveringsordning;
- smoke test;
- rollback;
- ägare och supportväg.

## Filkvalitet

Varje fil ska:
- ha tydligt syfte;
- vara självständig;
- sakna hemligheter och tomma platshållare;
- använda konsekventa begrepp;
- skilja beslut från rekommendation;
- ange verifieringsdatum för versionskänslig fakta.
