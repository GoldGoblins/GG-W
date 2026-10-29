"use strict";
(() => {
  const element = id => document.getElementById(id);
  const packet = element("packet"), button = element("verify"), result = document.querySelector(".result");
  let trust = null, worker = null, timeout = null;
  const byteLength = value => new TextEncoder().encode(value).length;
  const errors = {
    GG_PROOF_PIN_MISMATCH: "Bevispaketet tillhör inte den här sidans GG-nät.",
    GG_PROOF_LIMIT: "Bevispaketet överskrider 256 KiB.",
    GG_PROOF_TIMEOUT: "Kontrollen tog mer än 3 sekunder och avbröts.",
    GG_PROOF_INVALID: "Bevispaketet kunde inte verifieras."
  };
  function detail(label, value) {
    const dt = document.createElement("dt"), dd = document.createElement("dd");
    dt.textContent = label; dd.textContent = String(value); element("result-details").append(dt, dd);
  }
  function finish(value, started) {
    if (timeout) clearTimeout(timeout);
    if (worker) worker.terminate();
    worker = null; timeout = null; button.disabled = !trust;
    element("elapsed").textContent = Math.round(performance.now() - started) + " ms · lokal kontroll";
    element("result-details").replaceChildren();
    const good = value && value.verified === true;
    result.className = "result " + (good ? "good" : "bad");
    element("result-status").textContent = good ? "Godkänd" : "Avvisad";
    element("result-title").textContent = good ? "Certifierad saldobild vid höjd " + value.state_height : (errors[value && value.error] || errors.GG_PROOF_INVALID);
    if (good) {
      if (value.verified_account) {
        const account = value.verified_account;
        const atomic = String(account.balance_atomic).padStart(account.decimals + 1, "0");
        const whole = atomic.slice(0, -account.decimals).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
        const fraction = atomic.slice(-account.decimals).replace(/0+$/, "");
        detail("Certifierat saldo", whole + (fraction ? "." + fraction : "") + " " + account.symbol);
        detail("Konto", account.address);
      }
      detail("Saldobild / certifikat", value.state_height + " / " + value.certificate_height);
      detail("Kvorum", value.quorum_required + " av " + value.validator_count + " fasta validatorer");
      detail("Tillståndsrot", value.state_root);
      detail("Kontobevis", value.account_proof_verified ? "Verifierat" : "Ingår inte i paketet");
      detail("Transaktionsbevis", value.transaction_inclusion_verified ? "Verifierat" : "Ingår inte i paketet");
      detail("Exekvering", value.execution_status_verified ? "Verifierad från certifierat föregående tillstånd" : "Ingår inte i paketet");
      if (Number.isFinite(value.wasm_linear_memory_bytes)) detail("WASM linjärt minne", (value.wasm_linear_memory_bytes / 1048576).toFixed(1) + " MiB under kontrollen");
    }
  }
  packet.addEventListener("input", () => {
    const length = byteLength(packet.value);
    element("packet-size").textContent = (length / 1024).toFixed(1) + " / 256 KiB";
  });
  element("clear").addEventListener("click", () => {
    if (worker) worker.terminate(); if (timeout) clearTimeout(timeout);
    worker = null; timeout = null; packet.value = ""; packet.dispatchEvent(new Event("input"));
    button.disabled = !trust; result.className = "result"; element("result-details").replaceChildren();
    element("result-title").textContent = "Ingen saldobild har kontrollerats.";
    element("result-status").textContent = "Väntar på bevispaket"; element("elapsed").textContent = "";
  });
  button.addEventListener("click", () => {
    if (!trust || worker) return;
    const started = performance.now();
    if (!packet.value || byteLength(packet.value) > 262144) { finish({ verified: false, error: "GG_PROOF_LIMIT" }, started); return; }
    button.disabled = true; element("result-status").textContent = "Kontrollerar…";
    worker = new Worker("/verify-worker.js");
    timeout = setTimeout(() => finish({ verified: false, error: "GG_PROOF_TIMEOUT" }, started), 3000);
    worker.onmessage = event => finish(event.data, started);
    worker.onerror = () => finish({ verified: false, error: "GG_PROOF_INVALID" }, started);
    worker.postMessage({ packet: packet.value, trust });
  });
  fetch("/trust.json", { cache: "no-store", credentials: "omit" }).then(async response => {
    if (!response.ok) throw new Error("unavailable");
    const raw = await response.text();
    if (byteLength(raw) > 16384) throw new Error("invalid");
    const pinned = JSON.parse(raw);
    if (!pinned.genesis || typeof pinned.genesis_hash !== "string") throw new Error("invalid");
    trust = Object.freeze(pinned);
    element("chain").textContent = pinned.genesis.chain_id;
    element("connection").textContent = "Lokal förankring låst";
    element("artifact").textContent = "Verifieraren: " + (pinned.verifier_wasm_bytes / 1048576).toFixed(2) + " MiB. Laddas vid kontroll; arbetaren avslutas efteråt.";
    button.disabled = false;
  }).catch(() => {
    element("connection").textContent = "Förankring saknas";
    element("result-title").textContent = "Öppna en ny certifikatkontroll från GG.";
  });
  window.addEventListener("pagehide", () => { if (worker) worker.terminate(); if (timeout) clearTimeout(timeout); });
})();
