"""Install the pinned official Kaspa node in this user's app data directory."""
from pathlib import Path
import hashlib
import json
import os
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.application_paths import STATE_ROOT

VERSION = 'v2.1.0'
NAME = 'rusty-kaspa-v2.1.0-win64.zip'
DIGEST = 'fb25743a4b432d376c4ca49d8799769dbc6d5b070f0b502350ce32cfdb38ec0f'
ROOT = STATE_ROOT.parent / 'crypto-tools' / 'kaspa' / VERSION


def install():
    if os.name != 'nt':
        raise ValueError('WINDOWS_PACKAGE_ONLY')
    ROOT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / (NAME + '.part')
    try:
        request = urllib.request.Request('https://github.com/kaspanet/rusty-kaspa/releases/download/' + VERSION + '/' + NAME,
                                         headers={'User-Agent': 'GG-crypto-runtime/1'})
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(request, timeout=30) as response, archive.open('wb') as out:
            while chunk := response.read(1024*1024):
                size += len(chunk)
                if size > 64*1024*1024:
                    raise ValueError('RUNTIME_DOWNLOAD_LIMIT')
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != DIGEST:
            raise ValueError('RUNTIME_DIGEST_MISMATCH')
        with zipfile.ZipFile(archive) as package:
            nodes = [r for r in package.infolist() if Path(r.filename).name == 'kaspad.exe']
            if len(nodes) != 1 or nodes[0].file_size > 200*1024*1024:
                raise ValueError('INVALID_RUNTIME_PACKAGE')
            target = ROOT / 'kaspad.exe'
            temporary = ROOT / 'kaspad.exe.new'
            with package.open(nodes[0]) as source, temporary.open('wb') as out:
                while chunk := source.read(1024*1024):
                    out.write(chunk)
            temporary.replace(target)
        (ROOT / 'provenance.json').write_text(json.dumps({'provider': 'kaspanet/rusty-kaspa',
            'version': VERSION, 'asset': NAME, 'verified_digest': DIGEST, 'license': 'ISC'}, indent=2)+'\n', encoding='utf-8')
        return {'status': 'READY', 'version': VERSION, 'download_bytes': size}
    finally:
        archive.unlink(missing_ok=True)


if __name__ == '__main__':
    if '--compiler' in sys.argv:
        destination = STATE_ROOT.parent/'crypto-tools/silverscript/v1.0.0'
        destination.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request('https://github.com/kaspanet/silverscript/releases/download/v1.0.0/silverc-windows-x86_64.zip', headers={'User-Agent':'GG-crypto-runtime/1'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(8*1024*1024+1)
        if len(data)>8*1024*1024 or hashlib.sha256(data).hexdigest() != '3e0d660c15a9e7ac90f3960da24d348b076b1891481bfe758db18accc8a102e1':
            raise ValueError('COMPILER_DIGEST_MISMATCH')
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [r for r in archive.infolist() if Path(r.filename).name == 'silverc.exe']
            if len(files)!=1 or files[0].file_size > 32*1024*1024:
                raise ValueError('INVALID_COMPILER_PACKAGE')
            temporary = destination/'silverc.exe.new'
            temporary.write_bytes(archive.read(files[0]))
            temporary.replace(destination/'silverc.exe')
        print(json.dumps({'status':'READY','compiler':'silverc','version':'v1.0.0'}))
    else:
        print(json.dumps(install()))
