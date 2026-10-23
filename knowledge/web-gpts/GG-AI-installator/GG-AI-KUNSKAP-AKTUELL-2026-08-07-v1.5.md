# GG AI installatör — aktuell operativ kunskapsbas

- **Dokument-ID:** `GG-AI-KUNSKAP-AKTUELL-2026-08-07-v1.5`
- **Version:** 1.5
- **Datum:** 2026-08-07
- **Pauspunkt:** CP6A verifierat slutförd och lokalt promotad; CP6B scope discovery + contract inventory PASS_READ_ONLY; CP6B build ej påbörjad
- **Ersätter aktivt:** `GG-AI-KUNSKAP-AKTUELL-2026-08-07-v1.4`
- **Auktoritet:** aktuell lokal terminalutdata har alltid företräde

## Aktuell status

| Del | Status |
|---|---|
| CP1–CP3 | HISTORISKT KLARA |
| CP5A | VERIFIERAD KLAR |
| CP5B | VERIFIERAD KLAR I 4096-SCOPE |
| CP5C | PASS_PUBLISHED |
| CP6A | VERIFIERAD PASS + LOKALT PROMOTAD |
| CP6B scope discovery | PASS_READ_ONLY |
| CP6B contract inventory | PASS_READ_ONLY |
| CP6B build | EJ PÅBÖRJAD |
| CP4 | BLOCKERAD AV CP6B |
| CP6C | EJ PÅBÖRJAD |

## Git

```text
Repository=/home/GG/GoldGoblins
Branch=main
HEAD=1144492f17df1c749f734175c6a1e4742ff95a41
Clean=YES
Remotes=NONE
```

Promotion från CP5C-baslinjen `9cee2ad703cd516fc16746d8ad571ac30e6c0d3f` var FAST_FORWARD_ONLY. Ingen merge-commit, push eller extern publicering.

## CP6A slutbevis

```text
FINAL_RECEIPT_STATUS=PASS
FINAL_RECEIPT_SHA256=ed985140f385adfdbea87877b53223389899859733c87c20c166840aae95566a
BUILD_RESULT_STATUS=PASS
BUILD_RESULT_SHA256=53f90d2dcbbba07a08479fac315b1407ac53f0f4428123ee90f4ad7ff90525c6
GENERATED_GATE_REPORT_SHA256=314b9a33f7be0407212c8b938d3727ed55319dd5463442cf7662a3edcfc7475c
CANDIDATE_COMMIT=1144492f17df1c749f734175c6a1e4742ff95a41
SYNTHETIC_COMMIT=6249f5c5564628bd1eccc5709c1f68f698f63fd3
CANDIDATE_COMMIT_COUNT=1
SYNTHETIC_COMMIT_COUNT=1
TOTAL_CODE_GATE_EXECUTION_COUNT=19
GENERATED_FILE_CODE_GATE_COUNT=1
RUNTIME_CONTAINER_START_COUNT=2
MODEL_INFERENCE_COUNT=1
DEBUG_RUNNER_EXECUTION_COUNT=0
NETWORK_USED=NO
INDEPENDENT_CANDIDATE_AUDIT_V3=PASS
LOCAL_PROMOTION=PASS
```

## Runtime/modell

```text
MODEL_PATH=/home/GG/models/qwen3-4b-q5_k_m/Qwen3-4B-Q5_K_M.gguf
MODEL_SHA256=aca596860e8cb40af6539e3f2ea40df305f42515deac56d49c08d39a02e6533f
IMAGE_REF=localhost/gg-llama-cpp-vulkan:b10182
IMAGE_ID=0a4db391fe04f0a5370ccc04bf2b9c3960180e569092a1e51a48d30ab425d178
IMAGE_DIGEST=sha256:61f81360fdf2d10c069cf183d1a8671f19977015d8fd42ef9868654c44697e44
PODMAN_EMPTY=YES
MODEL_UNCHANGED=YES
```

## Permanent CP6A no-rerun

```text
V118_AMENDMENT_C_RED_LAUNCH=CONSUMED_NEVER_RERUN
V118_AMENDMENT_C_APPROVAL_CONSUMED=YES_FOREVER
CP6A_RED_RERUN_ALLOWED=NO
CP6A_DELIVERY_RERUN_ALLOWED=NO
CP6A_LOCAL_PROMOTION_RERUN_ALLOWED=NO
```

Bevara recovery-evidens, backup-ref och candidate-ref.

## CP6B kontrakt

Rollordning:

1. `idekompassen-2.0`
2. `metaarkitekten`
3. `agentarkitekten`
4. `ai-istallator`
5. `webmaster`
6. `reviewer`

```text
ROLE_REGISTRY_SHA256=fd5f821378206c20f86e9e7f5292ba06846d597790797b2186fb3f44f751306e
HANDOFF_SCHEMA_SHA256=4585d7fe85ba691c122b5afa9ac1704688e349387b245d79e29b6a6e16eec8f4
IDEKOMPASS_CONTRACT_SHA256=3a3b3558b8485fe98b5e4ad14617e2b0f23d61d9a71e614a7ff9c7d5fd2fa0bb
AGENT_MANIFEST_SHA256=8735fa407264503b40835d0bf50e3822875102902c1d79569182ecf7c4a4deb0
AGENT_RULE_SHA256=4b25c2fd020b6f3c25c6ff3d60c7917abbf06130970b92d00203cf11c74a7f0b
TASK_SCHEMA_SHA256=955edfbdd5769e066456e259d9953f4b45f738fad099fea2b5e2667c921cdd9d
PROPOSAL_SCHEMA_SHA256=c1d8fbcc8baa82ce3d882d28f4fa476692b918c2482694f5565c4ebe1643b3dc
AGENT_CORE_SHA256=879177425541e9f5fdbfb6c7291d9c565b3bc05cf33e0ced109fa3fb1c5fc3da
```

Befintlig agentregel har fortfarande:

```text
task_mode=single_task
cp6b_routing=false
network=none
sudo=false
secrets=false
production=false
merge=false
deploy=false
automatic_rerun=false
kill_switch=STOP / stop_before_next_effect
```

CP6B måste därför byggas som separat orchestratorlager; CP6A-policyn får inte tyst expanderas.

## CP6B säkerhetskrav

- Idékompassen 2.0 först.
- Reviewer oberoende.
- Ingen roll får själv utöka rättigheter.
- Handoffs är versionsmärkta artefakter, inte antaget delat minne.
- Ingen web-GPT-autonomi får påstås utan verklig mekanism.
- Ingen produktion/one.com/externt skrivande i första CP6B-scope.

## Checkpointkadens — användarbeslut

Checkpointa aktiv kunskap vid större fas-/delfasövergångar. Inte varje liten versionsiteration kräver nytt paket. Vid lång felsökningskedja ska extra resume-checkpoint normalt tas ungefär vid v1.15–v1.20 eller tidigare om kontextförlust riskeras.

## Nästa exakta steg

```text
NEXT_PHASE=CP6B
CP6B_SCOPE_DISCOVERY=PASS_READ_ONLY
CP6B_CONTRACT_INVENTORY=PASS_READ_ONLY
CP6B_BUILD=NOT_STARTED
NEXT_ACTION=FORMULATE_NAMED_CP6B_BUILD_PLAN
```

Vid ny session: läs denna fil, verifiera aktuell main/clean/remotes och kontraktshashar, och fortsätt med CP6B-planering. Kör inte om CP6A Recovery/Delivery/Promotion.
