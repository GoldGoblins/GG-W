# Public certificate viewer

Static Swedish GG interface for the optional CometBFT SDK WASM verifier.
`backend.gg_consensus_web` serves only fixed allowlisted files over an owned
`127.0.0.1` listener. The active GG session supplies the immutable public trust
anchor; pasted packets cannot choose their own genesis or validators.

`proof-policy.js` is shared with actual Node/WASM tests. It preserves original
uint64 JSON bytes, rejects ambiguous/oversized/deep input, checks the session pin,
and replaces only the two trust fields with the captured trusted context.
`verify-worker.js` runs the identical native SDK verification code in WASM.
`viewer.js` terminates the worker after every result or at three seconds and
shows a certified balance only when its account witness was verified.

No private keys, signing, wallet connections, external URLs, telemetry, service
workers or background verification are provided. Result labels specify the
historical state height. The four validators in this development network run on
one computer under one operator. The trust handoff and local measurements must
not be described as public-network decentralization or production readiness.

The WASM/runtime artifacts remain in the user's external tool directory, are
explicitly built from pinned original dependencies, and are checked against a
separate public build manifest. They are not bundled as giant source assets.
