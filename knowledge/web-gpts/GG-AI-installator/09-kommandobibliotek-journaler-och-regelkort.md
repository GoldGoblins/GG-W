# 09 — Kommandobibliotek, journaler och regelkort

**Version:** 3.1.0  
**Varning:** Exempel är mallar. Kontrollera aktuell systemstatus och officiell syntax före användning.

## Format för läsande förkontroll

```markdown
### Kontroll-ID — namn

**Fas:**  
**Riskklass:** Grön  
**Syfte:**  
**Sudo:**  
**Nätverk:**  
**Ändrar:** Inget

```bash
# komplett läsande block
```

**Skicka tillbaka:**  
**Stoppa om:**  
```

## Format för gul/röd plan

```text
Plan-ID:
Version:
Checkpoint/fas:
Mål:
Riskklass:
Miljö:
Förkontroll-ID:
Källhash:
Code-Gate-profil:
Tillåtna mål:
Förbjudna mål:
Nätverk:
Sudo:
Bestående ändringar:
Temporära ändringar:
Backup:
Rollback:
Verifiering:
Stoppvillkor:
Exakt godkännandefras:
```

## Code Gate-kvitto

```yaml
gate_id:
profile:
profile_version:
created_at:
source:
  path:
  sha256:
  bytes:
  encoding:
language:
interpreter:
checker_versions:
sandbox:
  image:
  digest:
  rootless:
  network:
  readonly_rootfs:
  capabilities:
  no_new_privileges:
  mounts:
  uid_gid:
limits:
  timeout_seconds:
  memory_mb:
  cpus:
  pids:
  max_output_bytes:
fixtures:
checks:
  secret_scan:
  syntax:
  lint:
  static_analysis:
  unit:
  sandbox_runtime:
  negative_network:
  negative_paths:
  cleanup:
artifacts:
status: PASS | CONDITIONAL | FAIL
conditions:
target_environment_tested: false
```

## Säkert kodkörningskvitto

```text
RUN-ID:
Källhash:
Exakt argv:
Arbetskatalog:
Miljövariabelnamn:
Mounts:
Nätverksläge:
UID/GID:
Start:
Slut:
Timeout:
Exitkod:
Signal:
Stdout-hash:
Stderr-hash:
Skapade filer:
Cleanup:
```

Visa inte hemliga miljövariabelvärden.

## Agentregel

```yaml
name:
version:
owner:
purpose:
approved_at:
checkpoint:
project_root:
read_paths:
write_paths:
code_gate_required: true
code_gate_profiles:
allowed_commands:
denied_commands:
allowed_interpreters:
network_allowlist: []
network_denylist:
  - "*"
mount_allowlist:
secret_sources: []
max_files_changed:
max_lines_changed:
max_runtime_seconds:
max_steps:
max_memory_mb:
max_pids:
required_tests:
reviewer_required: true
commit_allowed:
merge_allowed: false
deploy_allowed: false
production_allowed: false
log_path:
handoff_path:
evidence_path:
stop_conditions:
rollback:
manual_kill_switch:
```

## Multiagent-handoff

```yaml
task_id:
created_at:
requester:
assigned_role:
goal:
verified_context:
historical_context:
assumptions:
missing_facts:
risk_class:
allowed_scope:
forbidden_scope:
inputs:
expected_artifacts:
required_code_gate:
required_reviewer:
stop_conditions:
status:
```

## Git-regler

- maskinläs filstatus med NUL-separerad porcelain;
- kontrollera branch, HEAD och parent;
- stagea endast explicit lista;
- verifiera indexlista;
- kör `git diff --check`;
- skapa commit med uppgifts-ID;
- ingen merge, rebase eller deploy utan separat plan.

## Robust Git-statusparser

```python
raw = subprocess.run(
    [
        "git", "-C", str(root),
        "status", "--porcelain=v1", "-z",
        "--untracked-files=all",
    ],
    check=True,
    stdout=subprocess.PIPE,
).stdout

paths = []
for record in raw.split(b"\0"):
    if not record:
        continue
    if len(record) < 4 or record[2:3] != b" ":
        raise RuntimeError("Ogiltig porcelain-post")
    status = record[:2].decode("ascii")
    if "R" in status or "C" in status:
        raise RuntimeError("Rename/copy ingår inte")
    paths.append(
        record[3:].decode("utf-8", errors="surrogateescape")
    )

if len(paths) != len(set(paths)):
    raise RuntimeError("Duplicerade sökvägar")
```

## Robust pipelineprincip

Undvik att läsa `PIPESTATUS` över flera shellkommandon. Spara råutdata och kontrollera varje steg separat:

```bash
command >"$RAW_FILE" 2>"$ERROR_FILE"
COMMAND_RC="$?"

if [ "$COMMAND_RC" -eq 0 ]; then
    python3 parser.py "$RAW_FILE"
    PARSER_RC="$?"
fi
```

## Robust payloadtransport

```bash
cat >"$PAYLOAD_FILE" <<'PAYLOAD'
# exakt payload
PAYLOAD

/bin/sh -n "$PAYLOAD_FILE"
bash --posix -n "$PAYLOAD_FILE"

SOURCE_SHA="$(
    sha256sum "$PAYLOAD_FILE" |
        awk '{ print $1 }'
)"

PAYLOAD_TEXT="$(cat -- "$PAYLOAD_FILE")"
printf '%s' "$PAYLOAD_TEXT" >"$TRANSPORT_FILE"

set -- /bin/sh -ceu "$PAYLOAD_TEXT"
[ "$#" -eq 3 ]
```

## Git-commitmall

```text
[UPPGIFTS-ID] Kort sammanfattning

Varför:
Källhash:
Ändrade filer:
Code Gate:
Tester:
Resultat:
Kända villkor:
Externa effekter:
Rollback:
```

## Checkpointmall

```markdown
# SYSTEMSTATUS — Checkpoint

- Datum:
- Checkpoint:
- Föregående checkpoint:
- Verifierad status:
- Användarbeslut:
- Historisk status:
- Ändringar:
- Code Gate:
- Tester:
- Avvikelser:
- Backup:
- Rollback:
- Säkerhet:
- Öppna risker:
- Nästa exakta steg:
- SHA-256:
```

## Dry-run-princip

1. lista mål;
2. lås källhash;
3. kör dry-run;
4. granska oväntade träffar;
5. kör Code Gate;
6. begär rätt godkännande;
7. kör samma avgränsning;
8. verifiera mål;
9. dokumentera rollback.

Dry-run och Code Gate ersätter inte backup eller målmiljötest.


## Exakt Podman inspect-kontrakt

```python
def normalize_inspect(value):
    if isinstance(value, dict):
        return value
    if (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
    ):
        return value[0]
    raise RuntimeError("oväntad inspectstruktur")
```

Validera exakta JSON-paths. Använd inte rekursiv global sökning efter generiska värden.

För den låsta CP5C-profilen verifierades:

```text
HostConfig.CapAdd=[]
HostConfig.CapDrop=EXAKT_LÅST_EXPANDERAD_MÄNGD
HostConfig.Privileged=false
HostConfig.ReadonlyRootfs=true
HostConfig.SecurityOpt innehåller no-new-privileges
HostConfig.NetworkMode=none
HostConfig.UsernsMode=private
Config.User=1000:1000
NetworkSettings.Networks keys=["none"]
```

## Kopiering med exakt mode under umask

```python
def copy_new(source: pathlib.Path, destination: pathlib.Path) -> None:
    source_mode = stat.S_IMODE(source.stat().st_mode)
    data = source.read_bytes()

    fd = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        source_mode,
    )

    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())

    # os.open påverkas av umask. Återställ kontrakterat mode.
    os.chmod(destination, source_mode)

    if hashlib.sha256(data).hexdigest() != sha256_file(destination):
        raise RuntimeError("kopieringshash skiljer")
```

Kontrollera både innehållsfingerprint och full trädfingerprint.

## Amendmentmall

```text
AMENDMENT_ID:
BASPLAN:
ORSAK_TILL_STOPP:
FAKTISK_DELSTATUS:
LÅST_EVIDENS:
ÄNDRAD_PLANDEL:
OFÖRÄNDRADE_GRÄNSER:
NY_KOD_SOM_KRÄVER_CODE_GATE:
TILLÅTEN_EXTRA_GATE_COUNT:
FÖRBJUDNA_OMKÖRNINGAR:
ROLLBACK:
STOPPVILLKOR:
EXAKT_GODKÄNNANDEFRAS:
```

## Resume-regler

- återanvänd inte tidigare controller för ny exekvering;
- radera inte stoppad evidensrot;
- skapa separat amendmentrot;
- verifiera tidigare controller-, report- och inspect-hashar;
- verifiera Git och status före skrivning;
- kör endast den nya controllern genom Code Gate;
- räkna totalt antal Gate-körningar;
- förbjud automatisk rerun;
- bevara Git-refs och evidens vid stopp;
- slutverifiera effekten separat.
