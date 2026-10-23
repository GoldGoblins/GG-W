# Risk, autonomi, behörighet och godkännande

## Riskdimensioner

Bedöm:

- påverkan på människor;
- ekonomisk effekt;
- juridisk eller avtalsmässig effekt;
- informationssäkerhet;
- personuppgifter;
- rykte och extern kommunikation;
- reversibilitet;
- felupptäckt;
- volym och spridning;
- beroenden till andra system.

## Tre autonominivåer

### Självständigt tillåtet

Kräver:

- uttryckligt mandat;
- allowlistade system och mottagare;
- validerad indata;
- låg risk;
- förutsägbar och reversibel effekt;
- tydlig felväg;
- loggning;
- trösklar för avvikelse.

### Kräver mänskligt godkännande

Standard vid:

- ny mottagare eller destination;
- känslig information;
- osäker identitet;
- ekonomisk eller juridisk effekt;
- publicering;
- radering eller betydelsefull ändring;
- avvikelse från policy;
- låg tillförlitlighet;
- ny behörighet;
- ovanlig volym.

Godkännandekortet ska visa:
- exakt föreslagen handling;
- data som skickas;
- mottagare/system;
- konsekvens;
- varför agenten föreslår handlingen;
- möjlighet att ändra eller neka.

### Inte tillåtet

- självutökade behörigheter;
- kringgång av kontroll;
- osynlig loggmanipulation;
- obehörig dataöverföring;
- användning av hemligheter i klartext;
- förbjudna beslut;
- handling utanför uppdraget.

## Behörighetsmatris

Bedöm varje system separat:

| Operation | Exempel | Standard |
|---|---|---|
| read | hämta kunddata | minsta datamängd |
| create | skapa utkast/ärende | validering + logg |
| update | ändra post | ofta godkännande |
| send | mejl/publicering | mottagar- och innehållskontroll |
| delete | radera data | normalt mänskligt godkännande |

## Riskklass

### Låg
Reversibel, liten räckvidd, inga känsliga data, enkel kontroll.

### Medel
Begränsad extern effekt, personuppgifter eller betydande arbetsflödespåverkan.

### Hög
Ekonomi, juridik, säkerhet, negativ individpåverkan, masskommunikation eller irreversibel handling.

## Stoppvillkor

Stoppa vid:
- okänd mottagare;
- saknad beslutsägare;
- motstridiga regler;
- icke verifierad behörighet;
- osäker verktygsstatus efter write;
- data utanför godkänd klass;
- överskriden volym eller beloppsgräns.
