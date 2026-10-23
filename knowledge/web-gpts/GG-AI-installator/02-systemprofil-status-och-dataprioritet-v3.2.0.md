# 02 — Systemprofil, status och dataprioritet

**Version:** 3.2.0  
**Datum:** 2026-08-07  
**Dokumenttyp:** rekonstruerad, källmärkt ersättningsfil  
**Status:** aktuell styrfil för informationskvalitet  
**Originalstatus:** den borttagna originalfilens byteinnehåll och SHA-256 är inte tillgängliga. Denna fil är därför inte en återställning av originaltexten utan en ny, spårbar ersättningsversion.

## 1. Syfte

Den här filen styr hur GG AI istallatör ska:

- skilja aktuell verifierad status från historik;
- ange källa för maskinspecifika uppgifter;
- markera användarbeslut, policy och saknade fakta;
- prioritera motstridiga uppgifter;
- undvika att gamla checkpoints används som aktuell systemstatus;
- återuppta arbete säkert i en ny session.

Filen ger inte i sig rätt att ändra datorn.

## 2. Obligatoriska informationsetiketter

Varje uppgift som kan påverka en plan ska klassificeras med någon av följande etiketter.

### `VERIFIERAD`

Styrkt med faktisk lokal utdata från den berörda datorn.

Format:

```text
[VERIFIERAD YYYY-MM-DD | KÄLLA Sx]
```

En verifierad uppgift är aktuell endast vid den angivna kontrolltidpunkten. Den kan behöva verifieras på nytt om den är dynamisk.

### `HISTORISK`

Tidigare verifierad eller dokumenterad status som inte har kontrollerats i den aktuella fasen.

Format:

```text
[HISTORISK | KÄLLA Sx]
```

### `ANVÄNDARBESLUT`

Uttryckligen beslutad riktning, scope eller regel. Ett beslut bevisar inte att åtgärden är genomförd.

### `POLICY`

Normativ regel som styr hur arbetet ska utföras. Policy är inte en observation om datorns aktuella skick.

### `SAKNAD`

En uppgift som behövs för en plan men ännu inte är verifierad.

### `MOTSAGD`

Aktuell utdata strider mot en äldre checkpoint, plan eller antagande.

### `ANTAGEN`

Får användas endast tillfälligt i resonemang. En antagen uppgift får inte ligga till grund för gul eller röd exekvering.

## 3. Källregister

### S1 — CP5C slutpublicering

Faktisk terminalutdata från:

`GG-CP5C-FINAL-PUBLICATION-PLAN-v1.0-AMENDMENT-C`

Tidpunkt i chatten: 2026-07-31 15:22 svensk sommartid.

Utdata verifierade bland annat Git-commit, publicerade filer, statusfiler, Code Gate-resultat och tom Podman-runtime.

### S2 — CP6A läsande design- och systemförkontroll

Faktisk terminalutdata från:

`GG-CP6A-READ-ONLY-DESIGN-SYSTEM-PRECHECK-v1.0`

Tidpunkt i chatten: 2026-07-31 15:25 svensk sommartid.

Utdata verifierade bland annat Fedora-, kernel-, säkerhets-, hårdvaru-, verktygs-, runtime- och modellkatalogstatus.

### S3 — Tidigare verifierad systemprofil och checkpoints

Historisk projektstatus som bland annat anger KDE-miljö samt att CP1–CP3 tidigare slutförts.

S3 ska inte ersätta ny lokal kontroll.

### S4 — Uttryckliga användarbeslut i chatten

Omfattar bland annat:

- reviderad checkpointordning;
- obligatorisk Idékompassen 2.0;
- planerade specialistroller;
- krav på versionsmärkt delad kunskap;
- förbud mot självutökade rättigheter.

### S5 — Historisk operativ kunskapsbas v1.3

Sekundär sammanställning skapad från S1–S4. S5 är historisk efter CP6A-slutförandet och är inte högre auktoritet än senare lokal utdata.

### S5B — Aktiv operativ kunskapsbas v1.5

`GG-AI-KUNSKAP-AKTUELL-2026-08-07-v1.5.md` sammanfattar CP6A-slutläget och CP6B-planeringsberedskapen. Den är sekundär till faktisk lokal utdata.

### S6 — CP6A slutverifiering och lokal promotion 2026-08-07

Faktisk terminalutdata verifierade CP6A Phase 2 `PASS`, oberoende kandidatgranskning `PASS` och lokal `--ff-only` promotion till `main`.

Verifierad Git-HEAD efter promotion:

`1144492f17df1c749f734175c6a1e4742ff95a41`

### S7 — CP6B scope discovery och contract inventory 2026-08-07

Faktisk läsande terminalutdata verifierade CP6B:s scope, rollregister, handoffschema, Idékompassen-kontrakt, agentmanifest, agentregel och task/proposal-scheman. Ingen CP6B-build eller skrivning genomfördes.

## 4. Informationsprioritet

Vid konflikt gäller:

1. aktuell lokal systemutdata;
2. aktuell verifierad `SYSTEMSTATUS.md`;
3. aktuell officiell dokumentation för versionskänsliga fakta;
4. uttryckligt användarbeslut;
5. denna källmärkta kunskapsfil;
6. historiska checkpoints;
7. generell vägledning.

När två primärkällor motsäger varandra ska den senare, relevanta och korrekt avgränsade kontrollen normalt ha företräde. Motsägelsen ska dokumenteras.

## 5. Senast verifierad systemprofil — 2026-07-31

Dessa maskinfakta ska behandlas som daterad verifiering. De är inte nykontrollerade enbart för att dokumentet uppdaterades 2026-08-07.

Uppgifterna nedan var verifierade vid S2. De är inte permanenta identiteter.

| Uppgift | Värde | Klassificering |
|---|---|---|
| Fedora-version | 44 | `[VERIFIERAD 2026-07-31 | S2]` |
| Kernel | `7.1.5-200.fc44.x86_64` | `[VERIFIERAD 2026-07-31 | S2]` |
| Skrivbordsmiljö | KDE | `[HISTORISK | S3]` |
| SELinux | `Enforcing` | `[VERIFIERAD 2026-07-31 | S2]` |
| firewalld | `active` | `[VERIFIERAD 2026-07-31 | S2]` |
| Secure Boot | `disabled` | `[VERIFIERAD 2026-07-31 | S2]` |
| Lokal användare | `GG` | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| UID/GID | `1000:1000` | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| CPU | Intel Core i7-9750H | `[VERIFIERAD 2026-07-31 | S2]` |
| RAM | `16206028 kB` | `[VERIFIERAD 2026-07-31 | S2]` |
| Integrerad GPU | Intel UHD Graphics 630 | `[VERIFIERAD 2026-07-31 | S2]` |
| Diskret GPU | NVIDIA GTX 1660 Ti Mobile | `[VERIFIERAD 2026-07-31 | S2]` |
| Rootfilsystem totalt | `66776465408` byte | `[VERIFIERAD 2026-07-31 | S2]` |
| Rootfilsystem ledigt | `49815851008` byte | `[VERIFIERAD 2026-07-31 | S2]` |

### Tolkning

- Fedora 44 är aktuellt verifierad.
- KDE är historiskt verifierad men kontrollerades inte separat i S2.
- Secure Boot-status kan ändras och ska verifieras på nytt före boot- eller signeringsarbete.
- GPU-namn bevisar inte vilken GPU, drivrutin eller rendernod som används av en viss container.

## 6. Senast verifierad verktygs- och containermiljö — 2026-07-31

Verktygsversionerna nedan är senaste dokumenterade 2026-07-31-värden om inte en senare källa uttryckligen anges.

| Komponent | Värde | Klassificering |
|---|---|---|
| Python | `3.14.6` | `[VERIFIERAD 2026-07-31 | S2]` |
| Git | `2.55.0` | `[VERIFIERAD 2026-07-31 | S2]` |
| Podman | `5.8.4` | `[VERIFIERAD 2026-07-31 | S2]` |
| crun | `1.28` | `[VERIFIERAD 2026-07-31 | S2]` |
| jq | `1.8.1` | `[VERIFIERAD 2026-07-31 | S2]` |
| yq | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| Node | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| npm | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| Podman-containrar | 0 efter kontroll | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| Podman-volymer | 0 efter kontroll | `[VERIFIERAD 2026-07-31 | S2]` |
| Icke-standardnätverk | 0 efter kontroll | `[VERIFIERAD 2026-07-31 | S2]` |

`Podman runtime tom` betyder endast att inga objekt hittades vid den kontrollen. Det betyder inte att Podman inte är installerat eller att images saknas.

## 7. Git- och checkpointstatus

### Aktuell verifierad Git-status

| Uppgift | Värde | Klassificering |
|---|---|---|
| Repository | `/home/GG/GoldGoblins` | `[VERIFIERAD 2026-08-07 | S6]` |
| Branch | `main` | `[VERIFIERAD 2026-08-07 | S6]` |
| HEAD | `1144492f17df1c749f734175c6a1e4742ff95a41` | `[VERIFIERAD 2026-08-07 | S6]` |
| Git-status | ren | `[VERIFIERAD 2026-08-07 | S6]` |
| Git-remotes | 0 | `[VERIFIERAD 2026-08-07 | S6]` |
| Promotion | fast-forward only | `[VERIFIERAD 2026-08-07 | S6]` |

### Checkpoints

| Checkpoint | Status | Klassificering |
|---|---|---|
| CP1 | klar vid tidigare checkpoint | `[HISTORISK | S3]` |
| CP2 | klar vid tidigare checkpoint | `[HISTORISK | S3]` |
| CP3 | klar vid tidigare checkpoint | `[HISTORISK | S3]` |
| CP5A | verifierad klar | `[HISTORISK/VERIFIERAD PROJEKTSTATUS | S3, S5]` |
| CP5B | verifierad klar i 4096-scope | `[HISTORISK/VERIFIERAD PROJEKTSTATUS | S3, S5]` |
| CP5C | `PASS_PUBLISHED` | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| CP6A | `PASS` + independent audit `PASS` + local promotion `PASS` | `[VERIFIERAD 2026-08-07 | S6]` |
| CP6B discovery | `PASS_READ_ONLY` | `[VERIFIERAD 2026-08-07 | S7]` |
| CP6B build | ej påbörjad | `[VERIFIERAD 2026-08-07 | S7]` |
| CP4 | väntar på CP6B | `[ANVÄNDARBESLUT/PROJEKTSTATUS | S4, S7]` |
| CP6C | ej påbörjad | `[PROJEKTSTATUS | S7]` |

## 8. Lokal AI-status

| Uppgift | Värde | Klassificering |
|---|---|---|
| Runtimeimage | `localhost/gg-llama-cpp-vulkan:b10182` | `[VERIFIERAD 2026-07-31 | S2]` |
| Image-ID | `0a4db391fe04f0a5370ccc04bf2b9c3960180e569092a1e51a48d30ab425d178` | `[VERIFIERAD 2026-07-31 | S2]` |
| Image digest | `sha256:61f81360fdf2d10c069cf183d1a8671f19977015d8fd42ef9868654c44697e44` | `[VERIFIERAD 2026-07-31 | S2]` |
| Modellrot | `/home/GG/models` | `[VERIFIERAD 2026-07-31 | S2]` |
| Inventerad storlek | `2889514341` byte | `[VERIFIERAD 2026-07-31 | S2]` |
| `ollama` host-CLI | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| `llama-server` host-CLI | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| `llama-cli` host-CLI | saknas | `[VERIFIERAD 2026-07-31 | S2]` |
| Relevanta lyssnande AI-portar | inga hittade | `[VERIFIERAD 2026-07-31 | S2]` |

Korrekt klassificering:

```text
CONTAINER_IMAGE_PRESENT_HOST_CLI_ABSENT
```

Efter CP6A-slutverifieringen är följande inte längre saknat:

- modellfil: `/home/GG/models/qwen3-4b-q5_k_m/Qwen3-4B-Q5_K_M.gguf`;
- modell-SHA-256: `aca596860e8cb40af6539e3f2ea40df305f42515deac56d49c08d39a02e6533f`;
- runtimeimage: `localhost/gg-llama-cpp-vulkan:b10182`;
- rendernod: `/dev/dri/renderD129`;
- agentkärna: lokalt installerad/promotad genom CP6A;
- CP6B-routing: fortfarande avstängd i CP6A-agentregeln.

Dessa är verifierade för CP6A-slutkörningen men dynamiska systemdetaljer ska fortfarande riktat nyverifieras före en ny gul/röd plan.

## 9. Uppgifter som inte är verifierade

Följande ska inte antas från denna fil:

- aktuell IP-adress;
- aktuella lyssnande portar efter S2;
- aktuellt bootnummer;
- aktuell UEFI-bootordning;
- TPM-status;
- LUKS-layout;
- blockenhetsnamn;
- EFI-systempartition;
- aktiv GPU-drivrutin eller rendernod;
- aktuell fullbackup;
- backupens restorebarhet;
- att Knowledge-filer finns lokalt på Fedora;
- att CP6B-orchestratorn finns.

Alla dessa är `[SAKNAD]` tills aktuell lokal utdata bevisar annat.

## 10. Dynamiska identiteter

Följande får aldrig behandlas som permanenta utan ny kontroll:

- IP-adresser;
- portar;
- process-ID;
- container-ID;
- bootnummer;
- `/dev`-namn;
- rendernoder;
- LUKS-mappernamn;
- tillfälliga kataloger;
- Git HEAD och branch;
- image-ID och digest;
- modellfil och hash.

Föredra stabila identiteter som:

- SHA-256;
- Git-commit;
- UUID;
- versionsmärkt evidens;
- exakt absolut path kombinerad med hash.

## 11. Dataklasser

### `[POLICY]` Offentlig data

Officiell dokumentation, generiska fixtures och offentlig källkod utan hemligheter.

### `[POLICY]` Intern data

Projektstruktur, sanerad systemstatus, syntetiska testresultat och interna beslut.

### `[POLICY]` Känslig data

Detaljerad systeminventering, personuppgifter, privata loggar och kundfria databaskopior. Kräver minimering och tydligt syfte.

### `[POLICY]` Hemlig eller produktionsdata

Lösenord, API-nycklar, cookies, SSH-nycklar, `.env`, databascredentials, kunddata och betalningsdata.

Sådan data ska normalt inte läggas i:

- Git;
- GPT Knowledge;
- promptar;
- images;
- testfixtures;
- vanliga loggar;
- screenshots.

## 12. Systemstatus som checkpoint

`[POLICY]` En aktuell `SYSTEMSTATUS.md` ska minst innehålla:

- datum och tidszon;
- dokumentversion;
- verifierad Git-status;
- verifierad system- och runtimeprofil;
- genomförda förändringar;
- tester och bevis;
- öppna risker;
- användarbeslut;
- stoppade eller partiella körningar;
- nästa exakta steg;
- relevanta SHA-256 och commits.

Historiska statusfiler ska inte skrivas om för att passa en ny roadmap.

## 13. ChatGPT Knowledge och lokal Fedora

`[POLICY]` En fil uppladdad till GPT Knowledge är inte automatiskt installerad på Fedora.

Använd en av dessa statusar:

- `CHATGPT_KNOWLEDGE_PRESENT`;
- `LOCAL_FILE_PRESENT`;
- `BOTH_PRESENT_AND_HASH_MATCHED`;
- `PRESENCE_NOT_PROVEN`.

I S2 hittades endast ett av femton efterfrågade kunskapsnamn lokalt. Det bevisar inte att övriga uppladdade filer fanns på Fedora.

## 14. Stoppregler

Stoppa berörd del när:

- aktuell utdata motsäger planens baslinje;
- två påstått identiska filer har olika hash;
- användare, branch, commit, image eller destination är tvetydig;
- historisk status används som aktuell utan ny kontroll;
- en hemlighet riskerar att visas eller loggas;
- lokal filnärvaro antas från GPT Knowledge;
- CP5C föreslås köras om trots oförändrad låst evidens;
- CP6B-build eller rättighetsutökning behandlas som godkänd utan separat plan;
- en `[SAKNAD]` uppgift krävs för säker exekvering.

## 15. Sessionsåterupptagning

Vid ny session:

1. läs aktuell operativ kunskapsbas;
2. läs senaste verifierade `SYSTEMSTATUS.md`;
3. kontrollera endast dynamiska fakta som behövs för uppgiften;
4. märk varje sakuppgift med rätt klassificering;
5. skilj GPT Knowledge från lokal filnärvaro;
6. verifiera Git före Git-plan;
7. verifiera Podman före containerplan;
8. dokumentera verifierat, historiskt, saknat och beslut;
9. begär separat godkännande före gul eller röd exekvering.
