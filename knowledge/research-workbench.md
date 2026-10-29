# RESEARCH Workbench

Källkö, återläsbara original, kravbundna kontroller, användningsjournal,
källhistorik och statisk skill-granskning delas mellan GROK TUI, GPT TUI och
RESEARCH → WORKBENCH. Alla data ligger i användarens befintliga research-databas.
Ingen funktion här ger exekverings-, nätverks- eller installationsbehörighet.

## För användaren

Klistra in länkar i **Källkö** och skapa ett namngivet jobb. Dubbletter slås
ihop. Spela/pausa gör kön tillgänglig för det godkända AI-arbetet eller pausar
den. Stopp behåller redan sparat material. Det är en arbetskö åt AI:n: knappen
startar ingen separat automatisk webbläsare. Inloggningshinder visas som
blockerade källor och kan läggas tillbaka i kön. Avbrutna källor kan återtas
när deras korta arbetslås löpt ut; programstart hämtar ingenting automatiskt.

**Original** visar sparad text efter maskning. Radantal, utelämnade rader och
exitstatus följer med utdraget. **Tester** visar körda kontroller och markerar
dem inaktuella om deklarerade filer eller testfilen ändrats. **Källstatus**
bevarar tidigare statusnoteringar. Bestridd/inaktuell källa kan inte fortsätta
styrka en verifierad metod; omprövning godkänner inte automatiskt gamla metoder.

## För AI-motorerna

Använd `gg-research workbench OPERATION` med ett JSON-objekt på stdin. Använd
programmets Python (`.venv-windows/Scripts/python.exe` på Windows) vid behov.
Låt strukturerade argument eller en UTF-8-fil bära texten; interpolera inte
hemligheter eller källtext i skalkommandon. `gg-research tools` visar katalogen.

Operationer och argument:

| Operation | JSON-argument |
| --- | --- |
| create_batch | title, links (lista eller inklistrad text, högst 512 länkar) |
| snapshot | batch_id (valfri), task (valfri) |
| control_batch | batch_id, action: resume/pause/cancel |
| claim_source | batch_id |
| renew_source | item_id, lease |
| complete_source | item_id, lease, outcome: READ/BLOCKED/SKIPPED, note, content (krävs vid READ), exit_code (valfri) |
| retry_source | item_id |
| observe | session, source, content, title (valfri), exit_code (valfri) |
| observation | session, observation_id, start/count eller offset/length; query och expected_version är valfria |
| add_requirement | task, title, paths (relativa källfiler), test_module (tests.test_namn) |
| verdict | task |
| record_usage | task, model, outcome: SUCCEEDED/FAILED/CANCELLED, basis: PROVIDER_REPORTED/ESTIMATED/UNKNOWN, input_tokens, output_tokens, cost, currency |
| usage | task |
| source_event | source_id, state: CURRENT/CONTESTED/SUPERSEDED/STALE, note, valid_at/valid_until (valfria ISO-tider med tidszon) |
| preflight_skill | path (lokal skill-mapp), session |

Arbetsgång: skapa/återanvänd en kö, aktivera den, begär en källa, använd de
redan godkända researchverktygen och lämna ett kvitto med konkret
granskningsomfattning. Förnya arbetslåset inom 120 sekunder om granskningen
fortsätter. Sena kvitton efter paus eller utgånget lås avvisas. READ betyder
att det angivna underlaget sparats, inte att varje repo, bild eller kommentar
har fullständigt granskats. Skriv avgränsningen i note. BLOCKED räknas aldrig
som läst. Registrera inte samma källa igen som en ny uppgift för att kringgå
paus eller behörighetsgränser.

Spara stora verktygssvar med observe. Kompakt text behåller exitstatus och
felrader, men är uttryckligen ett utdrag. Använd återläsningsreferensen,
versionskontrollen och rad-/teckenintervall innan du drar en slutsats som
kräver utelämnad text. Teckenintervall kan återställa även en mycket lång rad.
JSON sparas som text; typer, Unicode och exakta värden ändras inte utom vid
maskning. Högst 512 KiB per original, 16 MiB per session och 64 MiB totalt.
Överskriden kvot ger fel; lagret raderar inte äldre bevis i tysthet.
Analyskommandon stöder `--compact-session NAMN` för denna återläsningsväg.
Hela svaret returneras om komprimering inklusive återläsningsreferensen blir
större. Byteantal är ett storleksmått, inte fakturerade token.

Registrera konkreta krav med berörda källfiler och ett lokalt unittest-modulnamn.
Kör sedan `gg-research check REQUIREMENT_ID` explicit inom uppgiftens befintliga
testbehörighet. Körningen använder samma Python, en tidsgräns och begränsad
utdata. Kvittot binder de deklarerade filerna och testfilen före/efter körning.
Inga tester, överhoppade tester, fel, avbrott, ändrade filer och saknat original
ger aldrig PASS. Deklarationen ska omfatta relevanta beroenden; kvittot bevisar
inte beteenden utanför den angivna kontrollen. Verdict är en informationsstatus,
ingen ny behörighetsgrind eller ersättning för befintliga kontrakt.

Användningsjournalen kräver uttrycklig proveniens. Rapporterade leverantörstal
och uppskattningar hålls isär, valutor summeras separat, alla försök inklusive
misslyckade räknas. Saknade siffror betyder okänt, aldrig gratis. Det här lagret
hämtar inga priser och läser inga credentials eller orelaterade chattloggar.

Skill-preflight läser högst 64 textfiler, 64 mappar och 512 KiB. Verktygsbehov,
körbar yta, licensnärvaro och avvikelser redovisas utan att något körs eller
installeras. STATIC_REVIEW är en statisk observation; INCOMPLETE redovisar
utelämnad yta. Ingendera är ett intyg om säkert beteende.
