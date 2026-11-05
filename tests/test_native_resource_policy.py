"""Actual kernel readback for finite SERVER profiles, within old test budgets."""
import ctypes
import os
import unittest

from backend import gg_native_resources as resources
from backend import gg_native_process_policy as policy,gg_testnet_process as finite
from tests.test_native_process_policy import NativeProcessPolicyTests as ExistingFixture


class NativeServerKernelPolicyTests(unittest.TestCase):
    setUp=ExistingFixture.setUp
    close_owners=ExistingFixture.close_owners
    owner=ExistingFixture.owner
    child=ExistingFixture.child

    def server(self,**changes):
        value=dict(mode="SERVER",go_max_procs=32,verify_workers=32,go_heap_bytes=256*resources.MiB,
            process_memory_bytes=512*resources.MiB,virtual_bytes=8*resources.GiB,open_files=1024,
            owner_memory_bytes=1024*resources.MiB,owner_cpu_basis_points=5000,maximum_native_children=2)
        value.update(changes)
        return resources.NativeResources(**value)

    def attach(self,child,owner,profile):
        lease=policy.contain_owned_native(child,owner,resources=profile)
        self.addCleanup(lease.close)
        return lease

    def test_server_kernel_readback_preserves_exact_leaf_and_honest_platform_scope(self):
        selected=self.server();owner=self.owner();child=self.child()
        lease=self.attach(child,owner,selected);facts=lease.facts;group=facts["group"]
        self.assertTrue(facts["verified"]);self.assertTrue(group["verified"])
        self.assertEqual(facts["resource_profile"],selected.wire())
        self.assertEqual(group["resource_profile"],selected.wire())
        self.assertIsNone(facts["cpu_seconds"]);self.assertIsNone(group["lifetime_cpu_seconds"])
        if os.name=="nt":
            self.assertEqual(facts["memory_bytes"],512*resources.MiB)
            self.assertEqual(facts["active_process_limit"],1)
            self.assertEqual(group["owner_aggregate_memory_bytes"],1024*resources.MiB)
            self.assertTrue(group["owner_aggregate_memory_enforced"])
            self.assertEqual(group["cpu_rate_percent"],50)
            actual=finite._ExtendedLimits();handle=lease._group
            self.assertTrue(handle._kernel.QueryInformationJobObject(handle._job,9,
                ctypes.byref(actual),ctypes.sizeof(actual),None))
            self.assertEqual(actual.job_memory,selected.owner_memory_bytes)
            self.assertEqual(actual.basic.active_processes,2)
            self.assertTrue(actual.basic.flags & 0x200)
            self.assertFalse(actual.basic.flags & (finite._PROCESS_TIME|0x4))
        else:
            self.assertEqual(facts["data_bytes"],512*resources.MiB)
            self.assertEqual(facts["virtual_address_bytes"],8*resources.GiB)
            self.assertEqual(facts["open_files"],1024)
            self.assertFalse(group["owner_aggregate_memory_enforced"])
            self.assertIsNone(group["owner_aggregate_memory_bytes"])
            self.assertIsNone(group["cpu_rate_percent"])
            self.assertEqual(group["child_count_enforcement"],"APPLICATION_REGISTRY")
        self.assertIsNone(child.poll())

    def test_live_owner_cannot_switch_or_quietly_widen_profile_and_sibling_survives(self):
        owner=self.owner();selected=self.server();first=self.child()
        original=self.attach(first,owner,selected)
        excess=self.child();changed=self.server(owner_memory_bytes=2048*resources.MiB)
        with self.assertRaisesRegex(ValueError,"OWNER_RESOURCE_PROFILE_CHANGED"):
            policy.contain_owned_native(excess,owner,resources=changed)
        excess.wait(timeout=5);self.assertIsNone(first.poll())
        self.assertEqual(original.facts["group"]["resource_profile"],selected.wire())
        second=self.child();self.attach(second,owner,selected)
        third=self.child()
        with self.assertRaises((ValueError,RuntimeError)):policy.contain_owned_native(third,owner,resources=selected)
        third.wait(timeout=5)
        self.assertIsNone(first.poll());self.assertIsNone(second.poll())
        owner.close();first.wait(timeout=5);second.wait(timeout=5)

    @unittest.skipUnless(os.name=="nt","Actual queried Windows aggregate CPU cap")
    def test_server_cpu_update_cannot_exceed_selected_cap(self):
        owner=self.owner();child=self.child();lease=self.attach(child,owner,self.server())
        with self.assertRaisesRegex(ValueError,"CPU_RATE_PROFILE_LIMIT"):policy.set_owner_cpu_percent(owner,50.01)
        self.assertIsNone(child.poll());self.assertEqual(lease.facts["group"]["cpu_rate_percent"],50)
        self.assertEqual(policy.set_owner_cpu_percent(owner,25)["cpu_rate_percent"],25)


if __name__=="__main__":unittest.main()
