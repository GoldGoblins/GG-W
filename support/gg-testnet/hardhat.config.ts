// The owned Python service supplies fresh test keys in the process environment.
// Never use a mainnet key or a remembered seed in this disposable development node.
const raw = process.env.GG_TESTNET_ACCOUNTS;
if (!raw) throw new Error("GG_TESTNET_ACCOUNTS_REQUIRED");
const accounts = JSON.parse(raw);
if (!Array.isArray(accounts) || accounts.length !== 4 || accounts.some((a) =>
  !a || !/^0x[0-9a-f]{64}$/.test(a.privateKey) || a.balance !== "10000000000000000000000"
)) throw new Error("GG_TESTNET_ACCOUNTS_INVALID");

export default {
  networks: {
    ggtest: {
      type: "edr-simulated",
      chainType: "l1",
      chainId: 31337,
      hardfork: "cancun",
      // Ethereum header timestamps are whole seconds; fast local blocks can
      // share one timestamp. Real throughput uses a monotonic host clock.
      allowBlocksWithSameTimestamp: true,
      accounts,
      // Actual empty blocks keep the local graph alive without dummy transfers.
      // Automine remains enabled so reviewed development transfers stay quick.
      mining: { auto: true, interval: 10 },
      loggingEnabled: false,
      allowUnlimitedContractSize: false,
      throwOnTransactionFailures: true,
      throwOnCallFailures: true
    }
  }
};
