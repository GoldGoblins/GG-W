"""Build the bounded C++ world core with the system or dedicated local compiler."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.platform_support import native_directory

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / 'native/world'
TOOLS = Path.home() / '.local/share/goldgoblins/gg-ai-desktop/game-engine/native-tools'
FLAGS = ['-std=c++17', '-O2', '-fPIC', '-fvisibility=hidden', '-Wall', '-Wextra', '-Wpedantic', '-Werror']

def source_digest():
    digest=hashlib.sha256()
    for name in ('gg_world.h','gg_world.cpp'):
        digest.update(name.encode()); digest.update((SOURCE/name).read_bytes())
    return digest.hexdigest()

def build(output: Path):
    if os.name == 'nt':
        from build_windows_native import build_cpp
        return build_cpp('world', output, source_digest)
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise RuntimeError('this local build targets Linux x86_64')
    compiler=shutil.which('g++')
    extra=[]
    if compiler is None:
        compiler=str(TOOLS/'usr/bin/g++')
        if not Path(compiler).is_file():
            raise RuntimeError('C++ compiler missing; install gcc-c++ or the signed local Fedora build tools first')
        extra=['-B'+str(TOOLS/'usr/libexec/gcc/x86_64-redhat-linux/16')+'/',
               '-B'+str(TOOLS/'usr/lib/gcc/x86_64-redhat-linux/16')+'/',
               '-B/usr/libexec/gcc/x86_64-redhat-linux/16/', '-B/usr/lib/gcc/x86_64-redhat-linux/16/', '-nostdinc++']
        for rel in ('usr/include/c++/16','usr/include/c++/16/x86_64-redhat-linux','usr/include/c++/16/backward'):
            extra+=['-isystem',str(TOOLS/rel)]
        extra+=['-isystem','/usr/lib/gcc/x86_64-redhat-linux/16/include']
        extra+=['-L'+str(TOOLS/'usr/lib/gcc/x86_64-redhat-linux/16'),'-L'+str(TOOLS/'usr/lib64')]
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gg-world-build-',dir=output) as tmp:
        tmp=Path(tmp); library=tmp/'libgg_world.so'; probe=tmp/'gg_world_probe'
        subprocess.run([compiler,*extra,*FLAGS,'-shared',str(SOURCE/'gg_world.cpp'),'-Wl,-z,relro,-z,now','-Wl,-soname,libgg_world.so','-o',str(library)],check=True,timeout=90)
        subprocess.run([compiler,*extra,*FLAGS,str(SOURCE/'world_probe.cpp'),'-L'+str(tmp),'-lgg_world','-Wl,-rpath,$ORIGIN','-o',str(probe)],check=True,timeout=90)
        result=subprocess.run([str(probe)],check=True,capture_output=True,text=True,timeout=10)
        version=subprocess.run([compiler,'--version'],check=True,capture_output=True,text=True).stdout.splitlines()[0]
        manifest={'schema':'gg.native-world-build.v1','abi':1,'platform':'linux-x86_64','compiler':version,'flags':FLAGS,
                  'source_sha256':source_digest(),'binary_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
                  'binary_bytes':library.stat().st_size,'probe':json.loads(result.stdout)}
        (tmp/'build.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for name in ('libgg_world.so','gg_world_probe','build.json'):
            os.replace(tmp/name,output/name)
    return {'status':'PASS','library':str(output/'libgg_world.so'),'binary_bytes':manifest['binary_bytes'],'probe':manifest['probe']}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=native_directory(PROJECT))
    print(json.dumps(build(parser.parse_args().output)))
