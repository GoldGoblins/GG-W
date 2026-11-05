"""Platform-neutral validation of Linux kernel readback; actual exec in Linux gate."""
import unittest
from unittest.mock import patch
from backend import gg_posix_native as policy


def limits(data='536870912',space='8589934592',files='1024',core='0'):
    return '\n'.join((f'Max data size             {data} {data} bytes',
        f'Max address space         {space} {space} bytes',
        f'Max open files            {files} {files} files',
        f'Max core file size        {core} {core} bytes'))


class PosixNativeReadbackTests(unittest.TestCase):
    def test_owned_archive_modes_keep_the_resource_launcher_and_reject_arbitrary_arguments(self):
        with patch.object(policy,'supported',return_value=True),patch.object(policy.subprocess,'Popen') as spawn:
            for mode in ('financial-history-verify','financial-observer-restore'):
                policy.launch('/public/test-binary',cwd='/public',env={},arguments=(mode,))
                self.assertEqual(spawn.call_args.args[0][-2:],['/public/test-binary',mode])
                self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            for value in ('financial-history-verify',('--help',),('financial-history-verify','another'),(True,)):
                with self.assertRaisesRegex(ValueError,'GG_NATIVE_LINUX_LAUNCH_ARGUMENTS'):
                    policy.launch('/public/test-binary',cwd='/public',env={},arguments=value)
    def test_kernel_limits_are_finite_hard_bounds_and_preserve_stricter_limits(self):
        result=policy._parse_limits(limits(data='402653184',files='512'))
        self.assertEqual(result['Max data size'],(402653184,402653184))
        self.assertEqual(result['Max open files'],(512,512))
        self.assertEqual(result['Max core file size'],(0,0))

    def test_unbounded_excess_missing_or_wrong_units_cannot_claim_limits(self):
        for value in ('unlimited','-1','536870913','nan'):
            with self.subTest(value=value),self.assertRaises(ValueError):policy._parse_limits(limits(data=value))
        for raw in (limits(core='1'),limits().replace('bytes','files'),limits().split('\n',1)[1],
                    limits().replace('536870912 536870912','536870912 402653184')):
            with self.subTest(raw=raw),self.assertRaises(ValueError):policy._parse_limits(raw)

    def test_root_privilege_capability_and_missing_no_new_privileges_rejected(self):
        valid='Uid:\t1000 1000 1000 1000\nCapEff:\t0\nCapPrm:\t0\nNoNewPrivs:\t1\n'
        self.assertEqual(policy._parse_status(valid),1000)
        for raw in (valid.replace('1000','0'),valid.replace('1000 1000 1000 1000','1000 0 1000 1000'),
                    valid.replace('CapEff:\t0','CapEff:\t1000000'),
                    valid.replace('CapPrm:\t0','CapPrm:\t1000000'),
                    valid.replace('NoNewPrivs:\t1','NoNewPrivs:\t0'),valid.replace('CapEff:\t0\n','')):
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'PRIVILEGE_POLICY'):policy._parse_status(raw)


if __name__=='__main__':unittest.main()
