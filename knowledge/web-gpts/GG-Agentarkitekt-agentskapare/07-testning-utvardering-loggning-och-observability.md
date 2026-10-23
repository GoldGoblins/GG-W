# Testning, utvärdering, loggning och observability

## Testnivåer

### Struktur
- obligatoriska filer;
- teckengräns;
- manifest;
- ZIP;
- inga tomma filer.

### Beteende
- rätt lösningsnivå;
- få men avgörande frågor;
- användbart första förslag;
- tydlig avgränsning.

### Risk
- autonominivåer;
- minsta behörighet;
- mänskligt godkännande;
- förbjudna handlingar.

### Verktyg
- rätt verktyg;
- verifierad funktion;
- timeout;
- felstatus;
- idempotens.

### Multiagent
- routing;
- handoffs;
- beslutsägande;
- konflikter;
- loopskydd.

### Regression
- tidigare bra beteende;
- signaturflöden;
- kända specialregler;
- tidigare fel.

## Testfallsformat

```text
Test-ID:
Syfte:
Indata:
Förväntat beteende:
Förbjudet beteende:
Godkänt när:
Resultat:
```

## Mätvärden

- slutförandegrad;
- felaktiga externa handlingar;
- onödiga följdfrågor;
- korrekt eskalering;
- precision i routing eller klassificering;
- dataläckage;
- dubbla operationer;
- latency;
- token- och verktygskostnad;
- mänskliga korrigeringar;
- användbarhet.

## Loggmodell

Logga minst:
- körnings-ID;
- tid;
- agent och version;
- indatareferens;
- verktygsanrop;
- beslut och motivering;
- riskklass;
- godkännare;
- output;
- fel;
- slutstatus.

Logga inte hemligheter eller mer persondata än nödvändigt.

## Tracing

I fleragentsystem ska tracing kunna visa:
- modellsteg;
- verktygsanrop;
- handoffs;
- guardrails;
- godkännanden;
- fel och retries;
- total kostnad och tid.

## Eval-loop

1. definiera realistisk testmängd;
2. kör baslinje;
3. klassificera fel;
4. ändra en tydlig del;
5. kör om samma tester;
6. kontrollera regression;
7. dokumentera resultat;
8. publicera först när kritiska gränser klaras.
