"""Linux/Android SDK launch limits, applied before exec in a separate interpreter.

Only stdlib belongs here: this file is also the isolated child entry point.
RLIMIT_DATA and RLIMIT_AS are not RSS limits or a security sandbox. No limit is
applied to the desktop, real UID's process count, or accumulated CPU lifetime.
"""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

DATA_BYTES=512*1024**2
VIRTUAL_BYTES=8*1024**3
OPEN_FILES=1024
START_SECONDS=3
_LIMITS={'Max data size':(DATA_BYTES,'bytes'),'Max address space':(VIRTUAL_BYTES,'bytes'),
         'Max open files':(OPEN_FILES,'files'),'Max core file size':(0,'bytes')}


def supported():return sys.platform.startswith(('linux','android')) and os.name=='posix'


def _parse_limits(raw,requested=None):
    found={}
    for line in raw.splitlines():
        for name,(maximum,units) in (_LIMITS if requested is None else requested).items():
            if not line.startswith(name+' '):continue
            fields=line[len(name):].split()
            if len(fields)!=3 or fields[2]!=units:raise ValueError('GG_NATIVE_LINUX_LIMIT_FORMAT')
            try:soft,hard=(int(value) for value in fields[:2])
            except ValueError:raise ValueError('GG_NATIVE_LINUX_LIMIT_UNBOUNDED') from None
            if not 0<=soft<=hard<=maximum:raise ValueError('GG_NATIVE_LINUX_LIMIT_UNBOUNDED')
            found[name]=(soft,hard)
    if set(found)!=set(_LIMITS if requested is None else requested):raise ValueError('GG_NATIVE_LINUX_LIMIT_MISSING')
    return found


def _parse_status(raw):
    fields=dict(line.split(':',1) for line in raw.splitlines() if ':' in line)
    try:
        uids=[int(value) for value in fields['Uid'].split()]
        caps=[int(fields[name].strip(),16) for name in ('CapEff','CapPrm')]
        if (len(uids)!=4 or len(set(uids))!=1 or uids[0]==0
                or any(value & (1<<24) for value in caps) or fields['NoNewPrivs'].strip()!='1'):
            raise ValueError('GG_NATIVE_LINUX_PRIVILEGE_POLICY')
    except (KeyError,ValueError):raise ValueError('GG_NATIVE_LINUX_PRIVILEGE_POLICY') from None
    return uids[0]


def _apply_limits(server_limits=None):
    if not supported():raise ValueError('GG_NATIVE_RESOURCE_POLICY_UNAVAILABLE')
    import resource
    # No threaded-parent preexec_fn. This isolated launcher has one thread and
    # execs the SDK with the same PID/session, before any private stdin is read.
    version=os.uname().release.split('-',1)[0].split('.')
    if tuple(int(value) for value in version[:2])<(4,7):raise ValueError('GG_NATIVE_LINUX_KERNEL_TOO_OLD')
    status=Path('/proc/self/status').read_text(encoding='ascii')
    fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
    if (os.getuid()==0 or os.geteuid()!=os.getuid() or os.getsid(0)!=os.getpid()
            or any(int(fields[name].strip(),16)&(1<<24) for name in ('CapEff','CapPrm'))):
        raise ValueError('GG_NATIVE_LINUX_PRIVILEGE_POLICY')
    libc=ctypes.CDLL(None,use_errno=True)
    libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    libc.prctl.restype=ctypes.c_int
    if libc.prctl(38,1,0,0,0)!=0:raise OSError('GG_NATIVE_LINUX_NO_NEW_PRIVILEGES')
    data,space,files=(DATA_BYTES,VIRTUAL_BYTES,OPEN_FILES) if server_limits is None else server_limits
    requested={'Max data size':(data,'bytes'),'Max address space':(space,'bytes'),
        'Max open files':(files,'files'),'Max core file size':(0,'bytes')}
    for kind,maximum in ((resource.RLIMIT_DATA,data),(resource.RLIMIT_AS,space),
                         (resource.RLIMIT_NOFILE,files),(resource.RLIMIT_CORE,0)):
        soft,hard=resource.getrlimit(kind)
        bound=min(value for value in (maximum,soft,hard) if value!=resource.RLIM_INFINITY)
        resource.setrlimit(kind,(bound,bound))
    actual=_parse_limits(Path('/proc/self/limits').read_text(encoding='ascii'),requested)
    if server_limits is not None and any(actual[name]!=(cap,cap) for name,(cap,_) in requested.items()):
        raise ValueError('GG_NATIVE_SERVER_INHERITED_LIMIT_TOO_SMALL')
    _parse_status(Path('/proc/self/status').read_text(encoding='ascii'))


ARCHIVE_ARGUMENTS=('financial-history-export','financial-history-verify','financial-history-restore','financial-observer-restore','protocol-transport','financial-owned-restore-start','protocol-owned-start')


def launch(binary,*,cwd,env,arguments=(),resources=None):
    if not supported():raise ValueError('GG_NATIVE_RESOURCE_POLICY_UNAVAILABLE')
    if (not isinstance(arguments,(tuple,list)) or len(arguments)>1
            or arguments and (type(arguments[0]) is not str or arguments[0] not in ARCHIVE_ARGUMENTS)):
        raise ValueError('GG_NATIVE_LINUX_LAUNCH_ARGUMENTS')
    from backend.gg_native_resources import resolve
    selected=resolve(resources)
    envelope=[] if selected.mode=='LOW' else ['--gg-server-limits='+','.join(map(str,(selected.process_memory_bytes,selected.virtual_bytes,selected.open_files)))]
    return subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),str(binary),*arguments,*envelope],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        cwd=cwd,env=env,start_new_session=True)


class LinuxNativeLease:
    def __init__(self,process,facts):self._process=process;self._facts=facts;self._closed=False
    @property
    def facts(self):return {**self._facts,'verified':not self._closed and self._process.poll() is None}
    @property
    def closed(self):return self._closed
    def close(self):
        self._closed=True
        try:
            if self._process.poll() is None:self._process.kill()
            self._process.wait(timeout=3)
        except ProcessLookupError:pass
        except subprocess.TimeoutExpired:raise RuntimeError('GG_NATIVE_CHILD_STOP_FAILED') from None


def contain(process,*,cancelled,resources=None):
    from backend.gg_native_resources import resolve
    selected=resolve(resources)
    requested=None if selected.mode=='LOW' else {'Max data size':(selected.process_memory_bytes,'bytes'),
        'Max address space':(selected.virtual_bytes,'bytes'),'Max open files':(selected.open_files,'files'),
        'Max core file size':(0,'bytes')}
    if not supported():raise ValueError('GG_NATIVE_RESOURCE_POLICY_UNAVAILABLE')
    deadline=time.monotonic()+START_SECONDS
    while True:
        if cancelled():raise ValueError('GG_NATIVE_OWNER_CLOSED_OR_UNOWNED')
        if process.poll() is not None:raise ValueError('GG_NATIVE_CHILD_NOT_RUNNING')
        try:
            root=Path('/proc')/str(process.pid)
            actual=_parse_limits((root/'limits').read_text(encoding='ascii'),requested)
            if requested is not None and any(actual[name]!=(cap,cap) for name,(cap,_) in requested.items()):
                raise ValueError('GG_NATIVE_SERVER_INHERITED_LIMIT_TOO_SMALL')
            uid=_parse_status((root/'status').read_text(encoding='ascii'))
            if uid!=os.getuid() or os.getsid(process.pid)!=process.pid:
                raise ValueError('GG_NATIVE_LINUX_CHILD_IDENTITY')
            if process.poll() is not None:raise ValueError('GG_NATIVE_CHILD_NOT_RUNNING')
            return LinuxNativeLease(process,{'provider':'LINUX_RLIMIT','memory_bytes':None,
                'data_bytes':actual['Max data size'][0],'virtual_address_bytes':actual['Max address space'][0],
                'open_files':actual['Max open files'][0],'core_bytes':actual['Max core file size'][0],
                'memory_metric':'DATA_SEGMENT_AND_VIRTUAL_ADDRESS_SPACE_NOT_RSS',
                'no_new_privileges':True,'cpu_seconds':None,'active_process_limit':None,
                'kill_on_close':True,'kill_on_close_scope':'EXACT_OWNED_PROCESS',
                'descendant_process_limit_enforced':False,'limits_applied_before_exec':True,
                'resource_profile':selected.wire(),'owner_aggregate_memory_enforced':False,
                'owner_aggregate_memory_bytes':None})
        except (ValueError,OSError):
            if time.monotonic()>=deadline:raise ValueError('GG_NATIVE_LINUX_LIMIT_VERIFICATION_FAILED') from None
            time.sleep(.01)


def _server_argument(value):
    # Isolated launcher remains stdlib-only. Public finite numeric kernel
    # bounds arrive in argv from the validated parent, never ambient env.
    prefix='--gg-server-limits='
    if type(value) is not str or not value.startswith(prefix):raise ValueError('GG_NATIVE_RESOURCE_PROFILE')
    parts=value[len(prefix):].split(',')
    if len(parts)!=3 or any(not part.isascii() or not part.isdecimal() or str(int(part))!=part for part in parts):
        raise ValueError('GG_NATIVE_RESOURCE_PROFILE')
    data,space,files=map(int,parts)
    if (not 512*1024**2<=data<=1<<40 or not 8*1024**3<=space<=1<<44
            or space<2*data or not 1024<=files<=65536 or data%1024**2 or space%1024**2):
        raise ValueError('GG_NATIVE_RESOURCE_PROFILE')
    return data,space,files


if __name__=='__main__':
    try:
        arguments=sys.argv[2:];server_limits=None
        if arguments and arguments[-1].startswith('--gg-server-limits='):
            server_limits=_server_argument(arguments.pop())
        if not 2<=len(sys.argv)<=5 or len(arguments)>1 or arguments and arguments[0] not in ARCHIVE_ARGUMENTS:
            raise ValueError('GG_NATIVE_LINUX_LAUNCH_ARGUMENTS')
        _apply_limits(server_limits)
        os.execve(sys.argv[1],[sys.argv[1],*arguments],os.environ)
    except Exception:
        # No command argument, environment, key, profile or exception detail.
        os.write(2,b'GG_NATIVE_LINUX_LAUNCH_FAILED\n')
        os._exit(1)
