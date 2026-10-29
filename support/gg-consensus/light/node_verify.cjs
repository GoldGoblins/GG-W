// Bounded test harness for the same WASM and worker used by the browser.
// stdin and stdout contain public proof JSON only. No sockets or private keys.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { Worker } = require("node:worker_threads");

const MAX_BYTES = 256 * 1024;
let chunks = [], total = 0;
process.stdin.on("data", chunk => {
  total += chunk.length;
  if (total > 2 * MAX_BYTES + 16384) {
    process.stdout.write('{"verified":false,"error":"GG_PROOF_LIMIT"}\n');
    process.exit(1);
  }
  chunks.push(chunk);
});
process.stdin.on("end", () => {
  let input;
  try { input = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
  catch { process.stdout.write('{"verified":false,"error":"GG_PROOF_INVALID"}\n'); process.exit(1); }
  const worker = new Worker(path.join(__dirname, "node_worker.cjs"), {
    workerData: { toolRoot: process.argv[2], publicRoot: process.argv[3] },
    resourceLimits: { maxOldGenerationSizeMb: 192 }
  });
  const timeout = setTimeout(() => finish({ verified: false, error: "GG_PROOF_TIMEOUT" }), 3000);
  let finished = false;
  function finish(result) {
    if (finished) return;
    finished = true; clearTimeout(timeout);
    worker.terminate();
    process.stdout.write(JSON.stringify(result) + "\n", () => process.exit(result.verified === true ? 0 : 1));
  }
  worker.on("message", finish);
  worker.on("error", () => finish({ verified: false, error: "GG_PROOF_INVALID" }));
  worker.on("exit", () => { if (!finished) finish({ verified: false, error: "GG_PROOF_INVALID" }); });
  worker.postMessage(input);
});
