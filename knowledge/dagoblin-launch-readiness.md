# DAGoblin: tre enheter före publik drift

## Mål och ordning

Samma nätverkskod ska kunna användas i GG AI Desktop och i headless CLI för
Windows, Linux och Termux. Första integrationsprovet gäller tre faktiska
enheter på samma lokala nätverk: Windows-datorn, Linux-datorn och telefonen.
VPS, webbhotell och huvudnät kommer efter detta prov. Lokala IP-adresser och
enhetsidentiteter hör till operatörens status/konfiguration, inte källpaketet.

## Vad som redan körs

- Ägd lokal EVM med verkliga headers och transaktionskvitton.
- Lokal CometBFT-ledger med fyra validatorprocesser och verifierade 3-av-4-certifikat.
- DAGoblin med riktiga Ed25519-signerade förslag och verifierade föräldrar.
  Löpande desktop-/CLI-start använder åtta oberoende lokala producenter med
  olika takt och jitter. Åtta trådar är inte åtta externt anslutna datorer.
- Högst 128 verkliga poster i snabbgrafen. Mottagningsordning är en lokal
  visningsordning, inte ett bevis på global ordning eller slutlighet.
- Prioriterat avbrott för de två ägda snabba motorerna i desktop.
- Privat LAN-transport för exakt tre parade peers, med två egna producenter
  per peer, signerad sessionsdomän och verifierade föräldrar. Tre separata
  lokala processer används i transportprovet. Fysiska enheter är inte därmed
  verifierade. LAN-läget överför bara tomma förslag; finansiella transaktioner
  är avstängda tills det finns en gemensam stabil tillstånds-/checkpointmodell.
- Ett separat privat GG-LAN(TEST)-prov har signerade testöverföringar och
  koordinatorordnade kvitton. Alla tre peers måste uttryckligen tillåta det
  före parning. Dess saldo och kvitton är en egen testledger; de är inte
  ekonomiska tillgångar eller kanoniskt finaliserade DAG-transaktioner.
- Gemensamma TESTNET-/MAINNET-deskriptorer och skrivskyddad beredskapsrapport.
  Rapporten skapar ingen genesis, inga nycklar och inga nätanslutningar.

## Befintliga CLI-kommandon

Använd samma kommandon på alla tre plattformarna, med `python3` där den
installerade tolkens namn är det. Bootstrap är ett separat uttryckligt steg.

```text
python gg-cli.py --json --command network.readiness
python gg-cli.py --foreground --command dag.live_start
```

Det första kommandot beskriver både TESTNET och MAINNET och saknade delar.
Det andra behåller en **lokal** signerad DAG-session tills Ctrl+C. Det
exponerar ingen publik nodtjänst och är ingen beständig nätverksdaemon.

I den interaktiva terminalens egen session finns `dag.live_start`,
`dag.live_stop`, `dag.status` och `dag.stop`. Paus behåller sessionen.
Ett separat engångskommando äger en separat session och styr inte en annan
process. Engångskommandon behåller sin tidigare städning vid exit.

## Gränser som inte får döljas

| Område | Nuvarande gräns | Nästa verifierbara steg |
|---|---|---|
| Enheter | Signerad privat LAN-transport verifieras mellan tre separata lokala processer | Installation, peertrafik och återanslutning mellan de tre faktiska enheterna |
| Varierad produktion | Åtta verkliga lokala producenttrådar | Separata enheter producerar och överför egna verifierbara förslag |
| Kanonisk DAG | Ingen global ordning eller finalitet | Specificerad ordning, datatillgänglighet, exekvering och checkpoints |
| Beständig nod | Lokala sessioner och explicit foregroundläge | Beständig datamapp, återstart och operatörsägd signerare |
| Publika validatorer | Lokalt CometBFT-labb | Oberoende operatörer, identiteter, adresser och antagningsregler |
| Huvudnät | Ingen godkänd produktionsgenesis | Beslut om fördelning, utbud, avgifter, uppgraderingar och säkerhetsgranskning |
| Kvantskydd | Ed25519 är klassiskt; PQC saknas | Specificerad och granskad signatur-/migreringsprofil |
| Termux | Headless-källpaket finns | Installation och verkligt runtimeprov på telefonen |

CometBFT certifierar idag sin egen ledger, inte DAGoblins förslag. Ett
Comet-certifikat får inte användas som bevis för en ospecificerad DAG-checkpoint.
Aktuellt `PUBLIC_NOT_READY`, `runnable_public: false` och `mainnet_enabled:
false` gäller även för syntaktiskt giltig offentlig konfiguration. En
konfigurationsfil ersätter inte protokoll, implementation eller verifiering.

Efter ett lyckat prov mellan de tre enheterna kan ett publikt testnät förberedas
med konkreta operatörer och värdar. Huvudnätets genesis och produktionssignering
aktiveras först efter separat beslut och granskade testnätresultat.

[Löpande nätverk och grafik](gg-network-live.md) ·
[Privat LAN-prov](dagoblin-lan.md) ·
[Prototypens verifieringsgräns](gg-parallel-dag.md) ·
[Primärkällor och protokollstudier](research/dagoblin/README.md)
