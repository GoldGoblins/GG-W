# GG native consensus test engine

This component runs a GG transfer ledger inside **CometBFT v0.40.0**. Four separate
node processes communicate over loopback P2P. Each has one equal-power validator;
three signatures are required to commit. The controller owns process limits,
temporary roots, ephemeral seeds, fault tests, measurement and the user interface.

This is a disposable, fixed-membership development network on one computer. It
does not establish production readiness, Internet decentralization, sharding,
general computation proofs, or a throughput advantage over a public network.
The account witnesses below are ordinary Merkle membership proofs.

## Original dependencies and explicit build

`toolchain.json` pins the original Windows Go archive, its byte count and SHA-256.
The explicit `install_toolchain.py` installer verifies that archive before
extracting it into `TOOLS_ROOT/gg-consensus`. It does not change PATH or install
globally. Importing the module never downloads or starts anything.

On Linux or Android/Termux the installer uses an already installed stable Go
compiler version 1.25 or newer. It does not run a system package manager or
install Go globally. The original distributor/package manager supplies that
compiler. `GOTOOLCHAIN=local` prevents automatic alternate-toolchain downloads;
the receipt records the compiler version and GOOS/GOARCH actually used.

The installer copies these public sources and the pinned `go.mod`/`go.sum` into a
fresh temporary build directory below the external tool directory, then builds with `CGO_ENABLED=0`, `GOTOOLCHAIN=local`,
`-mod=readonly` and `-trimpath`. Module downloads use the Go module proxy and
checksum database. New binaries use a versioned native basename, recorded in
`build-manifest.json`:

```
TOOLS_ROOT/gg-consensus/gg-consensus-node-<source-version>.exe
```

`build-manifest.json` records the compiled binary SHA-256, source fingerprint,
Go/Comet versions and build flags. `source_fingerprint()` in the installer is a
read-only freshness helper. `notices/modules.json` records pinned module
suppliers, checksum-database sums and available original license/notice texts
copied into that directory; entries with no license text require an upstream
license audit before distributing a compiled tool. The installed Go distribution
retains its original license, which is copied into the notices directory too.

The controller accepts only the native receipt-bound basename in this exact
tool directory and verifies source freshness and executable bytes before
launch. A rebuild publishes beside an older running executable; it never
overwrites or stops that process. Existing verified legacy basenames remain
readable. No automatic cleanup deletes older executable images.

Idle operation now proposes real signed empty blocks with a two-second wait.
Transactions still wake consensus immediately; the four equal validators,
three-signature quorum and H+1 execution-proof rules are unchanged. A target
interval is not an exact scheduler guarantee or a claim of 60 blocks/s.

Explicit local installation from the application root:

```powershell
.\.venv-windows\Scripts\python.exe support/gg-consensus/install_toolchain.py
```

Upstream sources:

- [CometBFT v0.40.0](https://github.com/cometbft/cometbft/tree/v0.40.0)
- [Go original downloads](https://go.dev/dl/)
- [CometBFT node constructor](https://github.com/cometbft/cometbft/blob/v0.40.0/node/node.go)
- [Upstream private-validator signing protections](https://github.com/cometbft/cometbft/blob/v0.40.0/privval/file.go)
- [SDK light commit verification](https://github.com/cometbft/cometbft/blob/v0.40.0/types/validator_set.go)

## Secret-free disk contract

The node reads at most 64 KiB of bootstrap JSON from stdin, then requires EOF.
The controller sends validator and P2P seeds through that pipe only. Nodes create
their private keys in RAM. They never call the CometBFT private-key save or
node-key save routines. The account signing keys remain in the controller RAM.

Public persistent files include the CometBFT databases/WAL, immutable
`gg-public-genesis.json`, bounded `gg-public-state.json` history, and
`data/priv_validator_state.json`. The last file contains public signing state
and signatures, preserving upstream height/round/step anti-double-sign checks
across a process restart. A restart must retain both that public state and the
same RAM seed. If the application loses the RAM seeds, it must create a new chain
and fresh keys. Reusing an old validator identity after deleting its sign state
is unsafe and is not an authorized recovery path.

After `node.Start` succeeds, stdout contains one public ready-attestation JSON
line of at most 1024 bytes, with `schema:gg.consensus.ready.v1`, `chain_id`,
`node_id`, `pid`, `rpc_port` and `p2p_port`. The controller reads and validates
that bounded line from its own child pipe. This supports Android environments
that deny `/proc/net` inspection; it never replaces SDK certificate checking.
Stderr and any unexpected output are discarded. Startup failure prints only a
fixed code. No bootstrap seeds or signing values are logged.

Linux/Android nodes capture their initial parent PID before reading bootstrap
and check it every 500 ms. On parent loss they stop their own node, with a
three-second self-exit fallback. Windows retains application-owned Job-object
containment. The PID lease fails closed when the initial parent is PID 1; a
container controller therefore needs a real init/subreaper wrapper instead of
running directly as PID 1. No unrelated process is signaled.

## Bootstrap JSON

All hexadecimal strings are lowercase. Seeds below are descriptions, not
literal keys. The root is an absolute temporary directory reserved to this node.

```json
{
  "schema": "gg.consensus.bootstrap.v1",
  "genesis": {
    "accounts": ["four 32-byte Ed25519 public keys as 64 hexadecimal characters"],
    "chain_id": "ggnet:<24 hexadecimal characters>",
    "decimals": 6,
    "genesis_time_unix": 1700000000,
    "schema": "gg.native.genesis.v1",
    "supply_atomic": "1000000000000",
    "symbol": "GG-NET-TEST",
    "validators": ["four distinct validator public keys, same encoding"]
  },
  "genesis_hash": "SHA256 of compact sorted-key genesis JSON",
  "validator_index": 0,
  "validator_seed": "32 random bytes encoded as 64 hexadecimal characters",
  "node_seed": "different 32 random bytes in the same encoding",
  "root": "absolute temporary node directory",
  "rpc_port": 51001,
  "p2p_port": 51002,
  "peers": [{"id": "40-character Comet node ID", "port": 51004}]
}
```

Both public-key arrays contain exactly four entries; `peers` contains exactly the
other three nodes. The Comet node ID is its Ed25519 public key's SHA-256 digest
truncated to 20 bytes. RPC and P2P bind to `127.0.0.1`; peer exchange, state sync,
libp2p, RPC unsafe operations, RPC gRPC, profiling and Prometheus are disabled.

## Ledger and transaction JSON

There are exactly four genesis accounts. Each begins with 250,000 GG-NET-TEST.
Total supply is fixed at 1,000,000 with six decimals. This initial native transfer
ledger has **no transfer fees**; balances conserve exactly the fixed atomic
supply. The asset has no connection to GGHB, any public chain or real funds.

A transaction is compact UTF-8 JSON with lexicographically ordered object keys.
The Ed25519 signature covers only the canonical `body` bytes:

```json
{"body":{"amount_atomic":"1000000","chain_id":"ggnet:<chain>","genesis_hash":"<anchor>","nonce":0,"recipient":"<public key>","sender":"<public key>","version":1},"signature":"<128 hexadecimal characters>"}
```

No whitespace, duplicate keys, unknown fields, alternative numeric forms,
cross-chain reuse, self-transfers or non-genesis accounts are accepted. Amounts
are positive canonical integer strings. An execution requires the sender's exact
current nonce, a valid signature and sufficient balance; it increments that nonce
once. CheckTx allows a future nonce at most 255 ahead for bounded batching, but
proposal preparation and every validator execute strictly in nonce order.

Limits: transaction 2 KiB; block 64 KiB and at most 128 transfers; mempool 256
transactions and 512 KiB; public application history 256 heights. The controller
also bounds pending actions and process resources. Consensus timeout settings
are local test settings, not a promised blocks-per-second rate.

## Standard Comet RPC and GG queries

Use only the controller-owned loopback addresses. Standard Comet endpoints:

- `GET /status`
- `GET /broadcast_tx_sync?tx=0xHEX`
- `GET /tx?hash=0xHEX&prove=true`
- `GET /block?height=H`
- `GET /commit?height=H`
- `GET /abci_query?path="/gg/state"&height=H`

ABCI response `value` is base64 JSON. Standard ABCI height zero means the latest
committed application state. `/gg/genesis` returns the original height-zero state
even after later commits. `/gg/proof` accepts an account address as 32 raw bytes
or 64 ASCII hexadecimal bytes in request data, and supports a retained height.
Unknown/unretained heights fail; they never silently return latest state.

The public state contains `schema`, `height`, `chain_id`, `genesis_hash`, `symbol`,
`decimals`, `supply_atomic`, `accounts`, `account_root`, and `state_root`.
Accounts are sorted by address and each contains `address`, `balance_atomic`,
and `nonce`.

Each account leaf is `SHA256(0x00 || canonical(account))`. Each binary parent is
`SHA256(0x01 || left32 || right32)`. The four leaves produce a two-step witness.
The final state root is SHA-256 of this compact sorted-key object:

```json
{"account_root":"<Merkle root>","chain_id":"<chain>","genesis_hash":"<anchor>","schema":"gg.native.commitment.v1","supply_atomic":"1000000000000"}
```

Height is deliberately outside the commitment. An empty proof block therefore
does not change the state root or cause an endless sequence of proof blocks.

**Comet header H authenticates application state H-1.** A transfer in block H
needs the certified header H+1 to certify its resulting balances. Comet's
upstream `needProofBlock` behavior creates that extra proof block even with
ordinary idle empty blocks disabled. A CheckTx response, local FinalizeBlock
result, or transaction inclusion proof alone is insufficient for certified
execution.

## Offline SDK proof verification

`gg-consensus-node.exe verify` reads public JSON from stdin (maximum 256 KiB),
writes one bounded JSON result, and exits. It opens no files or network sockets
and requires no private keys. Its input:

```json
{
  "schema": "gg.consensus.proof.v1",
  "genesis": "full trusted public genesis object",
  "genesis_hash": "trusted genesis anchor",
  "signed_header": "signed_header object from /commit at H+1",
  "state": "public GG state object at H",
  "account_proof": "optional GG /gg/proof object at H",
  "tx_header": "optional signed_header object from /commit at H",
  "tx_proof": "optional proof object from /tx?prove=true",
  "expected_tx_hash": "optional SHA256 transaction hex",
  "before_state": "optional public state at H-1",
  "block_txs": ["optional full block H data.txs base64 strings"]
}
```

The quoted descriptions above stand for actual nested JSON objects. The caller
must provide its independently trusted genesis; accepting a genesis supplied by
an untrusted server would destroy that trust boundary.

The helper uses the Comet SDK for SignedHeader validation, header hashing, commit
signature sign bytes, fixed-validator quorum verification and transaction Merkle
proof validation. It verifies the fixed validator hashes, chain, state height,
supply and GG roots. With transaction fields, it verifies adjacent certified
headers, direct parent block identity, transaction inclusion, hash and sender
signature. Optional `before_state` **and** the full bounded `block_txs` enable
deterministic execution replay: the previous state is anchored to header H,
the full transaction list matches its data root, and replay must exactly produce
the state certified by H+1. Only then is `execution_status_verified` true.

Successful output has `verified:true`, `schema:gg.consensus.proof-result.v1`,
`chain_id`, `state_height`, `certificate_height`, `state_root`, `account_root`,
`validator_count:4`, `quorum_required:3`, `account_proof_verified`,
`transaction_inclusion_verified`, `transaction_height` and
`execution_status_verified`. Failure returns only
`{"verified":false,"error":"GG_PROOF_INVALID"}` and exit status 1.

## Verification and remaining scope

Run Go tests with the pinned external toolchain and the installer's environment.
The tests cover strict signatures/JSON/chain anchors, replay and overspending,
proposal isolation, exact persistent state, stable roots through empty blocks,
corrupt-state rejection, retained upstream double-sign protection without a key
file, valid 3-of-4 versus invalid 2-of-4 certificates, forged proofs and bounded
certified execution replay. The application integration tests must additionally
launch all four real processes, exercise peer links, halt and restore quorum,
reconcile equal states, check private-key absence, and measure observed timing.

The fixed four-account model, full public-state snapshots and sequential ledger
are intentionally small foundations. These need explicit migration, storage,
membership, hostile-peer, network-partition and multi-host work before public
operation. A fast local benchmark must never be labeled an Internet-network
capacity or a production security result.

## Browser verification without a validator process

The explicit installer also builds `verifier.wasm` from the same unchanged
`ledger.go` and `verify.go`, with the Comet SDK and a small JS/WASM entry point.
`build_light_verifier(target)` or `--light-only` builds this optional artifact
without overwriting the native node. The original Go `wasm_exec.js` runtime is
copied from the verified toolchain. `light-manifest.json` records separate source,
artifact and runtime fingerprints; native source receipts remain independent.

`backend.gg_consensus_web.start({genesis, genesis_hash})` explicitly starts an
owned loopback viewer and returns its URL. This is a public trusted context from
the active GG controller, never an anchor selected by a pasted proof. The browser
fetches that session pin once, rejects packets from other chains or validator
sets, then injects the pinned genesis before calling the SDK. A new session opens
a new listener; an old page keeps its original pin. This local handoff is not a
globally decentralized bootstrap mechanism.

Only fixed static paths and `/trust.json` are served. There are four connection
slots, no POST/import API, no external URL selection, Host/Origin checks, a
same-origin CSP and no wallet or signing calls. Each verification uses a fresh
worker; public input is limited to 256 KiB and the worker is terminated after the
result or after a three-second deadline. Duplicate object keys and deep JSON are
rejected; original uint64 nonce bytes are preserved. Certified historical
balances are labeled with their state height and never presented as guaranteed
latest balances.

Measured on the development Windows host: the SDK WASM file is 31,974,113 bytes
(30.49 MiB), with a 16,992-byte original Go JS runtime. Example desktop and narrow
Chromium checks reported 210–242 ms and 19 MiB of WASM linear memory. Those are
local examples, not small-device performance guarantees; linear memory excludes
the browser, JS engine, compiler and asset buffers. This proof viewer is lighter
in responsibility than a validator, but its cryptography and download are not
free.

`tests/test_gg_consensus_light.py` executes the real WASM via Node, including a
valid SDK certificate, account witness and adjacent-header execution replay;
changed roots/header/path; input/deadline limits; HTTP guards; and a genuinely
valid foreign four-validator chain that must fail under the original pin.
`light/render_viewer.py` provides an isolated headless Chromium visual check with
a fresh temporary profile. Its optional `--packet` is for explicitly trusted
public test exports only. It never uses a user's Firefox or browser profile.

## Linux and experimental Termux native builds

With the separately installed Go compiler available on PATH:

```sh
python3 support/gg-consensus/install_toolchain.py --native-only
```

This builds the native node and its receipt without a browser, Qt, Rust, or the
optional WASM artifact. The controller and actual TUI use the same native node,
ledger, certificates and test supply. Four local validator processes still
consume real CPU, RAM and storage; this is not a passive phone watch client.

The installer also supports explicit compile-only checks into independent
`TOOLS_ROOT/gg-consensus/cross/<os>-<arch>/` directories:

```sh
python3 support/gg-consensus/install_toolchain.py --cross linux/amd64
python3 support/gg-consensus/install_toolchain.py --cross linux/arm64
python3 support/gg-consensus/install_toolchain.py --cross android/arm64
```

Linux/amd64 and Android/arm64 were cross-compiled successfully from Windows.
Cross-compilation is not evidence of target execution, fault recovery, resource
containment or performance. Real Linux and phone acceptance remain separate.

Android/arm64 currently requires the upstream-documented Android-only
`-ldflags=-checklinkname=0` compatibility option. CometBFT's compiled dependency
graph includes Pion's `wlynxg/anet v0.0.5`, which references the private Go
`net.zoneCache` symbol; Go 1.23+ otherwise rejects the link. The library
[maintainer explains this unresolved compatibility issue](https://github.com/wlynxg/anet/pull/9).
The option permits that private-symbol link and depends on an unstable internal
ABI. It does not disable signatures, quorum, roots, nonces or SDK proof checks.
GG's libp2p path stays disabled. Android receipts explicitly record the flag,
reason, upstream URL, `experimental:true` and `target_execution_tested:false`.
Other Android architectures fail closed; no NDK or compiler is installed.

The [Android platform restricts `/proc/net` from Android 10 onward](https://developer.android.com/about/versions/10/privacy/changes#proc-net-filesystem),
as also documented by the [Termux maintainers](https://github.com/termux/termux-packages/wiki/Termux-and-Android-10).
Ownership reporting must distinguish kernel socket inspection from an owned
child-pipe attestation. A successful cross-build never justifies claiming the
four-node application has been tested on a real phone.
