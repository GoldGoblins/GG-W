"""Native/WASM must bind the same transaction admission source, not stale code."""
import importlib.util
import hashlib
from copy import deepcopy
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
from backend import gg_consensus_web

ROOT=Path(__file__).resolve().parents[1]


class SharedVerifierBuildTests(unittest.TestCase):
    def test_light_builder_and_runtime_bind_shared_signature_admission_source(self):
        spec=importlib.util.spec_from_file_location('gg_test_light_graph',ROOT/'support/gg-consensus/install_toolchain.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        sources=installer.light_source_files()
        self.assertIn(ROOT/'support/gg-consensus/signature_profile.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_execution.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_execution_policy.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_tx_verify.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/canonical_stream.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/financial_accounts_workspace.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/canonical_financial_hex.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/financial_decoded_payments.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_proof.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_order_root.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/dag_history.go',sources)
        self.assertIn(ROOT/'support/gg-consensus/sdk_overlay.py',sources)
        self.assertIn(ROOT/'support/gg-consensus/sdk_patches.json',sources)
        self.assertEqual(installer.light_fingerprint(),gg_consensus_web._light_fingerprint())
        self.assertTrue(all(path.is_file() for path in sources))

    def overlay(self):
        spec=importlib.util.spec_from_file_location('gg_test_sdk_overlay',ROOT/'support/gg-consensus/sdk_overlay.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_local_compiler_rejects_versions_below_pinned_security_floor(self):
        spec=importlib.util.spec_from_file_location('gg_test_local_go_security_floor',ROOT/'support/gg-consensus/install_toolchain.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        local_os=SimpleNamespace(**dict(vars(installer.os),name='posix'))
        cases=[('go1.25.0',False),('go1.26.10',False),('go1.27.2',False),
            ('go1.27.3',True),('go1.27.4',True),('go1.28.0',True),('go1.27.3rc1',False),('unknown',False)]
        with tempfile.TemporaryDirectory() as directory,patch.object(installer,'os',local_os),\
                patch.object(installer.shutil,'which',return_value='owned-go'),\
                patch.object(installer,'build_environment',return_value={}),\
                patch.object(installer.subprocess,'run') as run:
            for release,accepted in cases:
                with self.subTest(release=release):
                    run.return_value=SimpleNamespace(returncode=0,stdout='go version '+release+' linux/amd64\n')
                    if accepted:self.assertEqual(installer.ensure_go(Path(directory)),Path('owned-go'))
                    else:
                        with self.assertRaisesRegex(RuntimeError,'LOCAL_GO_VERSION_REQUIRED'):installer.ensure_go(Path(directory))
            run.return_value=SimpleNamespace(returncode=1,stdout='go version go1.27.3 linux/amd64\n')
            with self.assertRaisesRegex(RuntimeError,'LOCAL_GO_VERSION_REQUIRED'):installer.ensure_go(Path(directory))

    def test_sdk_log_patch_preserves_surrounding_code_and_requires_exact_known_source(self):
        module=self.overlay();raw=b'first(ntx.String());\nsecond(ntx.String());\n'
        changed=raw.replace(b'ntx.String()',b'ntx.Hash()')
        record={'original_sha256':hashlib.sha256(raw).hexdigest(),'patched_sha256':hashlib.sha256(changed).hexdigest(),
                'old':'ntx.String()','new':'ntx.Hash()','count':2}
        self.assertEqual(module.transform(raw,record),changed)
        with self.assertRaisesRegex(RuntimeError,'SOURCE_MISMATCH'):module.transform(raw+b'changed',record)
        with self.assertRaisesRegex(RuntimeError,'MATCH_COUNT'):module.transform(raw,{**record,'count':3})
        with self.assertRaisesRegex(RuntimeError,'RESULT_MISMATCH'):module.transform(raw,{**record,'patched_sha256':'0'*64})

    def test_sdk_patch_manifest_has_narrow_resource_scope_and_keeps_sdk_version(self):
        patches=self.overlay().patch_records();self.assertEqual(len(patches),6)
        record=patches[0]
        self.assertEqual((record['module'],record['version'],record['file']),('github.com/cometbft/cometbft','v0.40.0','mempool/reactor.go'))
        self.assertEqual((record['old'],record['new'],record['count']),('ntx.String()','ntx.Hash()',2))
        self.assertEqual(patches[1]['file'],'p2p/conn/connection.go')
        self.assertIn('cap(ch.recving) > 256*1024',patches[1]['new'])
        self.assertEqual(patches[0]['patched_h1'],patches[1]['patched_h1'])

    def test_sdk_scope_rejects_duplicate_files_and_inconsistent_integrity(self):
        module=self.overlay();patches=module.patch_records();module.validate_scope(patches)
        for field in ('upstream_h1','patched_h1'):
            changed=deepcopy(patches);changed[1][field]='different'
            with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):module.validate_scope(changed)
        with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):module.validate_scope([patches[0],patches[0]])

    def test_sdk_scope_cannot_be_repurposed_to_disable_validation(self):
        module=self.overlay();patches=module.patch_records()
        for replacement in ('0','ch.desc.RecvMessageCapacity'):
            changed=deepcopy(patches);changed[1]['new']=changed[1]['new'].replace('256*1024',replacement)
            with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):module.validate_scope(changed)

    def test_explicit_cold_build_prepares_pinned_module_and_download_failure_stops_derivation(self):
        spec=importlib.util.spec_from_file_location('gg_test_cold_sdk_build',ROOT/'support/gg-consensus/install_toolchain.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        derived=Mock(return_value=['-modfile','owned-build.mod'])
        with tempfile.TemporaryDirectory() as directory:
            environment={'GOMODCACHE':directory}
            with patch.object(installer,'sdk_overlay_module',return_value=SimpleNamespace(overlay_flags=derived)),patch.object(installer.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(installer.sdk_overlay_flags(Path(directory),environment,executable='owned-go'),['-modfile','owned-build.mod'])
                self.assertEqual(run.call_args.args[0],['owned-go','mod','download','github.com/cometbft/cometbft@v0.40.0'])
                run.return_value.returncode=1
                with self.assertRaisesRegex(RuntimeError,'MODULE_DOWNLOAD_FAILED'):
                    installer.sdk_overlay_flags(Path(directory),environment,executable='owned-go')
                self.assertEqual(derived.call_count,1)


if __name__=='__main__':unittest.main()
