# Verksamhetsbehov och problemanalys

## Syfte

Denna fil hjälper GG Agentarkitekten att förstå behovet innan en teknisk lösning väljs.

## Problemformulering

Formulera alltid:

- nuvarande situation;
- konkret problem eller möjlighet;
- vilka som påverkas;
- önskat verksamhetsresultat;
- hur resultatet mäts;
- kostnad eller risk om inget ändras;
- avgränsning.

Undvik att börja med teknik, exempelvis ”vi behöver en agent”. Översätt först till ett resultat, exempelvis ”minska tiden för manuell ärendetriagering utan att försämra kvalitet eller spårbarhet”.

## Fem kategorier

### Fakta
Uttryckligt underlag eller verifierad information.

### Beslut
Val som användaren eller verksamheten redan gjort.

### Antaganden
Reversibla, tydligt märkta tolkningar.

### Motsägelser
Krav som inte kan uppfyllas samtidigt eller saknar prioritet.

### Kunskapsluckor
Saknad information som påverkar arkitektur, risk eller mandat.

## Processkarta

Kartlägg:

1. trigger;
2. indata;
3. aktörer;
4. steg;
5. beslut;
6. undantag;
7. system;
8. utdata;
9. kvalitetskontroll;
10. slutstatus.

## Informationsvärde för frågor

Fråga först om det som mest påverkar:

- om agent behövs;
- extern systemåtkomst;
- känsliga data;
- beslutsmandat;
- ekonomisk eller juridisk effekt;
- godkännande;
- ansvarig ägare.

Kosmetiska frågor får inte blockera ett användbart första förslag.

## Mognadssignaler

### Låg mognad
- ingen processägare;
- instabila regler;
- okänd datakvalitet;
- saknad felhantering;
- oklart ansvar.

Rekommendation: processförbättring, datastädning eller begränsad pilot.

### Medelhög mognad
- processen är känd;
- variationer finns;
- data och ägare är identifierade;
- vissa kontroller saknas.

Rekommendation: read-only eller human-in-the-loop-pilot.

### Hög mognad
- tydliga regler och mandat;
- stabil data;
- definierad riskaptit;
- loggning och förvaltning;
- mätbara acceptanskriterier.

Rekommendation: kontrollerad automation eller agentisk implementation.

## Standardleverans

Sammanfatta behovet i högst tio punkter och avsluta med:

- önskat resultat;
- föreslagen lösningsnivå;
- viktigaste antagande;
- största risk;
- viktigaste nästa beslut.
