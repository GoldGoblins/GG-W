"""Build the adapted upstream format readers with GG's isolated toolchain."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,tempfile
from build_engine_ui import environment,TOOLS,ENGINE,PROJECT,rust_tool,native_directory,native_library_name
SOURCE=PROJECT/'native/engine-formats'
TARGET=ENGINE/'engine-formats-build'
def source_digest():
    digest=hashlib.sha256()
    for path in sorted(SOURCE.rglob('*')):
        if path.is_file() and path.suffix in ('.rs','.h','.toml','.lock'):
            digest.update(path.relative_to(SOURCE).as_posix().encode());digest.update(path.read_bytes())
    return digest.hexdigest()
def run(args,**kwargs):
    env=environment();env['CARGO_TARGET_DIR']=str(TARGET)
    return subprocess.run([rust_tool('cargo'),*args],cwd=SOURCE,env=env,check=True,**kwargs)
def build():
    run(['build','--release','--locked','-p','gg-engine-formats'])
    binary=TARGET/'release'/native_library_name('gg_engine_formats');output=native_directory(PROJECT);output.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'gg.engine-formats-build.v1','abi':1,'source_sha256':source_digest(),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'binary_bytes':binary.stat().st_size}
    with tempfile.TemporaryDirectory(prefix='.gg-engine-formats-',dir=output) as directory:
        temporary=Path(directory);shutil.copy2(binary,temporary/binary.name)
        (temporary/'engine-formats-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
        for name in (binary.name,'engine-formats-build.json'):os.replace(temporary/name,output/name)
    print(json.dumps({'status':'PASS','binary_bytes':receipt['binary_bytes']}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-lock',action='store_true');parser.add_argument('--tests',action='store_true');args=parser.parse_args()
    if args.prepare_lock:run(['generate-lockfile'])
    elif args.tests:run(['test','--locked','--workspace'])
    else:build()
