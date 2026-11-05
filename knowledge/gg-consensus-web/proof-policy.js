/* Shared public-packet policy for the browser worker and Node/WASM tests. */
"use strict";
(function (scope) {
  const MAX_BYTES = 256 * 1024;
  const CODES = new Set(["GG_PROOF_LIMIT", "GG_PROOF_INVALID", "GG_PROOF_PIN_MISMATCH"]);
  function fail(code) { throw new Error(code); }
  function strictParse(raw, locations) {
    if (typeof raw !== "string" || raw.length === 0 || new TextEncoder().encode(raw).length > MAX_BYTES) fail("GG_PROOF_LIMIT");
    let offset = 0;
    const space = () => { while (/\s/.test(raw[offset] || "") && offset < raw.length) offset++; };
    function string() {
      const start = offset++;
      while (offset < raw.length) {
        const character = raw[offset++];
        if (character === "\\") offset++;
        else if (character === '"') return JSON.parse(raw.slice(start, offset));
      }
      fail("GG_PROOF_INVALID");
    }
    function value(depth) {
      if (depth > 12) fail("GG_PROOF_INVALID");
      space();
      const character = raw[offset];
      if (character === "{") {
        offset++; space(); const keys = new Set();
        if (raw[offset] === "}") { offset++; return; }
        while (offset < raw.length) {
          if (raw[offset] !== '"') fail("GG_PROOF_INVALID");
          const key = string();
          if (keys.has(key)) fail("GG_PROOF_INVALID");
          keys.add(key); space();
          if (raw[offset++] !== ":") fail("GG_PROOF_INVALID");
          space(); const start = offset;
          value(depth + 1);
          if (depth === 0 && locations) locations[key] = [start, offset];
          space();
          const next = raw[offset++];
          if (next === "}") return;
          if (next !== ",") fail("GG_PROOF_INVALID");
          space();
        }
        fail("GG_PROOF_INVALID");
      } else if (character === "[") {
        offset++; space();
        if (raw[offset] === "]") { offset++; return; }
        while (offset < raw.length) {
          value(depth + 1); space(); const next = raw[offset++];
          if (next === "]") return;
          if (next !== ",") fail("GG_PROOF_INVALID");
        }
        fail("GG_PROOF_INVALID");
      } else if (character === '"') string();
      else {
        const start = offset;
        while (offset < raw.length && !/[\s,}\]]/.test(raw[offset])) offset++;
        if (offset === start) fail("GG_PROOF_INVALID");
      }
    }
    try { value(0); space(); if (offset !== raw.length) fail("GG_PROOF_INVALID"); return JSON.parse(raw); }
    catch { fail("GG_PROOF_INVALID"); }
  }
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
    return JSON.stringify(value);
  }
  function pinPacket(packet, trust) {
    const raw = typeof packet === "string" ? packet : JSON.stringify(packet);
    const locations = Object.create(null);
    const value = strictParse(raw, locations);
    if (!trust || !trust.genesis || typeof trust.genesis_hash !== "string" ||
        !value || typeof value !== "object" || Array.isArray(value) || !value.genesis ||
        value.genesis_hash !== trust.genesis_hash || value.genesis.chain_id !== trust.genesis.chain_id ||
        canonical(value.genesis) !== canonical(trust.genesis)) fail("GG_PROOF_PIN_MISMATCH");
    // The packet never gets to choose its validator trust set.
    // Replace only these two public trust fields. Preserve the original bytes
    // of uint64 account nonces; JS numbers cannot represent all of them exactly.
    let pinned = raw;
    const replacements = [
      { range: locations.genesis, value: canonical(trust.genesis) },
      { range: locations.genesis_hash, value: JSON.stringify(trust.genesis_hash) }
    ];
    // An authenticated absence path can cover several missing addresses.
    // Bind the requested wallet account separately from provider proof data.
    if (value.financial_account !== undefined || trust.expected_financial_account !== undefined) {
      const expected = trust.expected_financial_account;
      if (typeof expected !== "string" || !/^[0-9a-f]{64}$/.test(expected) ||
          value.expected_financial_account !== expected || !value.financial_account ||
          !value.financial_account.proof || value.financial_account.proof.address !== expected ||
          !locations.expected_financial_account) fail("GG_PROOF_PIN_MISMATCH");
      replacements.push({ range: locations.expected_financial_account, value: JSON.stringify(expected) });
    }
    // Every selected result belongs to the caller's separately opened request.
    // A provider may supply paths and certificates, never replace that request
    // by changing both the proof and its embedded expected selector.
    for (const name of ["receipt", "registry", "block", "reward"]) {
      const field = "financial_" + name, selector = "expected_" + field;
      if (value[field] === undefined && trust[selector] === undefined) continue;
      if (value[field] === undefined || trust[selector] === undefined ||
          !locations[selector] || canonical(value[selector]) !== canonical(trust[selector])) fail("GG_PROOF_PIN_MISMATCH");
      replacements.push({ range: locations[selector], value: canonical(trust[selector]) });
    }
    replacements.sort((a, b) => b.range[0] - a.range[0]);
    for (const replacement of replacements) pinned = pinned.slice(0, replacement.range[0]) + replacement.value + pinned.slice(replacement.range[1]);
    if (new TextEncoder().encode(pinned).length > MAX_BYTES) fail("GG_PROOF_LIMIT");
    return pinned;
  }
  function publicError(error) { return CODES.has(error && error.message) ? error.message : "GG_PROOF_INVALID"; }
  function verifiedAccount(raw, result) {
    if (!result || result.verified !== true) return null;
    const value = JSON.parse(raw);
    if (result.financial_account_verified === true) {
      const address = value.expected_financial_account;
      if (result.financial_account_address !== address || typeof result.financial_account_exists !== "boolean") fail("GG_PROOF_INVALID");
      const exists = result.financial_account_exists;
      const leaf = result.financial_account;
      if (exists && (!leaf || leaf.address !== address || typeof leaf.balance_atomic !== "string" ||
          !/^(0|[1-9][0-9]{0,19})$/.test(leaf.balance_atomic) || typeof leaf.nonce !== "string" ||
          !/^(0|[1-9][0-9]{0,19})$/.test(leaf.nonce))) fail("GG_PROOF_INVALID");
      if (!exists && leaf !== null) fail("GG_PROOF_INVALID");
      return { address, balance_atomic: exists ? leaf.balance_atomic : "0", nonce: exists ? leaf.nonce : "0",
        exists, symbol: value.state.symbol, decimals: value.state.decimals };
    }
    if (result.account_proof_verified !== true) return null;
    const leaf = value.account_proof.leaf;
    return { address: leaf.address, balance_atomic: leaf.balance_atomic, symbol: value.state.symbol, decimals: value.state.decimals };
  }
  const api = { pinPacket, strictParse, publicError, verifiedAccount, MAX_BYTES };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else scope.GGProofPolicy = api;
})(globalThis);
