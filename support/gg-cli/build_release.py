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
crypto_keys crypto_pump_accounts domain_merkle gg_block_graph gg_consensus gg_dag_hardware gg_dag_wire gg_ed25519 gg_lan_dag gg_lan_test_tokens gg_parallel_dag
gg_testnet_process kaspa_address live_mandate_store marketplace_contract network_profiles
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
GO_FILES = ('go.mod', 'go.sum', 'toolchain.json', 'install_toolchain.py', 'README.md', 'benchmark.py')


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
             project/'knowledge/dagoblin-launch-readiness.md', project/'knowledge/dagoblin-lan.md', project/'support/dagoblin/analyze.py',
             project/'support/dagoblin/README.md', project/'support/dagoblin/capacity.example.json']
    paths.extend(project/'knowledge/research/dagoblin'/name for name in (
        'README.md', 'kaspa-ghostdag-dagknight.md', 'kaspa-primary-sources.json',
        'tooling-code-audit.md', 'security-neighbor-merkle.md', 'consensus-comparison.md',
        'quantum-and-layers.md', 'dagoblin-v0-spec.md', 'benchmark-contract.json',
        'broader-primary-sources.json'))
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
    paths.extend(consensus/name for name in GO_FILES)
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
        'platform_validation': {'windows':'WINDOWS_LOCAL_SOFTWARE_AND_OWNED_LOOPBACK',
            'linux':'SOURCE_ONLY_CURRENT_LAN_RUNTIME_NOT_TESTED',
            'termux':'SOURCE_ONLY_PHYSICAL_PHONE_NOT_TESTED'}[platform],
        'public_network_readiness': {'testnet':False,'mainnet':False,'mainnet_enabled':False,
            'source':'backend/network_profiles.py','current_dag_scope':'LOCAL_ASYNC_AND_OPT_IN_PRIVATE_LAN_DAG_TEST_TRANSACTIONS_NO_CANONICAL_FINALITY',
            'dag_transaction_test_mode':'PRODUCER_OWNED_NONFINANCIAL',
            'dag_stress_requires_three_signed_opt_ins':True,
            'high_throughput_target_verified':False,
            'optional_test_token_settlement':'SINGLE_PAIRED_COORDINATOR',
            'financial_transactions_enabled':False,
            'physical_three_device_lan_verified':False},
        'platform_validation_scope': {
            'windows':'LOCAL_UNIT_SOFTWARE_QML_AND_OWNED_LOOPBACK_TESTS_NATIVE_PERFORMANCE_NOT_REVALIDATED',
            'linux':'HISTORICAL_V11_V13_BASELINE_CURRENT_READINESS_AND_ASYNC_SOURCE_REQUIRE_NEW_LINUX_RUNTIME_VALIDATION',
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
