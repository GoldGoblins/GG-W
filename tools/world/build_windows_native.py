"""Finite MSVC builds for the same GG native ABIs used on Fedora."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from backend.platform_build import build_environment, build_tool
from backend.platform_support import native_directory, native_library_name


def invoke(argv, *, env, cwd, timeout=180):
    return subprocess.run([str(a) for a in argv], env=env, cwd=cwd, check=True,
                          capture_output=True, text=True, errors='replace', timeout=timeout)


def build_cpp(kind, output, digest):
    if os.name != 'nt':
        raise RuntimeError('MSVC build requires Windows')
    env = build_environment()
    compiler = build_tool('cl.exe', env)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    source = PROJECT / 'native' / kind
    name = 'gg_world' if kind == 'world' else 'gg_presentation'
    receipt_name = 'build.json' if kind == 'world' else 'presentation-build.json'
    with tempfile.TemporaryDirectory(prefix='.gg-native-', dir=output) as directory:
        tmp = Path(directory)
        flags = ['/nologo', '/O2', '/MD', '/W4', '/EHsc', '/std:c++17', '/DGG_NATIVE_BUILD']
        objects = []
        if kind == 'presentation':
            for path in sorted((source / 'lua').glob('*.c')):
                if path.stem in ('linit', 'ldblib', 'liolib', 'loslib', 'loadlib'):
                    continue
                obj = tmp / (path.stem + '.obj'); objects.append(obj)
                invoke([compiler, '/nologo', '/O2', '/MD', '/TC', '/std:c11', '/c', path, '/Fo' + str(obj)], env=env, cwd=tmp)
        library = tmp / native_library_name(name)
        try:
            invoke([compiler, *flags, '/LD', '/I' + str(source / 'lua'), source / (name + '.cpp'),
                    *objects, '/link', '/OUT:' + str(library), '/IMPLIB:' + str(tmp / (name + '.lib'))], env=env, cwd=tmp)
            probe = tmp / (name + '_probe.exe')
            invoke([compiler, '/nologo', '/MD', '/EHsc', '/std:c++17', source / (kind + '_probe.cpp'),
                    tmp / (name + '.lib'), '/Fe' + str(probe)], env=env, cwd=tmp)
            host_lua = PROJECT / 'qml/game/lua/host.lua'
            argv = [probe] + ([host_lua] if kind == 'presentation' and host_lua.is_file() else [])
            checked = invoke(argv, env=env, cwd=tmp, timeout=30)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError((exc.stdout + '\n' + exc.stderr)[-12000:]) from exc
        receipt = dict(schema='gg.native-' + kind + '-build.v1', abi=1,
                       platform=native_directory().name, compiler='MSVC', flags=flags,
                       source_sha256=digest(), binary_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                       binary_bytes=library.stat().st_size, probe=json.loads(checked.stdout))
        if kind == 'presentation':
            receipt.update(lua_c_files=len(objects), sanitizers=False)
        (tmp / receipt_name).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        for filename in (library.name, probe.name, receipt_name):
            os.replace(tmp / filename, output / filename)
    return dict(status='PASS', platform=receipt['platform'], binary_bytes=receipt['binary_bytes'], probe=receipt['probe'])


def build_physics():
    from backend.game_engine_native_physics import source_digest
    env = build_environment()
    cmake = build_tool('cmake.exe', env)
    output = native_directory(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gg-physics-', dir=output) as directory:
        tmp = Path(directory)
        try:
            invoke([cmake, '-S', PROJECT / 'native/physics', '-B', tmp, '-G', 'NMake Makefiles',
                    '-DCMAKE_BUILD_TYPE=Release', '-DBOX3D_SAMPLES=OFF', '-DBOX3D_UNIT_TESTS=OFF'], env=env, cwd=tmp)
            invoke([cmake, '--build', tmp, '--config', 'Release', '-j', '2'], env=env, cwd=tmp, timeout=900)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError((exc.stdout + '\n' + exc.stderr)[-12000:]) from exc
        binary = next(tmp.rglob('gg_physics.dll'))
        invoke([sys.executable, '-X', 'utf8', '-B', '-c',
                'import ctypes,sys; assert ctypes.CDLL(sys.argv[1]).ggp_abi_version()==1', binary], env=env, cwd=tmp, timeout=10)
        compiler = build_tool('cl.exe', env)
        probe = binary.parent / 'gg_physics_probe.exe'
        invoke([compiler, '/nologo', '/MD', '/EHsc', '/std:c++17', PROJECT / 'native/physics/physics_probe.cpp',
                next(tmp.rglob('gg_physics.lib')), '/Fe' + str(probe)], env=env, cwd=tmp)
        checked = invoke([probe], env=env, cwd=tmp, timeout=30)
        receipt = dict(schema='gg.native-physics-build.v1', abi=1, precision='DOUBLE_POSITIONS',
                       platform=output.name, source_sha256=source_digest(),
                       binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), binary_bytes=binary.stat().st_size,
                       probe=json.loads(checked.stdout))
        os.replace(binary, output / binary.name)
        os.replace(probe, output / probe.name)
        (output / 'physics-build.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return dict(status='PASS', platform=output.name, binary_bytes=receipt['binary_bytes'])


if __name__ == '__main__':
    print(json.dumps(build_physics()))
