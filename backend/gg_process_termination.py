"""Terminal proof for an already owned Popen; never searches or opens a PID.

A Windows exit status can precede the process object's signaled state, and
Popen.wait may trust its cached returncode. Borrow the Popen's existing handle
and require the kernel signal within the caller's unchanged finite timeout.
This module does not close that borrowed handle, stop a process or grant access.
"""
import os
import subprocess
import time

_WINDOWS=os.name=='nt'
if _WINDOWS:import _winapi


def wait_process_terminal(process,timeout):
    if not _WINDOWS:return process.wait(timeout=timeout)
    deadline=time.monotonic()+max(0,timeout)
    try:handle=process._handle
    except AttributeError:raise OSError('GG_PROCESS_OWNED_HANDLE_UNAVAILABLE') from None
    # Round down to remain within the requested budget; never add a grace
    # interval or let cached Popen.returncode skip the kernel wait.
    milliseconds=min(0xfffffffe,max(0,int((deadline-time.monotonic())*1000)))
    result=_winapi.WaitForSingleObject(handle,milliseconds)
    if result==_winapi.WAIT_TIMEOUT:raise subprocess.TimeoutExpired('owned process',timeout)
    if result!=_winapi.WAIT_OBJECT_0:raise OSError('GG_PROCESS_TERMINAL_WAIT_FAILED')
    code=_winapi.GetExitCodeProcess(handle)
    process.returncode=code
    return code


def process_terminal(process):
    try:wait_process_terminal(process,0)
    except subprocess.TimeoutExpired:return False
    return True
