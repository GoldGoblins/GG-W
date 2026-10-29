"""Repeated protected Windows reads must not retain fresh ctypes ABI classes."""
import ctypes
import gc
import os
from pathlib import Path
import tempfile
import unittest

from backend import platform_files as files


class PlatformFileTests(unittest.TestCase):
    def test_regular_file_exclusive_append_truncate_and_no_inheritance(self):
        with tempfile.TemporaryDirectory(prefix='gg-protected-file-test-') as temporary:
            path=Path(temporary)/'fixture'
            descriptor=files.secure_open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            self.assertFalse(os.get_inheritable(descriptor))
            os.write(descriptor,b'public fixture');os.close(descriptor)
            with self.assertRaises(FileExistsError):files.secure_open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
            descriptor=files.secure_open(path,os.O_WRONLY|os.O_APPEND)
            os.write(descriptor,b' appended');os.close(descriptor)
            self.assertEqual(path.read_bytes(),b'public fixture appended')
            descriptor=files.secure_open(path,os.O_WRONLY|os.O_TRUNC)
            os.close(descriptor);self.assertEqual(path.read_bytes(),b'')
            self.assertTrue(files.owned_by_current_user(path))
            self.assertTrue(files.mode_matches(path,0o600))

    @unittest.skipUnless(os.name=='nt','Windows ctypes pointer-cache regression')
    def test_ten_thousand_reads_reuse_abi_types_and_close_handles(self):
        import psutil
        with tempfile.TemporaryDirectory(prefix='gg-protected-file-churn-') as temporary:
            path=Path(temporary)/'fixture';path.write_bytes(b'public fixture')
            for _ in range(3):os.close(files.secure_open(path,os.O_RDONLY))
            gc.collect();before=set(ctypes._pointer_type_cache);handles=psutil.Process().num_handles()
            for _ in range(10000):
                descriptor=files.secure_open(path,os.O_RDONLY)
                os.close(descriptor)
            gc.collect()
            self.assertEqual(set(ctypes._pointer_type_cache),before)
            self.assertLessEqual(psutil.Process().num_handles(),handles+2)
            self.assertEqual(ctypes.sizeof(files._FileInformation),52)
            self.assertEqual(ctypes.sizeof(files._SecurityAttributes),24 if ctypes.sizeof(ctypes.c_void_p)==8 else 12)

    def test_broad_permissions_are_rejected_then_private_mode_restored(self):
        with tempfile.TemporaryDirectory(prefix='gg-protected-mode-test-') as temporary:
            path=Path(temporary)/'public-fixture';path.write_bytes(b'public fixture')
            if os.name=='nt':
                from ctypes import wintypes
                security=ctypes.WinDLL('advapi32',use_last_error=True)
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
                security.SetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p]
                kernel.LocalFree.argtypes=[ctypes.c_void_p]
                descriptor=ctypes.c_void_p()
                self.assertTrue(security.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;FA;;;WD)',1,ctypes.byref(descriptor),None))
                try:self.assertTrue(security.SetFileSecurityW(str(path),0x80000004,descriptor))
                finally:kernel.LocalFree(descriptor)
            else:os.chmod(path,0o666)
            self.assertFalse(files.mode_matches(path,0o600))
            files.set_private_mode(path,0o600)
            self.assertTrue(files.mode_matches(path,0o600))

    def test_symlink_or_reparse_target_is_never_truncated(self):
        with tempfile.TemporaryDirectory(prefix='gg-protected-link-test-') as temporary:
            target=Path(temporary)/'target';target.write_bytes(b'preserve fixture')
            link=Path(temporary)/'link'
            try:link.symlink_to(target)
            except OSError as error:self.skipTest('Host does not permit fixture symlinks: '+str(error.errno))
            with self.assertRaises(OSError):files.secure_open(link,os.O_WRONLY|os.O_TRUNC)
            self.assertEqual(target.read_bytes(),b'preserve fixture')


if __name__=='__main__':unittest.main()
