# DAGoblin kapacitetsmodell

Offlineverktyget räknar exakt på angivna resurser. Det startar inga noder,
använder inga privata nycklar och ändrar inga hastighetsgränser.

```text
python support/dagoblin/analyze.py --json
python support/dagoblin/analyze.py --input support/dagoblin/capacity.example.json
```

Exempelfilen är ett **hypotetiskt scenario**, inte en mätning av din dator:
6 Gbit/s, 80 % budget, 1 000 transaktioner à 250 byte och 300 MiB RAM med
100 MiB reserverat, två sekunders datafönster och dubblerad lagringsstorlek.
Den visar hur ett minnesfönster kan bli begränsande även med snabb länk.
Köminnet är bara en del av processens RAM. CPU, GPU, disk, exekvering och
konsensus är ospecificerade i filen och får inte antas oändligt snabba.

Anpassa en egen JSON-fil. Alla tal måste vara heltal eller exakta rationaltal
som `"4/5"`; 0.8 accepteras inte. Enheter är skiftlägeskänsliga:
`Gbit/s` = decimala bit, `Gib/s` = binära bit, `GiB/s` = binära byte.

`capacity_bounds` accepterar `link`, `cpu_sign`, `cpu_verify`, `gpu`, `storage`,
`memory` och `checkpoint`; använd bara relevanta, faktiskt kända parametrar.
Detaljerade fält och standardvärden står vid funktionerna i `analyze.py`.
Ett CPU-steg kan exempelvis anges som
`{"p95_nanoseconds":1000000,"workers":4,"transactions_per_batch":1}`.
Det är ett räkneexempel; använd egna mätvärden. Arbetarna måste kunna använda
sina resurser samtidigt, annars blir summan missvisande.

Resultatets `scenario_*` är ett villkorat scenario. Bytebaserade tak ligger i
`byte_model_upper_bound_*`. Invers p95-tid är ett servicescenario och ger
varken ett matematiskt prestandatak eller en säker schedulerhastighet. För det
behövs uthålligt end-to-end-prov, svanstider och begränsade köer.

Övriga operationer: `wire_budget`, `retained_buffer`, `checkpoint_batch_cost`,
`peer_polling_cost`, `link_bytes_per_second` och `comparison_eligibility`.
De anropas med `{"operation":"namn","parameters":{...}}` via fil eller
`--input -` på stdin. Inga hastighetsvinster eller kryptografiska skydd bevisas
av en deklaration om lika testvillkor.

[Forskningsunderlag](../../knowledge/research/dagoblin/README.md).
