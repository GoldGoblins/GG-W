# Data, system, verktyg och integrationer

## Integrationsbedömning

För varje integration dokumentera:

- affärsbehov;
- systemägare;
- miljö: test eller produktion;
- operationer;
- data in och ut;
- autentisering;
- behörighetsomfattning;
- rate limits och kostnad;
- felkoder;
- timeout och retry;
- idempotens;
- loggning;
- retention;
- rollback eller kompensation;
- godkännandepunkter.

## Verktygsprincip

Lägg inte till verktyg bara för att de finns. Verktyget ska lösa ett identifierat problem bättre än enklare alternativ.

## Read kontra write

Read-only är inte riskfritt:
- data kan vara känslig;
- fel källa kan ge fel beslut;
- onödigt bred åtkomst ökar exponering.

Write kräver dessutom:
- destinationskontroll;
- validering;
- idempotens;
- efterkontroll;
- okänd-status-hantering;
- återställning.

## Autentisering

Använd:
- minst privilegium;
- separata serviceidentiteter;
- kortlivade eller roterbara credentials;
- säkra hemlighetslager;
- scopes per operation;
- testcredentials i testmiljö.

Lägg aldrig riktiga nycklar i instruktioner, Knowledge, exempel eller loggar.

## API-kontrakt

```text
Operation:
Metod och endpoint:
Syfte:
Indata:
Utdata:
Autentisering:
Behörighet:
Extern effekt:
Idempotens:
Timeout:
Retry:
Fel:
Godkännande:
Loggning:
```

## MCP, appar och Actions

Bedöm:
- vem som driver servern;
- vilka verktyg som exponeras;
- data som lämnar miljön;
- om verktygsbeskrivningar kan manipuleras;
- workspace- och adminregler;
- användargodkännande;
- versions- och distributionsmodell.

## Fel efter extern handling

Vid timeout efter write får agenten inte anta vare sig framgång eller misslyckande. Den ska:
1. kontrollera idempotensnyckel eller transaktionsstatus;
2. undvika blind retry;
3. logga okänd status;
4. eskalera om status inte kan verifieras.
