# Lösningsstege och arkitekturbeslut

## Grundregel

Välj lägsta nivå som uppfyller verksamhetsmålet. Teknik är ett medel, inte målet.

## Nivå 0 — Ingen agent

Använd när en process, mall, checklista, utbildning, regelmotor eller vanlig programvara räcker.

Typiska tecken:

- stabilt och helt deterministiskt flöde;
- låg språklig variation;
- inget behov av omdöme;
- enkel mänsklig rutin löser problemet billigare.

## Nivå 1 — Enkel anpassad GPT

Passar för analys, skrivstöd, förklaring, strukturerade förslag eller smal Knowledge-användning utan externa effekter.

## Nivå 2 — Specialiserad agent

Passar när arbetet består av flera steg, varierande indata, återkommande beslut och definierat uppdrag men begränsad systemåtkomst.

## Nivå 3 — Agent med verktyg eller integrationer

Passar när agenten måste hämta data, kalla verktyg eller genomföra kontrollerade operationer. Varje operation kräver separat riskbedömning.

## Nivå 4 — Automation

Passar när flödet är regelstyrt, frekvent och förutsägbart. En automation kan omsluta en agentisk del, exempelvis:
- agent tolkar fri text;
- regelmotor validerar;
- automation registrerar;
- människa godkänner avvikelse.

## Nivå 5 — Flera samverkande agenter

Motiveras av tydligt olika specialistroller, kontexter, verktyg eller behörigheter. Inte av önskan att låta lösningen verka avancerad.

## Nivå 6 — Större agentsystem

Kräver normalt:
- flera processer eller avdelningar;
- gemensam styrning;
- identitet och åtkomsthantering;
- central observability;
- kostnads- och kapacitetskontroll;
- förvaltningsorganisation;
- systemövergripande evals.

## Beslutsmatris

Poängsätt 0–2:

- språklig variation;
- antal steg;
- behov av omdöme;
- systemåtkomst;
- externa effekter;
- felkostnad;
- antal roller;
- behov av kontinuitet;
- behov av samordning;
- drift- och förvaltningsmognad.

Poäng är endast analysstöd. Hög risk ska inte automatiskt leda till mer autonomi.

## Arkitekturbeslutspost

Dokumentera:

```text
Beslut:
Vald nivå:
Behov:
Alternativ:
Varför enklare nivå inte räcker:
Varför mer avancerat inte behövs:
Risker:
Förutsättningar:
Uppgraderingssignal:
Beslutsägare:
Datum:
```

## Överdimensioneringskontroll

Fråga:

1. Kan detta lösas utan LLM?
2. Kan en enda GPT lösa det?
3. Kan systemåtkomst tas bort?
4. Kan skrivning ersättas med förslag?
5. Kan flera agenter ersättas med ett flöde?
6. Kan högrisksteget flyttas till människa eller regelmotor?
