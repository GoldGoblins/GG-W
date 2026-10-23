# Agentdesign, roller och arbetsflöden

## Agentkontrakt

Varje agent ska ha:

- namn och kort beskrivning;
- kärnuppdrag;
- målgrupp;
- trigger;
- indata;
- utdata;
- avgränsning;
- mandat;
- verktyg;
- beslutspunkter;
- undantag;
- stoppvillkor;
- felhantering;
- testkriterier;
- ansvarig ägare.

## Rollgräns

Skriv både vad agenten gör och vad den inte gör.

Exempel:

```text
Gör:
- klassificerar inkommande ärenden;
- föreslår kategori och prioritet;
- anger osäkerhet.

Gör inte:
- stänger ärenden;
- lovar kompensation;
- ändrar kunddata;
- fattar juridiska beslut.
```

## Utlösare–åtgärd–stopp–leverans

```text
Utlösare:
Vad som startar flödet.

Åtgärd:
Stegen i rätt ordning.

Beslut:
Vilka villkor styr nästa steg.

Stopp:
När agenten pausar, eskalerar eller avbryter.

Leverans:
Format, destination och kvalitetskrav.
```

## Indata

För varje indata ange:

- källa;
- obligatoriska fält;
- tillförlitlighet;
- känslighetsklass;
- färskhetskrav;
- validering;
- fallback om data saknas.

## Utdata

Definiera gärna strukturerat format:

```json
{
  "status": "förslag|kräver_godkännande|stopp",
  "sammanfattning": "...",
  "beslut": "...",
  "motivering": "...",
  "osäkerhet": "...",
  "källor": [],
  "nästa_steg": "..."
}
```

## Beslutspunkter

Varje beslut ska ha:

- villkor;
- tillåtna utfall;
- ägare;
- lägsta evidens;
- riskklass;
- godkännanderegel;
- loggad motivering.

## Felhantering

Skilj:

- ogiltig indata;
- saknad data;
- verktygsfel;
- behörighetsfel;
- motstridiga källor;
- låg tillförlitlighet;
- okänd slutstatus efter extern handling.

Agenten får inte dölja osäkerhet eller låtsas att ett verktyg lyckades.

## Instruktionskvalitet

Instruktioner ska innehålla konkreta utlösare, åtgärder och stoppregler. Stabil referenskunskap hör hemma i Knowledge; kritiska beteenderegler hör hemma i instruktionen.
