"""Offline native presentation build, including the pinned GgEngine Lua C VM."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path
from build_native_world import TOOLS, FLAGS, native_directory
PROJECT=Path(__file__).resolve().parents[2]
SOURCE=PROJECT/'native/presentation'

def digest():
    d=hashlib.sha256()
    for p in sorted([*(SOURCE.glob('*.h')),SOURCE/'gg_presentation.cpp',*(SOURCE/'lua').glob('*.c'),*(SOURCE/'lua').glob('*.h')]):
        d.update(p.relative_to(SOURCE).as_posix().encode());d.update(p.read_bytes())
    return d.hexdigest()

def build(output, sanitize=False):
    if os.name == 'nt':
        if sanitize:
            raise RuntimeError('The Windows build does not provide the Linux sanitizer profile')
        from build_windows_native import build_cpp
        return build_cpp('presentation', output, digest)
    compiler=shutil.which('g++') or str(TOOLS/'usr/bin/g++')
    extra=[]
    if not shutil.which('g++'):
        extra=['-B'+str(TOOLS/'usr/libexec/gcc/x86_64-redhat-linux/16')+'/',
               '-B'+str(TOOLS/'usr/lib/gcc/x86_64-redhat-linux/16')+'/',
               '-B/usr/libexec/gcc/x86_64-redhat-linux/16/','-B/usr/lib/gcc/x86_64-redhat-linux/16/','-nostdinc++']
        for rel in ('usr/include/c++/16','usr/include/c++/16/x86_64-redhat-linux','usr/include/c++/16/backward'):
            extra+=['-isystem',str(TOOLS/rel)]
        extra+=['-L'+str(TOOLS/'usr/lib/gcc/x86_64-redhat-linux/16'),'-L'+str(TOOLS/'usr/lib64')]
    flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if sanitize else []
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gg-presentation-build-',dir=output) as directory:
        tmp=Path(directory);objects=[]
        for source in sorted((SOURCE/'lua').glob('*.c')):
            if source.stem in ('linit','ldblib','liolib','loslib','loadlib'):continue
            obj=tmp/(source.stem+'.o');objects.append(obj)
            subprocess.run(['gcc','-std=gnu99','-O2','-fPIC','-fvisibility=hidden',*flags,'-c',str(source),'-o',str(obj)],check=True,timeout=20,stdout=subprocess.DEVNULL)
        lib=tmp/'libgg_presentation.so'
        subprocess.run([compiler,*extra,*FLAGS,*flags,'-shared','-I'+str(SOURCE/'lua'),str(SOURCE/'gg_presentation.cpp'),*(str(p) for p in objects),'-lm','-ldl','-Wl,-z,relro,-z,now','-Wl,-soname,libgg_presentation.so','-o',str(lib)],check=True,timeout=60)
        # Load ABI in a separate finite process before installing the build.
        if not sanitize:
            subprocess.run(['python3','-B','-c','import ctypes,sys; l=ctypes.CDLL(sys.argv[1]); assert l.ggm_abi_version()==1',str(lib)],check=True,timeout=10)
        probe=tmp/'gg_presentation_probe'
        subprocess.run([compiler,*extra,*FLAGS,*flags,str(SOURCE/'presentation_probe.cpp'),'-L'+str(tmp),'-lgg_presentation','-Wl,-rpath,$ORIGIN','-o',str(probe)],check=True,timeout=60)
        env=os.environ.copy()
        if sanitize:
            env['LD_LIBRARY_PATH']=str(TOOLS/'usr/lib64')
            env['ASAN_OPTIONS']='detect_leaks=1:halt_on_error=1'
            env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1'
        checked=subprocess.run([str(probe),str(PROJECT/'qml/game/lua/host.lua')],env=env,check=True,capture_output=True,text=True,timeout=20)
        manifest={'schema':'gg.native-presentation-build.v1','abi':1,'source_sha256':digest(),
                  'binary_sha256':hashlib.sha256(lib.read_bytes()).hexdigest(),'binary_bytes':lib.stat().st_size,'lua_c_files':len(objects),'sanitizers':sanitize,'probe':json.loads(checked.stdout)}
        (tmp/'presentation-build.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for name in ('libgg_presentation.so','presentation-build.json','gg_presentation_probe'):os.replace(tmp/name,output/name)
    return {'status':'PASS',**manifest}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=native_directory(PROJECT));p.add_argument('--sanitize',action='store_true')
    a=p.parse_args();print(json.dumps(build(a.output,a.sanitize)))
