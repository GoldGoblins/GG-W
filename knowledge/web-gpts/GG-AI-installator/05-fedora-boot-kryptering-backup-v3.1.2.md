# 05 — Fedora, boot, kryptering och backup

**Version:** 3.1.2  
**Datum:** 2026-07-31  
**Dokumenttyp:** rekonstruerad, källmärkt ersättningsfil  
**Status:** säkerhetskritisk policy- och förkontrollfil  
**Originalstatus:** den borttagna originalfilens byteinnehåll och SHA-256 är inte tillgängliga. Denna fil är en ny, spårbar ersättningsversion och inte en exakt kopia av originalet.

## 1. Syfte

Filen styr arbete med:

- Fedora-systemets basfunktion;
- boot och UEFI;
- Secure Boot och TPM;
- LUKS, blockenheter och kryptering;
- SELinux och firewalld;
- backup, restore och rollback;
- skydd av historiska checkpoints och evidens.

Maskinspecifika uppgifter märks med källa. Säkerhetsregler märks som policy. Okända uppgifter märks som saknade.

## 2. Etiketter

- `[VERIFIERAD YYYY-MM-DD | Sx]` — faktisk lokal utdata.
- `[HISTORISK | Sx]` — tidigare status, inte nykontrollerad.
- `[ANVÄNDARBESLUT | Sx]` — beslutad riktning eller gräns.
- `[POLICY]` — regel, inte maskinobservation.
- `[SAKNAD]` — ännu inte verifierat.
- `[MOTSAGD]` — ny utdata strider mot äldre uppgift.

## 3. Källregister

### S1 — CP5C slutpublicering

Faktisk terminalutdata 2026-07-31 som verifierade Git-, status-, publicerings- och runtimeutfall.

### S2 — CP6A läsande systemförkontroll

Faktisk terminalutdata 2026-07-31 som verifierade Fedora, kernel, SELinux, firewalld, Secure Boot, CPU, minne, GPU och rootfilsystem.

### S3 — Historiska CP1–CP3-checkpoints

Tidigare dokumenterad projektstatus. Den bevisar inte att boot, LUKS eller en gammal backup fortfarande är oförändrad.

### S4 — Projektets riskmodell och användarbeslut

Normativa regler om röd risk, backup, rollback, minsta behörighet och stoppvillkor.

## 4. Senast verifierad Fedora- och säkerhetsbaslinje — 2026-07-31

Ingen av dessa dynamiska uppgifter blir automatiskt aktuell genom denna Knowledge-uppdatering. Röd boot/LUKS/SELinux/firewall-plan kräver ny riktad verifiering.

| Uppgift | Värde | Klassificering |
|---|---|---|
| Fedora-version | 44 | `[VERIFIERAD 2026-07-31 | S2]` |
| Kernel | `7.1.5-200.fc44.x86_64` | `[VERIFIERAD 2026-07-31 | S2]` |
| Skrivbordsmiljö | KDE | `[HISTORISK | S3]` |
| SELinux | `Enforcing` | `[VERIFIERAD 2026-07-31 | S2]` |
| firewalld | `active` | `[VERIFIERAD 2026-07-31 | S2]` |
| Secure Boot | `disabled` | `[VERIFIERAD 2026-07-31 | S2]` |
| Användare | `GG` | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| UID/GID | `1000:1000` | `[VERIFIERAD 2026-07-31 | S1, S2]` |
| Rootfilsystem totalt | `66776465408` byte | `[VERIFIERAD 2026-07-31 | S2]` |
| Rootfilsystem ledigt | `49815851008` byte | `[VERIFIERAD 2026-07-31 | S2]` |

### Viktig avgränsning

- `Secure Boot disabled` var sant vid S2. Kontrollera igen före varje boot- eller signeringsplan.
- `SELinux Enforcing` och `firewalld active` är verifierad status, inte ett godkännande att ändra dem.
- Fedora 44 bevisar inte aktuell bootloader-, initramfs-, TPM- eller LUKS-konfiguration.
- KDE är historiskt dokumenterad men inte separat kontrollerad i S2.

## 5. Historisk checkpointstatus

| Checkpoint | Status | Klassificering |
|---|---|---|
| CP1 systembaslinje | klar vid tidigare checkpoint | `[HISTORISK | S3]` |
| CP2 backup och restore | klar vid tidigare checkpoint | `[HISTORISK | S3]` |
| CP3 säker utvecklingsgrund | klar vid tidigare checkpoint | `[HISTORISK | S3]` |

`CP2 klar` betyder inte att en aktuell backup har verifierats den 31 juli 2026. En historisk restoreövning kan inte användas som bevis för en senare backupfil.

## 6. Saknade maskinspecifika fakta

Följande är inte verifierade i S1 eller S2:

| Område | Status |
|---|---|
| UEFI-bootordning | `[SAKNAD]` |
| Aktiv bootloader och exakt konfiguration | `[SAKNAD]` |
| EFI-systempartitionens path, UUID och innehåll | `[SAKNAD]` |
| TPM-närvaro och status | `[SAKNAD]` |
| LUKS-enheter och UUID | `[SAKNAD]` |
| LUKS-mappernamn | `[SAKNAD]` |
| LUKS-keyslots | `[SAKNAD]` |
| Recovery key eller separat upplåsningsväg | `[SAKNAD]` |
| LUKS-headerbackup | `[SAKNAD]` |
| Aktuell initramfsstatus | `[SAKNAD]` |
| Aktuell fullbackup | `[SAKNAD]` |
| Backupdestination | `[SAKNAD]` |
| Backupens SHA-256 | `[SAKNAD]` |
| Senaste lyckade restoretest | `[SAKNAD]` |
| Externa diskars aktuella anslutning | `[SAKNAD]` |

Ingen av dessa uppgifter får fyllas i från minne eller antagande.

## 7. Riskklassificering

### `[POLICY]` Normalt rött

- ändring av UEFI-poster;
- skrivning till EFI-systempartition;
- ändring av Secure Boot;
- registrering eller radering av signeringsnycklar;
- ändring av TPM-binding;
- ändring av LUKS-header eller keyslots;
- omkryptering;
- destruktiva blockenhetskommandon;
- SELinux-policyändring;
- permanent brandväggsändring som påverkar exponering;
- privilegierad systemtjänst;
- overwrite-restore;
- radering av backup eller evidens;
- produktion eller kunddata.

### `[POLICY]` Normalt gult

- skapa ny användarägd backup till verifierad destination;
- skapa versionsmärkt recoverydokumentation;
- återställning i avtalad tom sandbox;
- användarkonfiguration som är tydligt återställningsbar.

### `[POLICY]` Normalt grönt

- läsande inventering;
- statisk kontroll;
- checksummeverifiering;
- backupkatalogens fil- och modeinventering;
- dokumentation utan systemändring.

Högsta riskklass i planen gäller.

## 8. Obligatorisk förkontroll före röd plan

`[POLICY]` Förkontrollen ska identifiera:

1. aktuell användare och hostname;
2. Fedora- och kernelversion;
3. bootmetod;
4. Secure Boot-status;
5. TPM-status om relevant;
6. monterade filsystem;
7. blockenheter, filsystem, storlek, modell och UUID;
8. eventuell LUKS-layout;
9. EFI-systempartition;
10. root- och bootmount;
11. ledigt utrymme;
12. exakt backupkälla;
13. exakt backupdestination;
14. backupens hash, storlek, ägare och mode;
15. restoremetod;
16. rollbackmål;
17. om extern disk är ansluten;
18. om produktion eller tredje part kan påverkas.

Förkontrollen ska vara läsande och sanerad.

## 9. Målidentifiering

`[POLICY]` Före skrivning till blockenhet eller restore krävs minst två oberoende identiteter, exempelvis:

- UUID;
- serienummer;
- modell och storlek;
- mountpunkt;
- filsystem;
- förväntad SHA-256;
- uttryckligt verifierad destination.

Ett flyktigt namn som `/dev/sda`, `/dev/nvme0n1` eller `/dev/mapper/...` räcker inte ensamt.

## 10. Boot och UEFI

### `[POLICY]` Regler

- Läs aktuell bootstatus före plan.
- Skapa inte nya UEFI-poster utan tydligt behov.
- Radera inte fungerande bootpost utan verifierad recoveryväg.
- Skriv inte direkt i EFI-systempartitionen utan röd plan.
- Ändra inte initramfs eller bootloader utan verifierad kernel och rollback.
- Ett lyckat kommando bevisar inte att nästa boot fungerar.
- Bootrelaterad ändring kräver separat rebootkontroll.
- Secure Boot ska verifieras på nytt efter relevant förändring.

### `[SAKNAD]` För denna dator

Aktuell bootloader, UEFI-postlista och EFI-systempartition är inte fastställda i denna fil.

## 11. LUKS och kryptering

### `[POLICY]` Regler

- LUKS-header och keyslots är kritiska.
- Ta inte bort en keyslot innan en annan upplåsningsväg har testats.
- Säkerhetskopiera LUKS-header före relevant ändring.
- Lägg aldrig lösenfras, recovery key eller headerbackup i Git, Knowledge, prompt eller vanlig logg.
- Ändra inte cipher, PBKDF, keyslot eller reencrypt-layout utan separat röd plan.
- Kör aldrig destruktivt kommando mot en enhet som bara identifierats med `/dev`-namn.
- Efter ändring krävs separat upplåsnings- och bootverifiering.

### `[SAKNAD]` För denna dator

Det finns ingen verifierad uppgift i S1–S2 om huruvida root, home eller annan volym använder LUKS, vilka UUID:n som gäller eller hur många keyslots som finns.

## 12. SELinux

### Verifierad status

`SELinux=Enforcing` `[VERIFIERAD 2026-07-31 | S2]`

### `[POLICY]` Regler

- Stäng inte av SELinux för att få en tjänst att fungera.
- Använd inte permanent permissive som genväg.
- Samla representativ AVC-utdata och identifiera rotorsaken.
- Skapa minsta möjliga policy endast efter separat röd plan.
- Verifiera att ändringen inte ger bredare rättigheter än avtalat.
- Agenten får inte ändra sin egen säkerhetspolicy.

## 13. firewalld

### Verifierad status

`firewalld=active` `[VERIFIERAD 2026-07-31 | S2]`

### `[POLICY]` Regler

- Öppna inte bred port eller zon utan exponeringsanalys.
- Bind lokala testtjänster till loopback när det räcker.
- Kontrollera aktuell zon, interface och befintliga regler före plan.
- Permanent brandväggsändring är röd.
- Efter ändring ska både lokal funktion och extern exponering verifieras.

## 14. Backupklasser

### `[POLICY]` Konfigurationsbackup

Krav:

- exakt fillista;
- inga hemligheter;
- SHA-256;
- ägare och mode;
- separat restoretest.

### `[POLICY]` Projektbackup

Omfattar Git-repository, dokumentation och syntetiska data. En Git-commit är inte ensam en full backup om externa eller ospårade artefakter saknas.

### `[POLICY]` Databas- och applikationsbackup

Kräver konsistent export eller dokumenterad snapshot. Kund- och produktionsdata är rött.

### `[POLICY]` System- och recoverybackup

Ska täcka den felmodell som anges: diskfel, bootfel, krypteringsfel, felaktig konfiguration eller användarfel.

## 15. När backup är bevisad

`[POLICY]` Backup får märkas `VERIFIERAD` först när följande är kontrollerat:

- källscope;
- destination;
- fri kapacitet;
- slutförd skrivning;
- filstorlek;
- SHA-256 eller motsvarande integritetsbevis;
- ägare och mode;
- läsbarhet;
- dokumenterad restoreprocedur;
- representativ restoretest;
- datum och ansvarig.

Annars använd exempelvis:

```text
BACKUP_PRESENT_RESTORE_NOT_PROVEN
```

## 16. Snapshot och backup

`[POLICY]` En snapshot på samma fysiska disk skyddar inte mot alla fel, exempelvis:

- diskhaveri;
- förlust av hela enheten;
- destruktiv partitionering;
- vissa krypteringsfel;
- vissa ransomware- eller användarfel.

Beskriv alltid vilken felmodell backupen faktiskt täcker.

## 17. Restore

### `[POLICY]` Regler

- Restore är en separat plan.
- Dry-run eller katalogjämförelse först när möjligt.
- Restore till ny, tom eller avtalad sandbox föredras.
- Overwrite-restore är rött.
- Bevara originalet tills den återställda kopian verifierats.
- Verifiera path, filantal, hash, mode, ägare och funktion.
- Databasrestore ska testas isolerat före produktion.
- Efter misslyckad restore får ingen automatisk omkörning ske.

## 18. Rollback

`[POLICY]` En giltig rollback ska ange:

- exakt trigger;
- vilka filer, refs, mounts eller inställningar som återställs;
- vilken verifierad backup som används;
- möjlig dataförlust;
- hur rollback verifieras;
- när automatisk rollback är förbjuden.

Efter ändring av `main`, boot, kryptering eller produktion kan automatisk destruktiv rollback vara farligare än stopp och manuell analys.

## 19. Skydd av checkpoints och evidens

`[POLICY]` Följande ska inte raderas eller skrivas om utan separat inventering och godkänd retentionplan:

- CP1–CP3-statusfiler;
- historisk CP3-kunskapsfil;
- CP5B- och CP5C-evidens;
- CP5C-publiceringsrötter;
- staging och rapporter;
- Git-backuprefs;
- checksummefiler;
- stoppade amendmentrötter.

## 20. WordPress och kunddata

`[POLICY]`

- one.com-inloggning och produktionsexport är röda;
- full produktionsdatabas ska normalt inte laddas upp till ChatGPT;
- kunddata och hemligheter ska saneras före lokal testmiljö;
- export, backup, sanering och import är separata steg;
- agenten får inte självständigt logga in eller hämta produktionsdata.

## 21. Stoppvillkor

Stoppa när:

- blockenhet eller destination är tvetydig;
- aktuell backup saknas;
- restorekällan inte kan verifieras;
- recoveryväg saknas;
- oväntad root eller sudo krävs;
- planen påverkar boot mer än godkänt;
- Secure Boot-, TPM- eller LUKS-status motsäger planen;
- en hemlighet riskerar att visas;
- utrymmet inte räcker;
- hash, filantal eller mode skiljer;
- extern disk eller mount försvinner;
- produktion eller tredje part kan påverkas;
- rollback blir större eller mer destruktiv än godkänt;
- någon `[SAKNAD]` uppgift krävs för nästa skrivande steg.

## 22. Arbetsflöde

Vid arbete med Fedora, boot, kryptering eller backup:

1. läs aktuell systemstatus;
2. markera CP1–CP3 som historiska;
3. samla riktad läsande förkontroll;
4. identifiera exakta mål;
5. klassificera högsta risk;
6. verifiera backup och restoreväg;
7. formulera namngiven plan;
8. begär exakt godkännande;
9. genomför ett atomiskt steg;
10. verifiera effekten separat;
11. uppdatera `SYSTEMSTATUS.md`;
12. dokumentera avvikelse, risk och nästa steg.
