"""Build small headless source ZIPs from an explicit reviewed file graph."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
BACKEND = frozenset('''application_paths bitcoin_address crypto_contract crypto_explorer
crypto_keys crypto_pump_accounts domain_merkle gg_block_graph gg_consensus gg_consensus_membership gg_consensus_profile gg_consensus_node gg_consensus_process gg_native_start gg_native_resources gg_native_pipe_lifecycle gg_native_observer gg_observer_profile gg_observer_node gg_observer_enrollment gg_observer_control gg_native_process_policy gg_posix_native gg_segmented_authority gg_segmented_proof_sync gg_segmented_payloads gg_segmented_submission gg_segmented_production gg_segmented_index_transition gg_network_archive gg_network_transition gg_dag_archive gg_dag_checkpoint gg_dag_execution_policy gg_dag_segmented gg_financial_dag gg_dag_segmented_runtime gg_dag_segmented_session gg_dag_producer_journal gg_dag_producer_archive gg_dag_json gg_dag_order_history gg_dag_payloads gg_dag_proof_sync gg_dag_hardware gg_dag_wire gg_lossless_wire gg_ed25519 gg_lan_admission gg_lan_dag gg_lan_resume gg_lan_test_tokens gg_parallel_dag gg_peer_scan
gg_financial_session gg_financial_wire gg_financial_authority gg_financial_producer gg_financial_retry gg_financial_proof_sync gg_financial_own_archive gg_financial_archive gg_financial_account gg_protected_journal gg_financial_relay gg_financial_economy gg_financial_protocol gg_financial_pool gg_protocol_node gg_local_history_status gg_protocol_producer gg_protocol_runtime gg_protocol_operations gg_protocol_setup gg_protocol_provisioning gg_committee_history gg_protocol_transport gg_protocol_light gg_protocol_inbox gg_observer_recovery gg_protected_restore
gg_node_store gg_node_vault gg_testnet_process gg_process_termination kaspa_address live_mandate_store marketplace_contract network_profiles
lan_dag_runtime local_node_observation marketplace_discovery marketplace_media marketplace_protocols omni_assets
omni_discovery omni_rpc omni_wallet platform_files platform_process
platform_support portable_wallet_vault research_desk research_workbench sensitive_ui_guard
solana_metadata solana_transfers task_scoped_action_grant terminal_approval
terminal_cli terminal_service token_market_prices wallet_account_roles wallet_approval wallet_mnemonic wallet_vault'''.split())
# Desktop-only functions are not called by TerminalService. Keeping the shared
# module does not make those optional branches part of the headless interface.
OPTIONAL_EDGES = frozenset({('omni_wallet', 'omni_lab'), ('omni_wallet', 'omni_service'),
                           ('omni_rpc', 'omni_lab'), ('research_workbench', 'research_lab'),
                           ('research_desk', 'long_memory')})
FORBIDDEN = frozenset({'PySide6', 'PyQt5', 'PyQt6', 'webview', 'selenium', 'playwright', 'cefpython3'})
HELPERS = ('README.md', 'repository-README.md', 'repository.gitignore', 'bootstrap.py', 'install.py', 'build_release.py', 'requirements.txt', 'requirements-wallet.txt')
INSTALL_FILES = ('windows.cmd', 'linux.sh', 'termux.sh')
GO_FILES = ('go.mod', 'go.sum', 'toolchain.json', 'install_toolchain.py', 'README.md', 'benchmark.py', 'financial_fixture.py')


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == 'backend':
                for name in node.names: yield 'backend', name.name
            elif node.module and node.module.startswith('backend.'):
                yield 'backend', node.module.split('.')[1]
            elif node.module: yield 'external', node.module.split('.')[0]
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name.startswith('backend.'): yield 'backend', name.name.split('.')[1]
                else: yield 'external', name.name.split('.')[0]


def source_files(project=PROJECT):
    project = Path(project).resolve()
    paths = [project/'gg-cli.py', project/'config/omni-networks.json', project/'config/gg-palette.json',
             project/'knowledge/token-market-pricing.md', project/'knowledge/gg-terminal-palette.md',
             project/'knowledge/gg-parallel-dag.md', project/'knowledge/gg-network-live.md',
             project/'knowledge/dagoblin-launch-readiness.md', project/'knowledge/dagoblin-lan.md',
             project/'knowledge/dagoblin-protocol-operators.md', project/'support/dagoblin/analyze.py',
             project/'support/dagoblin/prepare_protocol_ceremony.py', project/'support/dagoblin/protocol-testnet-policy.example.json',
             project/'support/dagoblin/README.md', project/'support/dagoblin/capacity.example.json']
    paths.extend(project/'knowledge/research/dagoblin'/name for name in (
        'README.md', 'kaspa-ghostdag-dagknight.md', 'kaspa-primary-sources.json',
        'tooling-code-audit.md', 'security-neighbor-merkle.md', 'consensus-comparison.md',
        'quantum-and-layers.md', 'dagoblin-v0-spec.md', 'benchmark-contract.json', 'durable-node-review-2026-10-31.md',
        'role-and-checkpoint-review-2026-10-31.md',
        'dag-consensus-binding-review-2026-10-31.md',
        'lan-consensus-anchor-review-2026-10-31.md',
        'cli-validator-review-2026-10-31.md','canonical-checkpoint-flow-review-2026-10-31.md',
        'replica-light-proof-review-2026-10-31.md',
        'native-proof-index-review-2026-10-31.md',
        'certified-conflict-review-2026-10-31.md',
        'producer-branch-review-2026-10-31.md',
        'resource-isolation-review-2026-10-31.md',
        'candidate-retention-review-2026-11-01.md',
        'sdk-payload-availability-review-2026-11-01.md',
        'payload-archive-review-2026-11-01.md','native-history-review-2026-11-01.md',
        'merkle-query-index-review-2026-11-01.md',
        'order-history-review-2026-11-01.md',
        'native-metadata-review-2026-11-01.md',
        'verification-cost-review-2026-11-01.md',
        'sdk-log-memory-review-2026-11-01.md',
        'strict-json-memory-review-2026-11-01.md',
        'resource-recovery-review-2026-11-01.md',
        'dependency-security-review-2026-11-01.md',
        'exact-equation-review-2026-11-01.md',
        'order-stream-review-2026-11-01.md',
        'incremental-transition-review-2026-11-01.md',
        'selection-index-review-2026-11-01.md',
        'parallel-tx-verification-review-2026-11-01.md',
        'indexed-replay-review-2026-11-01.md',
        'lan-resume-storage-boundary-review-2026-11-01.md',
        'history-byte-boundary-review-2026-11-01.md',
        'execution-policy-review-2026-11-01.md',
        'public-archive-review-2026-11-01.md',
        'public-history-import-review-2026-11-01.md',
        'history-cut-core-review-2026-11-01.md',
        'history-segment-archive-review-2026-11-01.md',
        'segmented-sdk-review-2026-11-01.md',
        'segmented-membership-review-2026-11-01.md',
        'observer-control-review-2026-11-02.md','native-start-review-2026-11-02.md','nonwindows-process-review-2026-11-02.md','financial-execution-review-2026-11-02.md','financial-production-review-2026-11-03.md','financial-pipeline-review-2026-11-03.md','financial-own-archive-review-2026-11-03.md','financial-history-review-2026-11-03.md','broader-primary-sources.json','delivery-contract.json',
        'financial-node-recovery-review-2026-11-03.md',
        'financial-slow-producer-review-2026-11-03.md',
        'financial-late-original-review-2026-11-03.md',
        'financial-storage-endurance-review-2026-11-03.md',
        'general-account-kernel-review-2026-11-03.md',
        'general-account-application-review-2026-11-03.md',
        'general-account-client-review-2026-11-03.md',
        'protected-account-signing-review-2026-11-03.md',
        'general-account-recovery-review-2026-11-03.md',
        'integrated-network-implementation-2026-11-03.md',
        'security-review-2026-10-31.md','security-primary-sources-2026-10-31.json'))
    for name in sorted(BACKEND):
        source = project/'backend'/(name+'.py')
        if not source.is_file() or source.is_symlink(): raise ValueError('GG_CLI_SOURCE_MISSING')
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        for kind, dependency in imports(tree):
            if kind == 'backend' and dependency not in BACKEND and (name, dependency) not in OPTIONAL_EDGES:
                raise ValueError('GG_CLI_UNREVIEWED_BACKEND_IMPORT:' + name + ':' + dependency)
            if kind == 'external' and dependency in FORBIDDEN:
                raise ValueError('GG_CLI_DESKTOP_DEPENDENCY_REFUSED:' + name)
        paths.append(source)
    paths.extend(project/'support/gg-cli'/name for name in HELPERS)
    paths.extend(project/'support/gg-cli/install'/name for name in INSTALL_FILES)
    consensus = project/'support/gg-consensus'
    paths.extend(consensus/name for name in (*GO_FILES,'sdk_overlay.py','sdk_patches.json'))
    paths.extend(sorted(consensus.glob('*.go')))
    paths.append(consensus/'light/wasm_main.go')
    # No recursive repository walk. Only these specific public source files can
    # enter the archive; state directories and installed tools are not inputs.
    for path in paths:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(project):
            raise ValueError('GG_CLI_SOURCE_PATH_INVALID')
    return tuple(sorted(set(paths), key=lambda path: path.relative_to(project).as_posix()))


def reviewed_entries(project=PROJECT):
    """Public repository projection shared by archives and explicit staging."""
    project = Path(project).resolve(); paths = source_files(project)
    entries = {path.relative_to(project).as_posix(): path.read_bytes() for path in paths}
    entries['README.md'] = entries['support/gg-cli/repository-README.md']
    entries['.gitignore'] = entries['support/gg-cli/repository.gitignore']
    entries['install.py'] = entries['support/gg-cli/install.py']
    for name in INSTALL_FILES:
        entries['install/'+name] = entries['support/gg-cli/install/'+name]
    # Namespace package marker is generated, never copied from desktop startup.
    entries['backend/__init__.py'] = b'"""GG terminal backend namespace."""\n'
    return entries


def build(platform, output_dir, project=PROJECT):
    if platform not in {'windows', 'linux', 'termux'}: raise ValueError('GG_CLI_RELEASE_PLATFORM')
    entries = reviewed_entries(project)
    manifest = {'schema': 'gg.terminal.release.v1', 'platform': platform, 'python': '>=3.10',
        'source_repository_declared_by_project': 'https://github.com/GoldGoblins/GG-CLI',
        'upstream_source_repository': 'https://github.com/GoldGoblins/GG',
        'remote_publish_performed': False, 'contents': 'HEADLESS_SOURCE_ONLY',
        'platform_validation': {'windows':'SOURCE_ARCHIVE_EXACT_RELEASE_RUNTIME_RECEIPT_REQUIRED',
            'linux':'SOURCE_ARCHIVE_EXACT_RELEASE_RUNTIME_RECEIPT_REQUIRED',
            'termux':'SOURCE_ONLY_PHYSICAL_PHONE_NOT_TESTED'}[platform],
        'public_network_readiness': {'testnet':False,'mainnet':False,'mainnet_enabled':False,
            'source':'backend/network_profiles.py','current_dag_scope':'PRIVATE_LAN_NONFINANCIAL_DAG_WITH_OPTIONAL_SDK_CERTIFIED_ORDER_AND_ACCOUNT_PROOFS',
            'optional_consensus':'FIXED_PRIVATE_4_VALIDATORS_QUORUM_3_REQUIRES_AVAILABLE_VALIDATED_PAYLOAD_AND_SDK_CERTIFICATE',
            'legacy_stress_ack_is_canonical_finality':False,
            'dag_transaction_test_mode':'PRODUCER_OWNED_NONFINANCIAL',
            'optional_financial_execution':'EXPLICIT_SIGNED_FINANCIAL_SESSIONS_V6_V7_WITH_FIXED_OR_GENERAL_PRIVATE_TEST_ACCOUNTS',
            'integrated_economy_membership_mining_round':'IMPLEMENTED_EXACT_RELEASE_RUNTIME_RECEIPT_REQUIRED_NOT_PUBLICLY_ACTIVATED',
            'integrated_protocol_v7':{'environment':'EXPLICIT_LOCAL_TESTNET_ACCEPTANCE',
                'native_fees_capped_epoch_rewards_and_pool_payouts':'IMPLEMENTED_EXACT_RELEASE_RUNTIME_RECEIPT_REQUIRED',
                'independent_governance_wallet_journals':True,
                'predecessor_quorum_and_weighted_membership':'IMPLEMENTED_EXACT_RELEASE_RUNTIME_RECEIPT_REQUIRED',
                'current_source_runtime_acceptance':'EXTERNAL_EXACT_SOURCE_RECEIPT_REQUIRED',
                'physical_or_public_network_acceptance':False},
            'operator_provisioning':{'implemented':True,'native_public_only_genesis_validation':True,
                'every_initial_voter_exact_genesis_consent':True,'protected_four_role_endorsements':True,
                'runtime_validation':'EXTERNAL_ACCEPTANCE_RECEIPT_REQUIRED_FOR_EXACT_RELEASE_SOURCE','physical_acceptance':False},
            'financial_queue_ack_is_execution':False,'financial_mining_or_pool_rewards':False,
            'dag_stress_requires_three_signed_opt_ins':True,
            'high_throughput_target_verified':False,
            'optional_test_token_settlement':'SINGLE_PAIRED_COORDINATOR',
            'financial_transactions_enabled':False,
            'physical_three_device_lan_verified':False},
        'platform_validation_scope': {
            'windows':'PLANNED_LOCAL_NATIVE_PYTHON_QML_OWNED_LOOPBACK_EXACT_SOURCE_RECEIPT_REQUIRED',
            'linux':'PLANNED_WSL_NATIVE_PYTHON_OWNED_LOOPBACK_EXACT_SOURCE_RECEIPT_REQUIRED_NO_LINUX_QML_OR_PHYSICAL_ACCEPTANCE',
            'termux':'GO_NATIVE_COMPILE_ONLY_PYTHON_RUNTIME_AND_PHYSICAL_PHONE_NOT_VERIFIED'}[platform],
        'dependencies': 'support/gg-cli/requirements.txt', 'optional_wallet_dependencies': 'support/gg-cli/requirements-wallet.txt',
        'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in sorted(entries.items())}}
    entries['TERMINAL-MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir/('gg-terminal-'+platform+'-source-v1.zip')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(entries.items()):
            item = zipfile.ZipInfo('GG-TERMINAL/'+name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED; item.external_attr = 0o100644 << 16
            archive.writestr(item, raw)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create reviewed headless source archives. No install, state copy or upload.')
    parser.add_argument('--platform', choices=('windows', 'linux', 'termux', 'all'), default='all')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    targets = ('windows', 'linux', 'termux') if args.platform == 'all' else (args.platform,)
    for platform in targets:
        archive = build(platform, args.output_dir)
        print(archive.name)
    return 0


if __name__ == '__main__': raise SystemExit(main())
