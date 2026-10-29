"""Explicit per-user Go/CometBFT test tool build. Never runs at import."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parent
PROJECT = SOURCE.parents[1]
sys.path.insert(0, str(PROJECT))
from backend.application_paths import TOOLS_ROOT

TARGET = TOOLS_ROOT / 'gg-consensus'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
ANDROID_COMPATIBILITY_URL='https://github.com/wlynxg/anet/pull/9'


def native_build_flags(goos):
    flags=['-p','2','-mod=readonly','-trimpath']
    if goos=='android':flags.append('-ldflags=-checklinkname=0')
    return flags


def source_files():
    return sorted([SOURCE/'go.mod',SOURCE/'go.sum',SOURCE/'toolchain.json',*SOURCE.glob('*.go')],key=lambda path:path.name)


def source_fingerprint():
    """Public source freshness check; this never installs or executes anything."""
    entries={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files()}
    return hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def light_source_files():
    return [SOURCE/'go.mod',SOURCE/'go.sum',SOURCE/'toolchain.json',SOURCE/'ledger.go',SOURCE/'verify.go',SOURCE/'light/wasm_main.go']


def light_fingerprint():
    """WASM source receipt, independent from the native build fingerprint."""
    entries={path.relative_to(SOURCE).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in light_source_files()}
    return hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def build_light_verifier(target=TARGET):
    """Explicitly build public-data SDK verification; never replaces the node."""
    target=Path(target).resolve();executable=ensure_go(target)
    fingerprint=light_fingerprint()
    lock=json.loads((SOURCE/'toolchain.json').read_text(encoding='utf-8'))
    compiler=compiler_metadata(executable,target)
    runtime=Path(compiler['goroot'])/'lib/wasm/wasm_exec.js'
    if not runtime.is_file():raise RuntimeError('GG_CONSENSUS_WASM_RUNTIME_MISSING')
    with tempfile.TemporaryDirectory(prefix='light-build-',dir=target) as scratch:
        build=Path(scratch)
        for source in light_source_files():shutil.copyfile(source,build/source.name)
        environment=build_environment(target)
        environment.update(GOOS='js',GOARCH='wasm',GOMAXPROCS='2')
        artifact=build/'verifier.wasm'
        result=subprocess.run([str(executable),'build','-p','2','-mod=readonly','-trimpath','-ldflags=-s -w','-o',str(artifact),'.'],
            cwd=build,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=300,creationflags=FLAGS)
        if result.returncode:raise RuntimeError('GG_CONSENSUS_WASM_BUILD_FAILED')
        if light_fingerprint()!=fingerprint:raise RuntimeError('GG_CONSENSUS_LIGHT_SOURCE_CHANGED_DURING_BUILD')
        manifest={'schema':'gg.consensus.light-build.v1','source_sha256':fingerprint,
            'wasm_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'wasm_bytes':artifact.stat().st_size,
            'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),'runtime_bytes':runtime.stat().st_size,
            'go':compiler['go'],'cometbft':lock['cometbft'],'goos':'js','goarch':'wasm',
            'cgo_enabled':False,'build_flags':['-p','2','-mod=readonly','-trimpath','-ldflags=-s -w']}
        runtime_copy=target/'wasm_exec.js.tmp';shutil.copyfile(runtime,runtime_copy)
        os.replace(artifact,target/'verifier.wasm');os.replace(runtime_copy,target/'wasm_exec.js')
        receipt=target/'light-manifest.json.tmp'
        receipt.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        os.replace(receipt,target/'light-manifest.json')
    return target/'verifier.wasm'


def compiler_metadata(executable,target=TARGET,environment=None):
    environment=build_environment(target) if environment is None else environment
    result=subprocess.run([str(executable),'env','-json','GOVERSION','GOOS','GOARCH','GOROOT'],
        env=environment,capture_output=True,text=True,encoding='utf-8',timeout=15,creationflags=FLAGS)
    if result.returncode:raise RuntimeError('GG_CONSENSUS_COMPILER_METADATA_FAILED')
    metadata=json.loads(result.stdout)
    return {'go':metadata['GOVERSION'],'goos':metadata['GOOS'],'goarch':metadata['GOARCH'],'goroot':metadata['GOROOT']}


def write_build_metadata(executable,binary,build,target=TARGET,environment=None):
    """Retain supplier license texts and a public, checkable binary receipt."""
    target=Path(target).resolve()
    environment=build_environment(target) if environment is None else environment
    compiler=compiler_metadata(executable,target,environment)
    binary_info=subprocess.run([str(executable),'version','-m',str(binary)],capture_output=True,text=True,
        encoding='utf-8',timeout=15,creationflags=FLAGS)
    if binary_info.returncode:raise RuntimeError('GG_CONSENSUS_BINARY_METADATA_FAILED')
    linked={fields[1] for line in binary_info.stdout.splitlines() if len(fields:=line.strip().split())>=3 and fields[0]=='dep'}
    if not linked:raise RuntimeError('GG_CONSENSUS_BINARY_MODULES_MISSING')
    result=subprocess.run([str(executable),'list','-m','-json','all'],cwd=build,
        env=environment,capture_output=True,text=True,encoding='utf-8',timeout=60,creationflags=FLAGS)
    if result.returncode:raise RuntimeError('GG_CONSENSUS_MODULE_METADATA_FAILED')
    modules=[];decoder=json.JSONDecoder();rest=result.stdout
    notice_root=target/'notices';notice_root.mkdir(exist_ok=True)
    while rest.strip():
        item,end=decoder.raw_decode(rest.lstrip());rest=rest.lstrip()[end:]
        if item.get('Main') or item['Path'] not in linked:continue
        folder=Path(item.get('Dir',''))
        texts=[]
        destination=notice_root/re.sub(r'[^a-zA-Z0-9._-]','_',item['Path']+'@'+item.get('Version',''))
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE')) and path.stat().st_size<=1024*1024:
                    destination.mkdir(exist_ok=True);shutil.copyfile(path,destination/path.name);texts.append(path.name)
        modules.append({'module':item['Path'],'version':item.get('Version',''),'sum':item.get('Sum',''),'license_files':texts})
    if {item['module'] for item in modules}!=linked:raise RuntimeError('GG_CONSENSUS_BINARY_MODULE_METADATA_INCOMPLETE')
    go_license=Path(compiler['goroot'])/'LICENSE'
    if go_license.is_file():shutil.copyfile(go_license,notice_root/'Go-LICENSE')
    (notice_root/'modules.json').write_text(json.dumps({'schema':'gg.consensus.notices.v1','modules':modules},indent=2)+'\n',encoding='utf-8')
    lock=json.loads((SOURCE/'toolchain.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256()
    with Path(binary).open('rb') as incoming:
        for chunk in iter(lambda:incoming.read(1024*1024),b''):digest.update(chunk)
    manifest={'schema':'gg.consensus.build.v1','source_sha256':source_fingerprint(),
        'binary_sha256':digest.hexdigest(),'binary':Path(binary).name,'go':compiler['go'],
        'goos':compiler['goos'],'goarch':compiler['goarch'],
        'cometbft':lock['cometbft'],'cgo_enabled':False,'build_flags':native_build_flags(compiler['goos']),
        'compatibility_flags':['-checklinkname=0'] if compiler['goos']=='android' else [],
        'notices':'notices/modules.json'}
    if compiler['goos']=='android':
        manifest.update(compatibility_reason='Pinned transitive wlynxg/anet v0.0.5 references private net.zoneCache; upstream requires this Android link compatibility flag on Go>=1.23. libp2p remains disabled; SDK cryptographic checks remain enabled.',
                        compatibility_upstream=ANDROID_COMPATIBILITY_URL,experimental=True,target_execution_tested=False)
    temporary=target/'build-manifest.json.tmp'
    temporary.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,target/'build-manifest.json')
    return manifest


def ensure_go(target=TARGET):
    target=Path(target).resolve()
    target.mkdir(parents=True,exist_ok=True)
    lock=json.loads((SOURCE/'toolchain.json').read_text(encoding='utf-8'))
    version=lock['go']['version']
    executable=target/'go/bin/go.exe'
    if os.name!='nt':
        installed=shutil.which('go')
        if not installed:raise RuntimeError('GG_CONSENSUS_GO_REQUIRED')
        result=subprocess.run([installed,'version'],env=build_environment(target),capture_output=True,text=True,timeout=10)
        release=result.stdout.split()[2:3]
        matched=re.fullmatch(r'go(\d+)\.(\d+)(?:\.(\d+))?',release[0]) if release else None
        if result.returncode or not matched or tuple(map(int,matched.group(1,2)))<(1,25):
            raise RuntimeError('GG_CONSENSUS_LOCAL_GO_1_25_REQUIRED')
        return Path(installed)
    if executable.is_file():
        result=subprocess.run([str(executable),'version'],env=build_environment(target),capture_output=True,text=True,timeout=10,creationflags=FLAGS)
        if result.returncode or result.stdout.split()[2:3]!=[version]:raise RuntimeError('GG_CONSENSUS_TOOLCHAIN_VERSION')
        return executable
    if (target/'go').exists():raise RuntimeError('GG_CONSENSUS_TOOLCHAIN_TARGET_EXISTS')
    descriptor=lock['go']['windows_amd64']
    with tempfile.TemporaryDirectory(prefix='go-install-',dir=target) as temporary:
        scratch=Path(temporary).resolve()
        archive=scratch/'go.zip';total=0;digest=hashlib.sha256()
        request=urllib.request.Request(descriptor['url'],headers={'User-Agent':'GG-Test-Toolchain'})
        with urllib.request.urlopen(request,timeout=30) as response,archive.open('wb') as output:
            while chunk:=response.read(1024*1024):
                total+=len(chunk)
                if total>descriptor['bytes']:raise RuntimeError('GG_CONSENSUS_DOWNLOAD_SIZE')
                digest.update(chunk);output.write(chunk)
        if total!=descriptor['bytes'] or digest.hexdigest()!=descriptor['sha256']:
            raise RuntimeError('GG_CONSENSUS_DOWNLOAD_INTEGRITY')
        unpack=scratch/'unpack';unpack.mkdir()
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                destination=(unpack/member.filename).resolve()
                if not destination.is_relative_to(unpack) or not member.filename.startswith('go/') or ((member.external_attr>>16)&0o170000)==0o120000:
                    raise RuntimeError('GG_CONSENSUS_ARCHIVE_PATH')
            package.extractall(unpack)
        shutil.move(str(unpack/'go'),str(target/'go'))
    return executable


def build_environment(target=TARGET):
    target=Path(target).resolve()
    allowed={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOME','LOCALAPPDATA','APPDATA'}
    environment={k:v for k,v in os.environ.items() if k.upper() in allowed}
    environment.update(CGO_ENABLED='0',GOENV='off',GOTOOLCHAIN='local',GOMAXPROCS='2',
        GOPROXY='https://proxy.golang.org,direct',GOSUMDB='sum.golang.org',
        GOCACHE=str(target/'cache'),GOMODCACHE=str(target/'modules'))
    if os.name=='nt':environment['GOROOT']=str(target/'go')
    return environment


def _build_native(executable,target,environment,destination):
    target=Path(target).resolve();destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    fingerprint=source_fingerprint()
    suffix='.exe' if environment.get('GOOS')=='windows' or (not environment.get('GOOS') and os.name=='nt') else ''
    # Publish beside a running older executable, never overwrite its image.
    binary=destination/('gg-consensus-node-'+fingerprint[:16]+suffix)
    with tempfile.TemporaryDirectory(prefix='build-',dir=target) as scratch:
        build=Path(scratch)
        for source in source_files():shutil.copyfile(source,build/source.name)
        artifact=build/binary.name
        goos=environment.get('GOOS') or compiler_metadata(executable,target,environment)['goos']
        result=subprocess.run([str(executable),'build',*native_build_flags(goos),'-o',str(artifact),'.'],
            cwd=build,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=300,creationflags=FLAGS)
        if result.returncode:raise RuntimeError('GG_CONSENSUS_BUILD_FAILED')
        if source_fingerprint()!=fingerprint:raise RuntimeError('GG_CONSENSUS_SOURCE_CHANGED_DURING_BUILD')
        if binary.is_symlink() or binary.resolve().parent!=destination:
            raise RuntimeError('GG_CONSENSUS_BINARY_TARGET_INVALID')
        if binary.exists():
            if (not binary.is_file() or hashlib.sha256(binary.read_bytes()).digest()!=hashlib.sha256(artifact.read_bytes()).digest()):
                raise RuntimeError('GG_CONSENSUS_BINARY_TARGET_EXISTS')
        else:
            os.replace(artifact,binary)
        write_build_metadata(executable,binary,build,destination,environment)
    return binary


def build_cross_target(goos,goarch,target=TARGET):
    """Compile a separate artifact. Success does not establish target execution."""
    if (goos,goarch) not in {('linux','amd64'),('linux','arm64'),('android','arm64')}:
        raise ValueError('GG_CONSENSUS_CROSS_TARGET_UNSUPPORTED')
    target=Path(target).resolve();executable=ensure_go(target)
    environment=build_environment(target);environment.update(GOOS=goos,GOARCH=goarch)
    return _build_native(executable,target,environment,target/'cross'/f'{goos}-{goarch}')


def install(target=TARGET,light=True):
    target=Path(target).resolve();executable=ensure_go(target)
    compiler=compiler_metadata(executable,target)
    if compiler['goos']=='android' and compiler['goarch']!='arm64':
        raise RuntimeError('GG_CONSENSUS_ANDROID_ARM64_REQUIRED')
    if not (SOURCE/'go.sum').is_file():raise RuntimeError('GG_CONSENSUS_MODULE_LOCK_MISSING')
    binary=_build_native(executable,target,build_environment(target),target)
    if light:build_light_verifier(target)
    return binary


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',type=Path)
    parser.add_argument('--light-only',action='store_true')
    parser.add_argument('--native-only',action='store_true')
    parser.add_argument('--cross',choices=['linux/amd64','linux/arm64','android/arm64'])
    options=parser.parse_args()
    if sum(bool(value) for value in (options.light_only,options.native_only,options.cross))>1:parser.error('Choose one build mode')
    if options.cross:build_cross_target(*options.cross.split('/'),target=options.target or TARGET)
    elif options.light_only:build_light_verifier(options.target or TARGET)
    else:install(options.target or TARGET,light=not options.native_only)
    print('GG_CONSENSUS_TOOLCHAIN_INSTALLED')
