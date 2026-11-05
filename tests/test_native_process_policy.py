"""Actual owned process/job checks; no user application is assigned or stopped."""
import ctypes
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_native_process_policy as policy,gg_testnet_process as finite
from backend import gg_node_store as nodes,portable_wallet_vault as vault


class NativeProcessPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-owned-native-policy-');self.addCleanup(self.temp.cleanup)
        scope=patch.object(nodes,'ROOT',Path(self.temp.name)/'owners');scope.start();self.addCleanup(scope.stop)
        session=vault.session('public native process policy fixture');session.__enter__();self.addCleanup(session.__exit__,None,None,None)
        self.owners=[];self.addCleanup(self.close_owners)

    def close_owners(self):
        for owner in reversed(self.owners):owner.close()

    def owner(self,name='Owner'):
        owner=nodes.NodeProfile.create(name,{'label':name,'host':'127.0.0.1','port':0,'allowed_cidr':'127.0.0.0/8',
            'trusted_coordinator':None,'allow_test_tokens':False,'allow_dag_transactions':True})
        self.owners.append(owner);return owner

    def child(self,source='import time;time.sleep(30)'):
        if os.name!='nt':
            from backend.gg_posix_native import launch
            executable=Path(self.temp.name)/('child-'+str(len(list(Path(self.temp.name).glob('child-*')))))
            executable.write_text('#!'+sys.executable+'\n'+source+'\n',encoding='utf-8');executable.chmod(0o700)
            child=launch(executable,cwd=self.temp.name,env=os.environ.copy())
            self.addCleanup(finite._stop_owned,child);return child
        child=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c',source],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.addCleanup(finite._stop_owned,child);return child

    def lease(self,child,owner):
        result=policy.contain_owned_native(child,owner);self.addCleanup(result.close);return result

    def test_persistent_policy_has_no_lifetime_cpu_expiration_and_reports_actual_platform(self):
        owner=self.owner();child=self.child();lease=self.lease(child,owner);facts=lease.facts
        self.assertEqual(facts['mode'],'OWNED_PERSISTENT_NATIVE');self.assertIsNone(facts['cpu_seconds'])
        self.assertIsNone(facts['group']['lifetime_cpu_seconds'])
        if os.name=='nt':
            self.assertTrue(facts['verified']);self.assertTrue(facts['group']['verified'])
            self.assertEqual(facts['memory_bytes'],512*1024**2);self.assertEqual(facts['active_process_limit'],1)
            self.assertEqual(facts['group']['cpu_rate_percent'],100);self.assertEqual(facts['group']['maximum_native_children'],6)
            actual=finite._ExtendedLimits();group=lease._group
            self.assertTrue(group._kernel.QueryInformationJobObject(group._job,9,ctypes.byref(actual),ctypes.sizeof(actual),None))
            self.assertFalse(actual.basic.flags & (finite._PROCESS_TIME|0x4))
            parent_member=ctypes.wintypes.BOOL()
            self.assertTrue(group._kernel.IsProcessInJob(group._kernel.GetCurrentProcess(),group._job,ctypes.byref(parent_member)))
            self.assertFalse(parent_member.value)
        else:
            self.assertTrue(facts['verified']);self.assertTrue(facts['group']['verified'])
            self.assertEqual(facts['provider'],'LINUX_RLIMIT')
            self.assertEqual(facts['data_bytes'],512*1024**2)
            self.assertEqual(facts['group']['child_count_enforcement'],'APPLICATION_REGISTRY')
            self.assertIsNone(facts['memory_bytes']);self.assertIsNone(facts['group']['cpu_rate_percent'])
        self.assertIsNone(child.poll())

    @unittest.skipUnless(os.name=='nt','Native Windows group/leaf lifetime')
    def test_leaf_stop_preserves_sibling_and_owner_close_kills_both_owned_scopes_only(self):
        owner=self.owner();other=self.owner('Other');first=self.child();second=self.child();unrelated=self.child()
        one=self.lease(first,owner);two=self.lease(second,owner);outside=self.lease(unrelated,other)
        self.assertIs(one._group,two._group);self.assertIsNot(one._group,outside._group)
        one.close();first.wait(timeout=5);self.assertIsNone(second.poll());self.assertIsNone(unrelated.poll())
        owner.close();second.wait(timeout=5);self.assertIsNone(unrelated.poll())
        self.assertFalse(two.facts['group']['verified']);self.assertTrue(outside.facts['group']['verified'])

    @unittest.skipUnless(os.name=='nt','Actual Windows assignment with membership-readback failure')
    def test_successful_assignment_retains_child_before_membership_query_can_fail(self):
        import _winapi
        child=self.child();handle=child._handle
        group=policy._Group(policy.DEFAULT_CPU_PERCENT);self.addCleanup(group.close)
        kernel=group._kernel;observed=[];case=self
        class FailedMembershipQuery:
            def __getattr__(self,name):return getattr(kernel,name)
            def IsProcessInJob(self,child_handle,job,result):
                # Assignment is REAL. Only its following readback result is
                # faulted. The exact Popen must already be retained here.
                actual=ctypes.wintypes.BOOL()
                case.assertTrue(kernel.IsProcessInJob(child_handle,job,ctypes.byref(actual)))
                case.assertTrue(actual.value);case.assertIn(child,group._children)
                observed.append(True);return False
        with patch.object(group,'_kernel',FailedMembershipQuery()):
            with self.assertRaisesRegex(RuntimeError,'^GG_NATIVE_GROUP_MEMBERSHIP_FAILED$'):
                group.attach(child)
        self.assertEqual(observed,[True]);self.assertIn(child,group._children)
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
        group.close()
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)
        self.assertIs(child._handle,handle);self.assertEqual(group._children,set())
        self.assertIsNone(group._job)

    @unittest.skipUnless(os.name=='nt','Failed Windows assignment must not acquire a child')
    def test_failed_assignment_does_not_record_or_stop_an_unassigned_child(self):
        import _winapi
        child=self.child();handle=child._handle
        group=policy._Group(policy.DEFAULT_CPU_PERCENT);self.addCleanup(group.close)
        kernel=group._kernel
        class FailedAssignment:
            def __getattr__(self,name):return getattr(kernel,name)
            def AssignProcessToJobObject(self,*unused):return False
        with patch.object(group,'_kernel',FailedAssignment()):
            with self.assertRaisesRegex(RuntimeError,'^GG_NATIVE_GROUP_ASSIGN_FAILED$'):
                group.attach(child)
        self.assertNotIn(child,group._children)
        actual=ctypes.wintypes.BOOL()
        self.assertTrue(kernel.IsProcessInJob(child._handle,group._job,ctypes.byref(actual)))
        self.assertFalse(actual.value)
        group.close()
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
        # The existing exact-owned child cleanup terminates it after the
        # assertion; group close must not target a child it never acquired.

    @unittest.skipUnless(os.name=='nt','Native Windows aggregate CPU-rate query')
    def test_cpu_rate_update_is_one_shared_queried_group_budget(self):
        owner=self.owner();a=self.child();b=self.child();one=self.lease(a,owner);two=self.lease(b,owner)
        result=policy.set_owner_cpu_percent(owner,37.5)
        self.assertEqual(result['cpu_rate_percent'],37.5);self.assertEqual(one.facts['group'],two.facts['group'])
        actual=policy._CpuRate();group=one._group
        self.assertTrue(group._kernel.QueryInformationJobObject(group._job,15,ctypes.byref(actual),ctypes.sizeof(actual),None))
        self.assertEqual(actual.flags,5);self.assertEqual(actual.rate,3750)
        for value in (0,-1,True,101,float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):policy.set_owner_cpu_percent(owner,value)
        self.assertEqual(two.facts['group']['cpu_rate_percent'],37.5)

    @unittest.skipUnless(os.name=='nt','Native Windows child memory/process bounds')
    def test_memory_and_descendant_limits_remain_on_each_persistent_child(self):
        owner=self.owner()
        memory=self.child('import time;time.sleep(.4); chunks=[]\ntry:\n for _ in range(80):chunks.append(bytearray(8*1024*1024))\nexcept MemoryError:raise SystemExit(73)\nraise SystemExit(74)')
        self.lease(memory,owner);self.assertEqual(memory.wait(timeout=12),73)
        descendant=self.child('import subprocess,sys,time;time.sleep(.4)\ntry:\n c=subprocess.Popen([sys.executable,"-I","-c","pass"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);r=c.wait()\nexcept OSError:raise SystemExit(73)\nraise SystemExit(73 if r else 74)')
        self.lease(descendant,owner);self.assertEqual(descendant.wait(timeout=8),73)

    @unittest.skipUnless(os.name=='nt','Native Windows CPU-rate failure containment')
    def test_unknown_cpu_update_outcome_stops_only_this_owners_children(self):
        owner=self.owner();other=self.owner('Other');child=self.child();outside=self.child()
        lease=self.lease(child,owner);self.lease(outside,other);group=lease._group;kernel=group._kernel
        class FailedRateQuery:
            def __getattr__(self,name):return getattr(kernel,name)
            def QueryInformationJobObject(self,_job,kind,*args):
                return False if kind==15 else kernel.QueryInformationJobObject(_job,kind,*args)
        with patch.object(group,'_kernel',FailedRateQuery()),self.assertRaisesRegex(RuntimeError,'CPU_RATE_QUERY_FAILED'):
            policy.set_owner_cpu_percent(owner,25)
        child.wait(timeout=5);self.assertIsNone(outside.poll())
        self.assertFalse(lease.facts['group']['verified']);self.assertIsNone(lease.facts['group']['cpu_rate_percent'])

    def test_unowned_closed_or_ended_owner_cannot_attach_a_child(self):
        child=self.child()
        with self.assertRaisesRegex(ValueError,'OWNER_CLOSED_OR_UNOWNED'):policy.contain_owned_native(child,object())
        child.wait(timeout=5)
        owner=self.owner();owner.close();second=self.child()
        with self.assertRaisesRegex(ValueError,'OWNER_CLOSED_OR_UNOWNED'):policy.contain_owned_native(second,owner)
        second.wait(timeout=5)
        with self.assertRaisesRegex(ValueError,'OWNED_CHILD_REQUIRED'):policy.contain_owned_native(object(),owner)

    def test_child_cannot_gain_a_second_owner_or_second_lease(self):
        owner=self.owner();other=self.owner('Other');child=self.child();lease=self.lease(child,owner)
        for candidate in (owner,other):
            with self.subTest(candidate=candidate),self.assertRaisesRegex(ValueError,'CHILD_ALREADY_ATTACHED'):
                policy.contain_owned_native(child,candidate)
        self.assertIsNone(child.poll());self.assertFalse(lease.closed)

    @unittest.skipUnless(os.name=='nt','Native Windows aggregate native child ceiling')
    def test_owner_native_child_ceiling_rejects_seventh_without_stopping_siblings(self):
        owner=self.owner();children=[self.child() for _ in range(6)]
        for child in children:self.lease(child,owner)
        excess=self.child()
        with self.assertRaisesRegex(RuntimeError,'GROUP_ASSIGN_FAILED'):policy.contain_owned_native(excess,owner)
        excess.wait(timeout=5);self.assertTrue(all(child.poll() is None for child in children))
        owner.close()
        for child in children:child.wait(timeout=5)

    @unittest.skipUnless(os.name=='nt','Native Windows parent-death lifetime')
    def test_parent_death_closes_persistent_group_and_leaf_without_python_cleanup(self):
        source='\n'.join((
            'import os,subprocess,sys',
            'from pathlib import Path',
            'from backend import gg_node_store as nodes',
            'from backend.gg_native_process_policy import contain_owned_native',
            'nodes.ROOT=Path(sys.argv[1])',
            'owner=nodes.NodeProfile.create("ParentOwner",{"label":"parent fixture","host":"127.0.0.1","port":0,"allowed_cidr":"127.0.0.0/8","trusted_coordinator":None,"allow_test_tokens":False,"allow_dag_transactions":True})',
            'child=subprocess.Popen([getattr(sys,"_base_executable",sys.executable),"-I","-c","import time;time.sleep(30)"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)',
            'lease=contain_owned_native(child,owner)',
            'print(child.pid,flush=True)',
            'os._exit(0)'))
        parent=subprocess.Popen([sys.executable,'-c',source,str(Path(self.temp.name)/'parent-owners')],
            cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(finite._stop_owned,parent)
        output,_=parent.communicate(timeout=8);self.assertEqual(parent.returncode,0)
        child_pid=int(output.strip())
        import psutil,time
        deadline=time.monotonic()+3
        while psutil.pid_exists(child_pid) and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(psutil.pid_exists(child_pid),'owned persistent child survived parent/job handle death')


if __name__=='__main__':unittest.main()
