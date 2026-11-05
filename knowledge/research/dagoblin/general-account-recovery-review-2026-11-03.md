# General account recovery and observation boundaries

## Original intent

Keep account and node identities, exact signed originals and verified monetary
history across failures. Public archives restore chain data to a nonvoting
observer, never voting or account-signing authority. CLI and Desktop must show
the same certified account, with its observation basis explicit.

## Findings and changes

The existing history destination guard covered node, validator and observer
profile roots. Independent financial account profiles add another protected
root; public history export/application restore now refuse that root as well.
Public account-document export likewise refuses all four key-profile roots.
These checks run before creating a public destination. They do not change
archive bytes, consensus, monetary rules, signing domains or genesis versions.

The signer's stored account proof is a durable review/nonce floor, not a live
balance query. Profile status now labels that basis explicitly. The account
status command separately returns the current cached certified node-account
view, including proof pending, offline, fault and network mismatch states.
Reading it performs no network request, wallet binding, signature or durable
write. The current value uses the same bounded certified rows as Desktop.

## Recovery acceptance

The private acceptance fixture must use the reviewed general-account model,
protected CLI-created accounts, real original payments, and actual SDK nodes.
It must export and verify full history, restore the application idempotently,
and bootstrap an owned nonvoting SDK observer offline. The restored observer
must join the existing committee, follow new actual payments, query an old
receipt from its own application and keep its P2P identity over cold restart.

Recovering public history must report `validator_signing_state_restored: false`
and no imported signing keys. Offline bootstrap is not a claim of live network
contact. Known signer/voter state must never be reset or copied from an archive.
Account private keys stay in their separate protected profiles.

The actual stage report records what was executed, exact reviewed sources,
platforms and limits. Unit policy seams are not evidence of SDK replay. Linux
processes in WSL are not physical Linux/Termux device acceptance. Neither this
finite recovery test nor its account count establishes the throughput target,
unlimited storage, public economics/admission or independent security approval.
