# Genomförandeunderlag per destination

## Grundregel

Genomförandeunderlaget ska översätta samma godkända idé till den form som nästa mottagare behöver. Målbilden får inte ändras bara för att destinationen ändras.

Varje underlag börjar med:

1. Vad användaren ville från början.
2. Vad vi upptäckte tillsammans.

## Gemensam kärna

Alla destinationer behöver:

- önskat slutresultat;
- användare och situation;
- problem eller möjlighet;
- huvudflöde;
- ingår och ingår inte;
- låsta beslut;
- flexibla delar;
- begränsningar;
- klart-kriterier;
- öppna frågor som nästa part får hantera.

## Till en annan GPT

Lägg till:

- GPT:ns kärnuppdrag;
- identitet och tonalitet;
- indata och utdata;
- arbetslägen;
- fråge- och beslutspunkter;
- Knowledge-behov;
- verktyg och capabilities;
- webbresearchmodell;
- säkerhetsgränser;
- testfall.

Undvik att skriva den slutliga GPT-instruktionen om uppdraget endast är överlämning till en GPT-arkitekt.

## Till en utvecklare

Lägg till:

- aktörer;
- användarresor;
- funktionella krav;
- data som finns vid start;
- tillstånd, regler och utdata;
- fel- och undantagsbeteende;
- lagring och dataägarskap;
- behörigheter;
- integrationer;
- prestanda- och kvalitetskrav;
- acceptanstester;
- sådant som uttryckligen inte ska byggas.

Teknikstack ska rekommenderas först efter relevant research och får lämnas flexibel när den inte påverkar kärnan.

## Till webb- eller appbyggare

Lägg till:

- sidkarta eller vyer;
- primär användarresa;
- innehållsansvar;
- konton och behörigheter;
- mobilanpassning;
- tillstånd före, under och efter viktiga handlingar;
- tomma lägen, fel och bekräftelser;
- visuella krav;
- analys- eller spårningsbehov;
- lanseringskriterier.

## Till automation

Lägg till:

- utlösare;
- källsystem;
- villkor;
- åtgärder;
- destination;
- frekvens;
- godkännanden;
- idempotens och dubbletter;
- felmeddelanden;
- återförsök;
- loggning;
- säkerhet och hemlighetshantering;
- rollback eller manuell reservprocess.

## Till kreativ produktion

Lägg till:

- målgrupp;
- önskad effekt;
- budskap;
- format och kanal;
- tonalitet;
- längd;
- obligatoriska fakta;
- förbjudet eller känsligt innehåll;
- referenser;
- godkännandeprocess;
- publiceringskrav.

## Till projektgrupp eller verksamhet

Lägg till:

- önskat verksamhetsresultat;
- ansvariga roller;
- beroenden;
- beslut som krävs;
- milstolpar;
- risker;
- resurser;
- mätetal;
- första validering;
- nästa konkreta handling.

## Till maskinellt system

Använd `MASKINUNDERLAG.json` när:

- ett definierat schema finns;
- fält ska valideras;
- information ska importeras;
- flera objekt ska behandlas konsekvent.

Inkludera:

- `original_intent`;
- `joint_discoveries`;
- `target_state`;
- `users`;
- `main_flow`;
- `in_scope`;
- `out_of_scope`;
- `inputs`;
- `outputs`;
- `constraints`;
- `acceptance_criteria`;
- `assumptions`;
- `open_questions`;
- `sources`.

Validera mot mottagarens schema när det finns. Hitta inte på obligatoriska värden; använd `null` eller märk en öppen fråga enligt schemat.
