"""Native, network-isolated AppContainer for trusted static-analysis tools.

The selected artifact is data. Only the installed tool executable is launched.
No Windows failure falls back to an ordinary, full-trust subprocess.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import zipfile

_RUN_LOCK = threading.Lock()
_JDK_FILE_SOURCE_SHA256 = '9fd5f23215e8f9f7f8f9763626a7612cf59813b6e50ed1a67313de327762ea4c'
_JDK_LINK_SOURCE_SHA256 = 'b205e8eb91c35dde7d64e39e5c1d8ae83c5a6873e94b6f8c1fefdd10a7040e8d'


def _jdk_compatibility(tools: Path, scratch: Path) -> Path | None:
    """Adapt filesystem metadata queries, retaining every actual I/O check.

    The official JDK asks the volume root for a component-name limit while
    creating temp files. AppContainer intentionally cannot open that root. The
    trusted host verifies this metadata once; the sandbox JVM uses a separately
    compiled copy of the exact vendor class with only this getter adapted.
    Canonical paths use the vendor's existing handle-based resolver first,
    retaining target-file ReadAttributes permissions and the original fallback.
    Vendor binaries and Java security settings are never modified.
    """
    java = tools / 'jdk/bin/java.exe'
    if not java.is_file():
        return None
    release = (tools / 'jdk/release').read_text(encoding='utf-8')
    if ('JAVA_VERSION="25.0.4.1"' not in release
            or 'IMPLEMENTOR="Eclipse Adoptium"' not in release):
        raise ValueError('WINDOWS_RESEARCH_JDK_COMPAT_VERSION_CHANGED')
    with zipfile.ZipFile(tools / 'jdk/lib/src.zip') as package:
        data = package.read('java.base/java/io/WinNTFileSystem.java')
        link_data = package.read('java.base/sun/nio/fs/WindowsLinkSupport.java')
    if hashlib.sha256(data).hexdigest() != _JDK_FILE_SOURCE_SHA256:
        raise ValueError('WINDOWS_RESEARCH_JDK_COMPAT_SOURCE_CHANGED')
    if hashlib.sha256(link_data).hexdigest() != _JDK_LINK_SOURCE_SHA256:
        raise ValueError('WINDOWS_RESEARCH_JDK_LINK_SOURCE_CHANGED')
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetVolumeInformationW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD,
        ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    component = w.DWORD()
    if not kernel.GetVolumeInformationW(scratch.anchor, None, 0, None,
                                       ctypes.byref(component), None, None, 0):
        raise ValueError('WINDOWS_RESEARCH_VOLUME_METADATA_UNAVAILABLE')
    if not 1 <= component.value <= 255:
        raise ValueError('WINDOWS_RESEARCH_UNSUPPORTED_COMPONENT_LIMIT')
    base = tools / 'gg-jdk-compat'
    metadata_path = base / 'compatibility.json'
    output = base / 'classes'
    class_names = ('java/io/WinNTFileSystem.class', 'sun/nio/fs/WindowsLinkSupport.class')
    expected = {'schema': 'gg.research-jdk-compat.v1', 'jdk': '25.0.4.1',
                'source_sha256': _JDK_FILE_SOURCE_SHA256, 'component_limit': component.value,
                'link_source_sha256': _JDK_LINK_SOURCE_SHA256,
                'scope': 'Filesystem metadata and handle canonicalization only; actual I/O checks unchanged'}
    try:
        recorded = json.loads(metadata_path.read_text(encoding='utf-8'))
        if (all(recorded.get(k) == v for k, v in expected.items())
                and all((output / name).is_file() and recorded.get('classes', {}).get(name)
                        == hashlib.sha256((output / name).read_bytes()).hexdigest() for name in class_names)):
            return output
    except (OSError, ValueError):
        pass
    source_text = data.decode('utf-8')
    start = source_text.index('public int getNameMax(String path) {')
    opening = source_text.index('{', start)
    position, depth = opening, 1
    while depth:
        position += 1
        depth += (source_text[position] == '{') - (source_text[position] == '}')
    original = source_text[opening + 1:position]
    if 'return getNameMax0(getPathForWin32Calls(s));' not in original:
        raise ValueError('WINDOWS_RESEARCH_JDK_COMPAT_METHOD_CHANGED')
    source_text = (source_text[:opening + 1] + '\n        return ' + str(component.value)
                   + '; // Host-verified metadata; AppContainer still enforces file access.\n    '
                   + source_text[position:])
    source_root = base / 'source'
    source = source_root / 'java/io/WinNTFileSystem.java'
    source.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    source.write_text(source_text, encoding='utf-8', newline='\n')
    link_text = link_data.decode('utf-8')
    start = link_text.index('static String getRealPath(WindowsPath input, boolean resolveLinks)')
    opening = link_text.index('{', start)
    link_text = (link_text[:opening + 1] + '\n'
        '        // Resolve the requested handle directly; its ReadAttributes ACL still applies.\n'
        '        if (resolveLinks) {\n'
        '            String direct = getFinalPath(input);\n'
        '            if (direct != null) return direct;\n'
        '        }\n' + link_text[opening + 1:])
    link_source = source_root / 'sun/nio/fs/WindowsLinkSupport.java'
    link_source.parent.mkdir(parents=True, exist_ok=True)
    link_source.write_text(link_text, encoding='utf-8', newline='\n')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env = {'SystemRoot': str(system), 'WINDIR': str(system),
           'PATH': os.pathsep.join((str(tools / 'jdk/bin'), str(system / 'System32'))),
           'TEMP': os.environ.get('TEMP', str(scratch)), 'TMP': os.environ.get('TMP', str(scratch))}
    result = subprocess.run([str(tools / 'jdk/bin/javac.exe'), '--patch-module',
        'java.base=' + str(source_root), '-d', str(output), str(source), str(link_source)], env=env,
        capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not all((output / name).is_file() for name in class_names):
        raise ValueError('WINDOWS_RESEARCH_JDK_COMPAT_COMPILE_FAILED')
    expected['classes'] = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in class_names}
    metadata_path.write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8')
    return output


def available() -> bool:
    if os.name != 'nt':
        return False
    import ctypes
    try:
        library = ctypes.WinDLL('userenv', use_last_error=True)
        return bool(library.CreateAppContainerProfile and library.DeriveAppContainerSidFromAppContainerName)
    except (AttributeError, OSError):
        return False


def _environment(scratch: Path, tools: Path) -> dict[str, str]:
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    home = scratch / 'home'
    temporary = scratch / 'tmp'
    return {
        'SystemRoot': str(system), 'WINDIR': str(system),
        'COMSPEC': str(system / 'System32/cmd.exe'),
        'PATH': os.pathsep.join(str(p) for p in (tools / 'runtime', tools / 'jdk/bin', system / 'System32')),
        'HOME': str(home), 'USERPROFILE': str(home),
        'APPDATA': str(home / 'AppData/Roaming'), 'LOCALAPPDATA': str(temporary),
        'TEMP': str(temporary), 'TMP': str(temporary), 'TMPDIR': str(temporary),
        'JAVA_HOME': str(tools / 'jdk'), 'GHIDRA_INSTALL_DIR': str(tools / 'ghidra'),
        'GHIDRA_HEADLESS_MAXMEM': '512m',
        'JAVA_TOOL_OPTIONS': '-Xmx512m -XX:ActiveProcessorCount=2 '
                             + f'-Duser.home="{home}" -Djava.io.tmpdir="{temporary}"',
        'NODE_OPTIONS': '--max-old-space-size=512', 'NODE_NO_WARNINGS': '1',
        'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
    }


def run(command: list[str], *, scratch: Path, tools: Path, timeout: float,
        max_output_bytes: int, cancelled=None) -> tuple[int, bytes, bytes, str]:
    """Run a trusted tool with no capabilities and return bounded pipe output.

    The callback is checked repeatedly. True cancels the job; an exception is
    propagated after terminating every child (used for the scratch-size limit).
    """
    if os.name != 'nt' or not available():
        raise ValueError('WINDOWS_APPCONTAINER_UNAVAILABLE')
    if not command or timeout <= 0 or max_output_bytes <= 0:
        raise ValueError('INVALID_SANDBOX_LIMITS')
    if any('\0' in str(argument) for argument in command) or len(subprocess.list2cmdline(command)) > 30000:
        raise ValueError('INVALID_SANDBOX_COMMAND')
    original_scratch, original_tools = Path(scratch), Path(tools)
    if (original_scratch.is_symlink() or original_scratch.is_junction()
            or original_tools.is_symlink() or original_tools.is_junction()):
        raise ValueError('SANDBOX_LINK_ROOT_NOT_ALLOWED')
    scratch, tools = original_scratch.resolve(strict=True), original_tools.resolve(strict=True)
    if scratch == Path(scratch.anchor) or tools == Path(tools.anchor):
        raise ValueError('SANDBOX_SCOPE_INVALID')
    if str(scratch).startswith('\\\\') or str(tools).startswith('\\\\'):
        raise ValueError('SANDBOX_LOCAL_DISK_REQUIRED')
    executable = Path(command[0]).resolve(strict=True)
    if (not scratch.is_dir() or not tools.is_dir() or scratch == tools
            or scratch.is_relative_to(tools) or tools.is_relative_to(scratch)
            or not executable.is_relative_to(tools) or executable.suffix.lower() != '.exe'):
        raise ValueError('SANDBOX_SCOPE_INVALID')
    protected = (Path.home().resolve(), Path(__file__).resolve().parents[1])
    if any(path.is_relative_to(root) for path in protected for root in (scratch, tools)):
        raise ValueError('SANDBOX_SCOPE_INVALID')
    with _RUN_LOCK:
        return _run_native([str(executable), *map(str, command[1:])], scratch, tools,
                           timeout, max_output_bytes, cancelled)


def _run_native(command, scratch, tools, timeout, max_output_bytes, cancelled):
    import ctypes
    from ctypes import wintypes as w
    import msvcrt

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', w.BOOL)]

    class SecurityCapabilities(ctypes.Structure):
        _fields_ = [('sid', ctypes.c_void_p), ('capabilities', ctypes.c_void_p),
                    ('count', w.DWORD), ('reserved', w.DWORD)]

    class StartupInfo(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                    ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                    ('chars_x', w.DWORD), ('chars_y', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                    ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', ctypes.c_void_p),
                    ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]

    class StartupInfoEx(ctypes.Structure):
        _fields_ = [('startup', StartupInfo), ('attributes', ctypes.c_void_p)]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                    ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('processes', w.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('reads', 'writes', 'others', 'read_bytes', 'write_bytes', 'other_bytes')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    userenv = ctypes.WinDLL('userenv', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CreatePipe.argtypes = [ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.POINTER(SecurityAttributes), w.DWORD]
    kernel.SetHandleInformation.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
    kernel.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                                     ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(StartupInfoEx), ctypes.POINTER(ProcessInformation)]
    kernel.CreateProcessW.restype = w.BOOL
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.ReleaseMutex.argtypes = [w.HANDLE]
    kernel.QueryDosDeviceW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    kernel.DefineDosDeviceW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.ResumeThread.argtypes = [w.HANDLE]
    kernel.ResumeThread.restype = w.DWORD
    userenv.CreateAppContainerProfile.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [w.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    userenv.GetAppContainerFolderPath.argtypes = [w.LPCWSTR, ctypes.POINTER(w.LPWSTR)]
    userenv.GetAppContainerFolderPath.restype = ctypes.c_long
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.FreeSid.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]

    def check(ok, label):
        if not ok:
            raise ValueError(label + '_' + str(ctypes.get_last_error()))

    name = 'GoldGoblins.Research.' + hashlib.sha256(str(tools).casefold().encode()).hexdigest()[:16]
    sid = ctypes.c_void_p()
    text_sid = w.LPWSTR()
    handles = set()
    profile = False
    attributes = None
    attributes_ready = False
    process = ProcessInformation()
    job = None
    pipes = []
    readers = []
    buffers = [bytearray(), bytearray()]
    buffer_lock = threading.Lock()
    overflow = threading.Event()
    trigger = 'NONE'
    profile_path = None
    dos_mappings = []
    dos_mutex = None
    mutex = kernel.CreateMutexW(None, False, 'Local\\' + name)
    check(mutex, 'WINDOWS_SANDBOX_MUTEX_FAILED')
    if kernel.WaitForSingleObject(mutex, min(30000, max(1, int(timeout * 1000)))) not in (0, 128):
        kernel.CloseHandle(mutex)
        raise ValueError('WINDOWS_SANDBOX_BUSY')

    def close(handle):
        value = handle.value if hasattr(handle, 'value') else handle
        if value in handles:
            handles.remove(value)
            kernel.CloseHandle(value)

    def acl(path, rights, *, low=False, recursive=False):
        # These are the two validated task roots or their scratch descendants.
        path = Path(path).resolve(strict=True)
        assert path == tools or path == scratch or path.is_relative_to(scratch)
        arguments = [str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icacls.exe'),
                     str(path), '/grant:r', '*' + text_sid.value + ':' + rights, '/q']
        if recursive:
            arguments.append('/T')
        result = subprocess.run(arguments, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('WINDOWS_SANDBOX_ACL_FAILED')
        if low:
            result = subprocess.run([arguments[0], str(path), '/setintegritylevel', '(OI)(CI)L', '/q'],
                                    capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError('WINDOWS_SANDBOX_INTEGRITY_FAILED')

    def read_pipe(index, pipe):
        try:
            while chunk := pipe.read(4096):
                with buffer_lock:
                    remaining = max_output_bytes - sum(map(len, buffers))
                    buffers[index].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
                        return
        except (OSError, ValueError):
            pass

    try:
        # JVM canonicalization probes every ancestor of C:\ paths. Temporary
        # per-logon aliases expose only the granted task roots, avoiding
        # metadata/list grants on the user's home or C:\ root. Only tools and
        # Java's temp property use aliases. User-home and explicit project paths
        # stay physical: OSGi/Felix compares canonical parent/child paths.
        dos_mutex = kernel.CreateMutexW(None, False, 'Local\\GoldGoblins.Research.DosMappings')
        check(dos_mutex, 'WINDOWS_SANDBOX_DOS_MUTEX_FAILED')
        if kernel.WaitForSingleObject(dos_mutex, min(30000, max(1, int(timeout * 1000)))) not in (0, 128):
            raise ValueError('WINDOWS_SANDBOX_BUSY')
        for root in (tools, scratch):
            for letter in 'ZYXWVUTSRQPONMLKJIHGFED':
                drive = letter + ':'
                buffer = ctypes.create_unicode_buffer(32768)
                if kernel.QueryDosDeviceW(drive, buffer, len(buffer)):
                    continue
                if ctypes.get_last_error() != 2:
                    continue
                target = '\\??\\' + str(root)
                check(kernel.DefineDosDeviceW(0x1 | 0x8, drive, target), 'WINDOWS_SANDBOX_DOS_CREATE_FAILED')
                dos_mappings.append((drive, target))
                break
            else:
                raise ValueError('WINDOWS_SANDBOX_NO_FREE_DRIVE_ALIAS')

        def mapped(value):
            for original, (drive, _) in zip((tools,), dos_mappings):
                value = re.sub(re.escape(str(original)) + r'(?=$|[\\/;\"])',
                               lambda _: drive, value, flags=re.IGNORECASE)
            return value

        mapped_command = [mapped(argument) for argument in command]
        jdk_compat = _jdk_compatibility(tools, scratch)
        result = userenv.CreateAppContainerProfile(name, 'GG static research', 'Temporary static-analysis execution profile', None, 0, ctypes.byref(sid))
        if result == -2147024713:  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)
            result = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        if result:
            raise ValueError('WINDOWS_SANDBOX_PROFILE_FAILED_' + str(result & 0xffffffff))
        profile = True
        check(security.ConvertSidToStringSidW(sid, ctypes.byref(text_sid)), 'WINDOWS_SANDBOX_SID_FAILED')
        for directory in ('home', 'tmp', 'home/AppData/Roaming', 'home/AppData/Local',
                          'tmp/Packages/' + name.lower() + '/AC/Temp'):
            (scratch / directory).mkdir(parents=True, exist_ok=True)
        acl_marker = tools / '.gg-appcontainer-read-access.json'
        fingerprint = {'profile': name, 'entries': [
            [path.name, path.stat().st_size, path.stat().st_mtime_ns]
            for path in sorted(tools.iterdir()) if path != acl_marker]}
        installation = tools / 'installation.json'
        if installation.is_file():
            fingerprint['installation'] = hashlib.sha256(installation.read_bytes()).hexdigest()
        try:
            acl_ready = json.loads(acl_marker.read_text(encoding='utf-8')) == fingerprint
        except (OSError, ValueError):
            acl_ready = False
        if not acl_ready:
            acl(tools, '(OI)(CI)(RX)', recursive=True)
            acl_marker.write_text(json.dumps(fingerprint), encoding='utf-8')
        acl(scratch, '(OI)(CI)(RX)')
        acl(scratch / 'home', '(OI)(CI)(M)', low=True)
        acl(scratch / 'tmp', '(OI)(CI)(M)', low=True)
        # An AppContainer normally has a persistent private profile. Deny this
        # tool access to that storage: all writable state belongs to this job.
        profile_folder = w.LPWSTR()
        result = userenv.GetAppContainerFolderPath(text_sid, ctypes.byref(profile_folder))
        if result:
            raise ValueError('WINDOWS_SANDBOX_PROFILE_PATH_FAILED_' + str(result & 0xffffffff))
        try:
            profile_path = Path(profile_folder.value).resolve(strict=True)
            package_root = (Path(os.environ['LOCALAPPDATA']) / 'Packages').resolve(strict=True)
            if not profile_path.is_relative_to(package_root) or profile_path.parent.name.casefold() != name.casefold():
                raise ValueError('WINDOWS_SANDBOX_PROFILE_PATH_INVALID')
            result = subprocess.run([
                str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icacls.exe'),
                str(profile_path), '/deny', '*' + text_sid.value + ':(OI)(CI)(W,D,DC)',
                '*S-1-15-2-1:(OI)(CI)(W,D,DC)', '*S-1-1-0:(OI)(CI)(W,D,DC)', '/q'],
                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError('WINDOWS_SANDBOX_PROFILE_DENY_FAILED')
        finally:
            ole = ctypes.WinDLL('ole32')
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree(ctypes.cast(profile_folder, ctypes.c_void_p))

        inheritance = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
        pipe_handles = []
        for _ in range(3):
            read_handle, write_handle = w.HANDLE(), w.HANDLE()
            check(kernel.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(inheritance), 0), 'WINDOWS_SANDBOX_PIPE_FAILED')
            handles.update((read_handle.value, write_handle.value))
            pipe_handles.append((read_handle, write_handle))
        stdin_read, stdin_write = pipe_handles[0]
        stdout_read, stdout_write = pipe_handles[1]
        stderr_read, stderr_write = pipe_handles[2]
        for handle in (stdin_write, stdout_read, stderr_read):
            check(kernel.SetHandleInformation(handle, 1, 0), 'WINDOWS_SANDBOX_PIPE_FLAGS_FAILED')
        size = ctypes.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        check(kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)), 'WINDOWS_SANDBOX_ATTRIBUTES_FAILED')
        attributes_ready = True
        capabilities = SecurityCapabilities(sid, None, 0, 0)
        check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20009, ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None), 'WINDOWS_SANDBOX_CAPABILITIES_FAILED')
        inherited = (w.HANDLE * 3)(stdin_read.value, stdout_write.value, stderr_write.value)
        check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited, ctypes.sizeof(inherited), None, None), 'WINDOWS_SANDBOX_HANDLE_LIST_FAILED')
        startup = StartupInfoEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdin_read, stdout_write, stderr_write
        startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
        environment = {key: mapped(value) for key, value in _environment(scratch, tools).items()}
        # Windows' temp-name limit query probes the volume root. The scratch
        # alias grants that query without granting access to the host C:\ root.
        environment['JAVA_TOOL_OPTIONS'] = environment['JAVA_TOOL_OPTIONS'].replace(
            f'-Djava.io.tmpdir="{scratch / "tmp"}"',
            '-Djava.io.tmpdir="' + dos_mappings[1][0] + '\\tmp"')
        if (tools / 'jdk').is_dir():
            environment['JAVA_TOOL_OPTIONS'] += ' -Djava.home="' + dos_mappings[0][0] + '\\jdk"'
        if jdk_compat is not None:
            environment['JAVA_TOOL_OPTIONS'] += ' "--patch-module=java.base=' + mapped(str(jdk_compat)) + '"'
        block = ctypes.create_unicode_buffer('\0'.join(k + '=' + v for k, v in sorted(environment.items(), key=lambda pair: pair[0].casefold())) + '\0\0')
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(mapped_command))
        flags = 0x80000 | 0x08000000 | 0x400 | 0x4  # extended, hidden, unicode environment, suspended
        check(kernel.CreateProcessW(mapped_command[0], command_line, None, None, True, flags,
                                    block, mapped(str(scratch / 'home')), ctypes.byref(startup), ctypes.byref(process)),
              'WINDOWS_SANDBOX_LAUNCH_FAILED')
        handles.update((process.process, process.thread))
        token = w.HANDLE()
        check(security.OpenProcessToken(process.process, 0x8, ctypes.byref(token)), 'WINDOWS_SANDBOX_TOKEN_FAILED')
        handles.add(token.value)
        token_size, is_container = w.DWORD(), w.DWORD()
        check(security.GetTokenInformation(token, 29, ctypes.byref(is_container), ctypes.sizeof(is_container), ctypes.byref(token_size)), 'WINDOWS_SANDBOX_TOKEN_INFO_FAILED')
        if is_container.value != 1:
            raise ValueError('WINDOWS_SANDBOX_TOKEN_NOT_CONTAINED')
        security.GetTokenInformation(token, 30, None, 0, ctypes.byref(token_size))
        token_caps = ctypes.create_string_buffer(token_size.value)
        check(security.GetTokenInformation(token, 30, token_caps, token_size, ctypes.byref(token_size)), 'WINDOWS_SANDBOX_TOKEN_CAPS_FAILED')
        if ctypes.cast(token_caps, ctypes.POINTER(w.DWORD))[0] != 0:
            raise ValueError('WINDOWS_SANDBOX_UNEXPECTED_CAPABILITIES')
        close(token)
        job = kernel.CreateJobObjectW(None, None)
        check(job, 'WINDOWS_SANDBOX_JOB_FAILED')
        handles.add(job)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8 | 0x2
        limits.basic.process_time = max(1, int(timeout * 10_000_000))
        limits.basic.processes = 16
        limits.process_memory = 1024 * 1024 * 1024
        limits.job_memory = 1536 * 1024 * 1024
        check(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), 'WINDOWS_SANDBOX_LIMITS_FAILED')
        check(kernel.AssignProcessToJobObject(job, process.process), 'WINDOWS_SANDBOX_ASSIGN_JOB_FAILED')
        for handle in (stdin_read, stdin_write, stdout_write, stderr_write):
            close(handle)
        for handle in (stdout_read, stderr_read):
            handles.remove(handle.value)
            pipe = os.fdopen(msvcrt.open_osfhandle(handle.value, os.O_RDONLY | os.O_BINARY), 'rb', buffering=0)
            pipes.append(pipe)
        for index, pipe in enumerate(pipes):
            reader = threading.Thread(target=read_pipe, args=(index, pipe), daemon=True)
            reader.start()
            readers.append(reader)
        if kernel.ResumeThread(process.thread) == 0xffffffff:
            check(False, 'WINDOWS_SANDBOX_RESUME_FAILED')
        close(process.thread)
        deadline = time.monotonic() + timeout
        while True:
            waited = kernel.WaitForSingleObject(process.process, 0)
            if waited == 0:
                break
            check(waited == 258, 'WINDOWS_SANDBOX_WAIT_FAILED')
            if overflow.is_set():
                trigger = 'OUTPUT_LIMIT'
                break
            if cancelled and cancelled():
                trigger = 'CANCELLED'
                break
            if time.monotonic() >= deadline:
                trigger = 'TIMEOUT'
                break
            time.sleep(0.01)
        kernel.TerminateJobObject(job, 1)
        kernel.WaitForSingleObject(process.process, 3000)
        for reader in readers:
            reader.join(timeout=2)
        if overflow.is_set() and trigger == 'NONE':
            trigger = 'OUTPUT_LIMIT'
        code = w.DWORD()
        check(kernel.GetExitCodeProcess(process.process, ctypes.byref(code)), 'WINDOWS_SANDBOX_EXIT_FAILED')
        return code.value, bytes(buffers[0]), bytes(buffers[1]), trigger
    finally:
        if job:
            kernel.TerminateJobObject(job, 1)
        if process.process:
            kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
            kernel.TerminateProcess(process.process, 1)
        if process.process:
            kernel.WaitForSingleObject(process.process, 3000)
        for reader in readers:
            reader.join(timeout=2)
        for pipe in pipes:
            pipe.close()
        for handle in list(handles):
            close(handle)
        if attributes_ready:
            kernel.DeleteProcThreadAttributeList(attributes)
        if text_sid:
            kernel.LocalFree(ctypes.cast(text_sid, ctypes.c_void_p))
        if sid:
            security.FreeSid(sid)
        try:
            if profile:
                if profile_path is not None:
                    result = subprocess.run([
                        str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icacls.exe'),
                        str(profile_path), '/remove:d', '*S-1-1-0', '/q'],
                        capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise ValueError('WINDOWS_SANDBOX_PROFILE_ACL_RESTORE_FAILED')
                result = userenv.DeleteAppContainerProfile(name)
                if result:
                    raise ValueError('WINDOWS_SANDBOX_PROFILE_CLEANUP_FAILED_' + str(result & 0xffffffff))
        finally:
            try:
                for drive, target in reversed(dos_mappings):
                    check(kernel.DefineDosDeviceW(0x1 | 0x2 | 0x4 | 0x8, drive, target),
                          'WINDOWS_SANDBOX_DOS_CLEANUP_FAILED')
            finally:
                if dos_mutex:
                    kernel.ReleaseMutex(dos_mutex)
                    kernel.CloseHandle(dos_mutex)
                kernel.ReleaseMutex(mutex)
                kernel.CloseHandle(mutex)
