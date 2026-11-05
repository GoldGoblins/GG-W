# Independent protected account signing

## Original intent

An account owner signs real payments with an independent account key. CLI owns
the operation and Desktop displays the same verified account. An account does
not gain a producer, node or validator role merely because it exists. Exact
originals must survive uncertainty, crashes and retries.

## Implemented boundary

`gg_financial_account.AccountProfile` owns one fresh prime-order Ed25519 key.
It reuses the existing Windows DPAPI or explicitly unlocked POSIX
scrypt/AES-GCM provider, with a separate `financial_account` role domain and
profile-root binding. The existing Solana wallet is not relabeled or reused
as a native account. There is no plaintext key file or automatic key import.

The profile uses an exclusive file lease and private SQLite database, validates
file type/link count, requires the exact schema, and uses synchronous EXTRA
durability. A key-signed metadata head binds the immutable native genesis pin,
reserved nonce range and hash chain of retained original payment documents.
The public account signature belongs to the account, not its block producer.

Review requires a native-verified proof of the independently requested own
account. Recipient/amount fields are finite and explicit, funds are checked
against that certified view, and nonce is derived from the verified account.
Review is an immutable local object, not a peer JSON assertion. A later empty
SDK height does not invalidate an otherwise identical account view; changed
own balance/nonce or changed signing head requires a new review.

Signatures and the exact public payment document commit in the same SQLite
transaction as the reserved nonce range and signed metadata head. Bytes return
only after commit. A failed or uncertain write faults that profile instance;
cold opening selects the actually committed boundary and never re-signs an
uncertain original. Pending exports select unchanged original account
envelopes, including an unconsumed suffix after partial ordered execution.

Historical documents remain on disk. Cold opening streams their hashes against
the key-signed chain with bounded chunks, rather than keeping global history
in RAM. Explicit historical export authenticates the chain. The current file
cap is 2 GiB and batch cap 65,535; these are finite local wallet storage limits,
not unlimited retention or a network throughput claim. Exhaustion refuses new
local signatures. Native blockchain history is a separate durable source.

## CLI and observation

Explicit commands create/open/select an account, review a bounded intent file,
sign the reviewed intent, export exact public originals, and submit their
unchanged account envelopes through an owned producer. Ordinary profile open,
node resume and `--account-profile` observation do not sign or produce.

The intent file binds schema, genesis, sender and ordered recipient/amount
rows. It rejects extra private fields, duplicate/noncanonical JSON and excessive
size/depth/count. Export never overwrites an existing file and refuses account
vault destinations. An export error leaves the durable original available.

Selected account addresses are registered only from loaded local profiles.
Only rows for that selected account appear as the current own wallet; another
member's account must not fill the view while its proof is pending. Read-only
CLI/Desktop observation preserves the selected public profile and exact
existence/certificate fields, without exposing the signer or protected key.

## Deliberate distinctions

- A valid account signature is not an SDK payment receipt.
- A transport ACK or mempool response is not execution or finality.
- Certified nonce consumption does not identify which payment recipient won.
  That state is reported as `NONCE_CONSUMED_OUTCOME_UNRESOLVED`, not APPLIED.
- No automatic same-nonce replacement or cancellation is implemented. An
  unconsumed original remains pending; receipt-aware replacement policy needs
  separate review before any such feature is exposed.
- Account signing is independent of producer ownership. The current direct
  submission command uses an owned opted-in producer. Autonomous wallet
  transaction relay from a light/replica-only peer is not claimed by this path;
  a signed public document can be submitted by another opted-in producer.
- Encrypted software storage is not a hardware signer, recoverable seed backup,
  protection from arbitrary same-user code, or whole-disk rollback detection.

## Verification scope

Protected-profile tests use real encryption, SQLite, account signatures,
5,000-payment documents and injected errors before/after durable commit. Their
SDK account lookup seam is explicitly synthetic. Separate tests use actual
SDK-signed unit membership/absence proofs and the current native verifier,
including protected cold reopen and exact retry without another signature.
The final stage report must distinguish those checks from actual multi-process
SDK payment execution. No physical device, active app, installed tool, public
network or real funds are changed by the private fixtures.

The full eight-step delivery remains open, including actual general-account
multi-process acceptance, physical Windows/Linux/Termux, capacity, public
economics/admission, pool accounting and independent security acceptance.
