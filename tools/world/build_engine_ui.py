"""Build the adapted upstream UI core using GG's isolated Rust toolchain."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,tempfile,sys
PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
from backend.application_paths import DATA_ROOT
from backend.platform_support import find_executable,native_directory,native_library_name
from backend.platform_build import build_environment
SOURCE=PROJECT/'native/engine-ui'
ENGINE=DATA_ROOT/'game-engine'
TOOLS=ENGINE/'rust-tools'
TARGET=ENGINE/'engine-ui-build'
def environment():
    env=build_environment()
    env.update(CARGO_TARGET_DIR=str(TARGET),CARGO_BUILD_JOBS='2')
    if os.name!='nt':
        env.update(CARGO_HOME=str(TOOLS/'cargo'),RUSTUP_HOME=str(TOOLS/'rustup'))
        env['PATH']=str(TOOLS/'cargo/bin')+os.pathsep+env['PATH']
    return env
def rust_tool(name):
    tool=find_executable(name) if os.name=='nt' else str(TOOLS/'cargo/bin'/name)
    if not tool:raise RuntimeError('Install Rust with rustup before building the native engine')
    return tool
def source_digest():
    d=hashlib.sha256()
    for p in sorted(SOURCE.rglob('*')):
        if p.is_file() and p.suffix in ('.rs','.c','.h','.toml','.lock','.tsv'):
            d.update(p.relative_to(SOURCE).as_posix().encode());d.update(p.read_bytes())
    return d.hexdigest()
def run(args):
    return subprocess.run([rust_tool('cargo'),*args],cwd=SOURCE,env=environment(),check=True)
def build():
    run(['build','--release','--locked','-p','gg-engine-ui'])
    binary=TARGET/'release'/native_library_name('gg_engine_ui')
    output=native_directory(PROJECT);output.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'gg.engine-ui-build.v1','abi':1,'source_sha256':source_digest(),
        'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'binary_bytes':binary.stat().st_size,
        'rustc':subprocess.check_output([rust_tool('rustc'),'--version'],env=environment(),text=True).strip()}
    with tempfile.TemporaryDirectory(prefix='.gg-engine-ui-',dir=output) as directory:
        tmp=Path(directory);shutil.copy2(binary,tmp/binary.name)
        (tmp/'engine-ui-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
        for name in (binary.name,'engine-ui-build.json'):os.replace(tmp/name,output/name)
    print(json.dumps({'status':'PASS','binary_bytes':receipt['binary_bytes']}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tests',action='store_true');p.add_argument('--prepare-lock',action='store_true');a=p.parse_args()
    if a.prepare_lock:run(['generate-lockfile'])
    elif a.tests:run(['test','--locked','-p','engine-ui-core'])
    else:build()
