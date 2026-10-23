# Multiagent, orkestrering och handoffs

## När flera agenter behövs

Motiverat när specialistroller behöver olika:

- instruktioner;
- Knowledge;
- verktyg;
- behörigheter;
- riskregler;
- kontextfönster;
- ansvar för användarsvaret.

Inte motiverat enbart för att uppgiften har flera steg.

## Två huvudmönster

### Handoff
En specialist tar över ägarskapet för nästa del eller svar.

Använd när:
- specialistens mandat verkligen ska ta över;
- användaren bör veta vilken roll som ansvarar;
- olika policyer gäller per gren.

### Agent som verktyg
En koordinator behåller ägarskapet och anropar specialister som avgränsade funktioner.

Använd när:
- ett sammanhållet slutresultat krävs;
- specialisterna inte ska kommunicera direkt med användaren;
- koordinatorn ska lösa konflikter.

## Ansvarskarta

För varje beslut definiera exakt en:
- ansvarig agent eller människa;
- godkännare;
- konsultativ roll;
- informerad roll.

Undvik delat slutansvar.

## Handoff-kontrakt

```text
Från:
Till:
Trigger:
Överförd kontext:
Förbjuden kontext:
Förväntad output:
Tidsgräns:
Returvillkor:
Felväg:
Ägare efter handoff:
```

## Konfliktlösning

Prioritetsordning:
1. säkerhet och lag;
2. beslutad verksamhetspolicy;
3. behörighetsgräns;
4. auktoritativ systemkälla;
5. ansvarig beslutsägare;
6. agentens rekommendation.

## Driftsregler

Definiera:
- correlation ID;
- idempotens;
- deduplicering;
- timeout;
- retry-budget;
- circuit breaker;
- fallback;
- mänsklig takeover;
- maximal agentkedja;
- kostnadsgräns.

## Systemtest

Testa:
- korrekt routing;
- fel routing;
- förlorad kontext;
- otillåten dataöverföring;
- agentkonflikt;
- specialistfel;
- loop;
- dubbla externa handlingar;
- mänsklig eskalering;
- slutresultatets ägarskap.
