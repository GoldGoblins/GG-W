"""SDK derivation scope cannot be silently widened or reordered."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class SDKLifecyclePatchScopeTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('gg_sdk_lifecycle_scope',ROOT/'support/gg-consensus/sdk_overlay.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.records=self.module.patch_records()

    def test_exact_order_cannot_skip_cancel_or_inject_a_different_sdk_operation(self):
        for index in range(2,len(self.records)):
            changed=deepcopy(self.records);changed[index]['new']='return nil'
            with self.subTest(index=index),self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):self.module.validate_scope(changed)
        reordered=deepcopy(self.records);reordered[2],reordered[3]=reordered[3],reordered[2]
        with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):self.module.validate_scope(reordered)

    def test_duplicate_transform_or_unreviewed_record_fields_cannot_pass(self):
        changed=deepcopy(self.records);changed[3]=deepcopy(changed[2])
        with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):self.module.validate_scope(changed)
        changed=deepcopy(self.records);changed[-1]['caller_verified']=True
        with self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):self.module.validate_scope(changed)

    def test_all_hunks_remain_on_one_pinned_module_with_consistent_tree_identity(self):
        for field in ('module','version','upstream_h1','patched_h1'):
            changed=deepcopy(self.records);changed[-1][field]='foreign'
            with self.subTest(field=field),self.assertRaisesRegex(RuntimeError,'PATCH_SCOPE'):self.module.validate_scope(changed)


if __name__=='__main__':unittest.main()
