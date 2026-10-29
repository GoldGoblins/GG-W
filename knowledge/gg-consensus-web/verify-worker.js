"use strict";
importScripts("/proof-policy.js", "/wasm_exec.js");

self.onmessage = async event => {
  self.onmessage = null;
  try {
    const raw = GGProofPolicy.pinPacket(event.data.packet, event.data.trust);
    const go = new Go();
    const response = await fetch("/verifier.wasm", { cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new Error("GG_PROOF_INVALID");
    const instance = await WebAssembly.instantiate(await response.arrayBuffer(), go.importObject);
    go.run(instance.instance).catch(() => {});
    if (typeof self.ggVerifyConsensusProof !== "function") throw new Error("GG_PROOF_INVALID");
    const result = JSON.parse(self.ggVerifyConsensusProof(raw));
    if (!result || typeof result !== "object" || JSON.stringify(result).length > 8192) throw new Error("GG_PROOF_INVALID");
    result.wasm_linear_memory_bytes = instance.instance.exports.mem.buffer.byteLength;
    result.verified_account = GGProofPolicy.verifiedAccount(raw, result);
    self.postMessage(result);
  } catch (error) {
    self.postMessage({ verified: false, error: GGProofPolicy.publicError(error) });
  }
};
