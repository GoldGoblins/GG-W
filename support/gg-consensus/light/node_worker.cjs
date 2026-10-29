"use strict";
const { parentPort, workerData } = require("node:worker_threads");
const fs = require("node:fs");
const path = require("node:path");
if (!globalThis.crypto) globalThis.crypto = require("node:crypto").webcrypto;
require(path.join(workerData.toolRoot, "wasm_exec.js"));
const policy = require(path.join(workerData.publicRoot, "proof-policy.js"));

parentPort.once("message", async input => {
  try {
    const raw = policy.pinPacket(input.packet, input.trust);
    const go = new Go();
    const instance = await WebAssembly.instantiate(fs.readFileSync(path.join(workerData.toolRoot, "verifier.wasm")), go.importObject);
    go.run(instance.instance).catch(() => {});
    if (typeof globalThis.ggVerifyConsensusProof !== "function") throw new Error("unavailable");
    const result = JSON.parse(globalThis.ggVerifyConsensusProof(raw));
    if (typeof result !== "object" || result === null || JSON.stringify(result).length > 8192) throw new Error("invalid");
    result.wasm_linear_memory_bytes = instance.instance.exports.mem.buffer.byteLength;
    result.verified_account = policy.verifiedAccount(raw, result);
    parentPort.postMessage(result);
  } catch (error) {
    parentPort.postMessage({ verified: false, error: policy.publicError(error) });
  }
});
