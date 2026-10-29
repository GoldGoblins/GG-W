// Compile deterministically with the pinned, locally installed solc-js toolchain.
// Imports are restricted to the installed OpenZeppelin package; no network fetch.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, realpathSync } from "node:fs";
import { dirname, join, resolve, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const sourceRoot = dirname(fileURLToPath(import.meta.url));
const toolchain = resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("GG_TESTNET_TOOLCHAIN_REQUIRED");
const require = createRequire(join(toolchain, "package.json"));
const solc = require("solc");
const compilerVersion = solc.version();
if (!compilerVersion.startsWith("0.8.38+")) throw new Error("GG_TESTNET_COMPILER_VERSION");
const ozRoot = realpathSync(join(toolchain, "node_modules", "@openzeppelin", "contracts"));
const ozVersion = JSON.parse(readFileSync(join(ozRoot, "package.json"), "utf8")).version;
if (ozVersion !== "5.6.1") throw new Error("GG_TESTNET_OPENZEPPELIN_VERSION");
const sourceName = "contracts/GGTestToken.sol";
const content = readFileSync(join(sourceRoot, sourceName), "utf8");
const imports = {};
function findImports(name) {
  const prefix = "@openzeppelin/contracts/";
  if (!name.startsWith(prefix)) return { error: "GG_TESTNET_IMPORT_DENIED" };
  try {
    const target = realpathSync(join(ozRoot, name.slice(prefix.length)));
    const rel = relative(ozRoot, target);
    if (rel.startsWith(".." + sep) || rel === ".." || resolve(target) === ozRoot)
      return { error: "GG_TESTNET_IMPORT_DENIED" };
    const contents = readFileSync(target, "utf8");
    imports[name] = createHash("sha256").update(contents).digest("hex");
    return { contents };
  } catch { return { error: "GG_TESTNET_IMPORT_NOT_FOUND" }; }
}
const settings = {
  optimizer: { enabled: true, runs: 200 },
  evmVersion: "cancun",
  metadata: { bytecodeHash: "none", appendCBOR: false },
  outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] } }
};
const input = { language: "Solidity", sources: { [sourceName]: { content } }, settings };
const output = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));
if ((output.errors || []).some((e) => e.severity === "error")) {
  // Compiler messages contain only this public source, never environment keys.
  for (const e of output.errors) if (e.severity === "error") process.stderr.write(e.formattedMessage);
  process.exit(1);
}
const contract = output.contracts[sourceName].GGTestToken;
const artifact = {
  schema: "gg.testnet.contract-artifact.v1",
  contractName: "GGTestToken",
  sourceName,
  compiler: compilerVersion,
  openzeppelin: ozVersion,
  settings,
  source_sha256: createHash("sha256").update(content).digest("hex"),
  imports: Object.fromEntries(Object.entries(imports).sort(([a], [b]) => a.localeCompare(b))),
  abi: contract.abi,
  bytecode: "0x" + contract.evm.bytecode.object,
  deployedBytecode: "0x" + contract.evm.deployedBytecode.object,
  token: { name: "GG Test Token", symbol: "GG-TEST", decimals: 6, supply_atomic: "1000000000000", production: false }
};
const destination = resolve(process.argv[3] || join(sourceRoot, "GGTestToken.json"));
writeFileSync(destination, JSON.stringify(artifact, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ status: "COMPILED", contract: artifact.contractName, compiler: compilerVersion,
  openzeppelin: ozVersion, creation_bytes: contract.evm.bytecode.object.length / 2,
  runtime_bytes: contract.evm.deployedBytecode.object.length / 2 }));
