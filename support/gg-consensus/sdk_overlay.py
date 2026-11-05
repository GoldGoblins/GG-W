"""Verified derived SDK tree and temporary modfile; upstream cache unchanged."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import base64
import shutil
import zipfile

SOURCE=Path(__file__).resolve().parent

def _fs(path):
    # The SDK includes long documentation/test paths. Windows checks must use
    # the extended path form too; Go itself already supports those paths.
    path=Path(path)
    return Path('\\\\?\\'+str(path)) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path

def patch_records():
    value=json.loads((SOURCE/'sdk_patches.json').read_text(encoding='utf-8'))
    if value.get('schema')!='gg.consensus.sdk-patches.v1' or not isinstance(value.get('patches'),list):
        raise RuntimeError('GG_SDK_PATCH_RECIPE')
    validate_scope(value['patches'])
    return value['patches']

def transform(raw,record):
    if hashlib.sha256(raw).hexdigest()!=record['original_sha256']:
        raise RuntimeError('GG_SDK_PATCH_SOURCE_MISMATCH')
    old,new=record['old'].encode('ascii'),record['new'].encode('ascii')
    if not old or raw.count(old)!=record['count']:raise RuntimeError('GG_SDK_PATCH_MATCH_COUNT')
    result=raw.replace(old,new)
    if hashlib.sha256(result).hexdigest()!=record['patched_sha256']:
        raise RuntimeError('GG_SDK_PATCH_RESULT_MISMATCH')
    return result

def validate_scope(records):
    # Exact ordered resource-only hunks; no caller-selected SDK transformation.
    allowed=[
        ('mempool/reactor.go', 'ntx.String()', 'ntx.Hash()', 2),
        ('p2p/conn/connection.go', '\t\t// clear the slice without re-allocating.\n\t\t// http://stackoverflow.com/questions/16971741/how-do-you-clear-a-slice-in-go\n\t\t//   suggests this could be a memory leak, but we might as well keep the memory for the channel until it closes,\n\t\t//\tat which point the recving slice stops being used and should be garbage collected\n\t\tch.recving = ch.recving[:0] // make([]byte, 0, ch.desc.RecvBufferCapacity)\n', '\t\t// Keep small receive buffers, but release completed large messages.\n\t\t// Otherwise every peer/channel pins its largest historical message.\n\t\tif cap(ch.recving) > 256*1024 {\n\t\t\tch.recving = make([]byte, 0, ch.desc.RecvBufferCapacity)\n\t\t} else {\n\t\t\tch.recving = ch.recving[:0]\n\t\t}\n', 1),
        ('mempool/reactor.go', '\t\tcase <-memR.waitSyncCh:\n\t\t\t// EnableInOutTxs() has set WaitSync() to false.\n\t\tcase <-memR.Quit():', '\t\tcase <-memR.waitSyncCh:\n\t\t\t// EnableInOutTxs() has set WaitSync() to false.\n\t\tcase <-peer.Quit():\n\t\t\t// A disconnected peer must not retain its buffers until sync finishes.\n\t\t\treturn\n\t\tcase <-memR.Quit():', 1),
        ('mempool/reactor.go', '\tfor {\n\t\tif ps, ok := peer.Get(types.PeerStateKey).(PeerState); ok {\n\t\t\tpeerState = ps\n\t\t\tbreak\n\t\t}\n\t\t// Peer does not have a state yet.\n\t\ttime.Sleep(PeerCatchupSleepIntervalMS * time.Millisecond)\n\t}', '\tfor {\n\t\tif !peer.IsRunning() || !memR.IsRunning() {\n\t\t\treturn\n\t\t}\n\t\tif ps, ok := peer.Get(types.PeerStateKey).(PeerState); ok {\n\t\t\tpeerState = ps\n\t\t\tbreak\n\t\t}\n\t\t// A peer can disconnect before consensus installs its state.\n\t\tselect {\n\t\tcase <-time.After(PeerCatchupSleepIntervalMS * time.Millisecond):\n\t\tcase <-peer.Quit():\n\t\t\treturn\n\t\tcase <-memR.Quit():\n\t\t\treturn\n\t\t}\n\t}', 1),
        ('p2p/switch.go', '\treconnecting  *cmap.CMap\n', '\treconnecting  *cmap.CMap\n\treconnectMtx  sync.Mutex // atomic registration of one reconnect job per peer ID\n', 1),
        ('p2p/switch.go', 'func (sw *Switch) reconnectToPeer(addr *NetAddress) {\n\tif sw.reconnecting.Has(string(addr.ID)) {\n\t\treturn\n\t}\n\tsw.reconnecting.Set(string(addr.ID), addr)\n\tdefer sw.reconnecting.Delete(string(addr.ID))\n\n\tstart := time.Now()', 'func (sw *Switch) reconnectToPeer(addr *NetAddress) {\n\tsw.reconnectMtx.Lock()\n\tif sw.reconnecting.Has(string(addr.ID)) {\n\t\tsw.reconnectMtx.Unlock()\n\t\treturn\n\t}\n\tsw.reconnecting.Set(string(addr.ID), addr)\n\tsw.reconnectMtx.Unlock()\n\tdefer sw.reconnecting.Delete(string(addr.ID))\n\n\t// A successful handshake can be followed immediately by remote rejection.\n\t// Bound this success/disconnect cycle too, not only failed dial attempts.\n\tselect {\n\tcase <-time.After(reconnectInterval):\n\tcase <-sw.Quit():\n\t\treturn\n\t}\n\n\tstart := time.Now()', 1),
    ]
    required={'id','module','version','upstream_h1','patched_h1','file','original_sha256','patched_sha256','old','new','count'}
    try:
        if (not isinstance(records,list) or len(records)!=len(allowed)
                or len({item['id'] for item in records})!=len(records)
                or [(item['file'],item['old'],item['new'],item['count']) for item in records]!=allowed):
            raise RuntimeError('GG_SDK_PATCH_SCOPE')
        first=records[0]
        for item in records:
            if (set(item)!=required or item['module']!='github.com/cometbft/cometbft' or item['version']!='v0.40.0'
                    or item['upstream_h1']!=first['upstream_h1'] or item['patched_h1']!=first['patched_h1']):
                raise RuntimeError('GG_SDK_PATCH_SCOPE')
    except (KeyError,TypeError,IndexError):
        raise RuntimeError('GG_SDK_PATCH_SCOPE') from None


def overlay_flags(target,environment):
    target=Path(target).resolve();modules=Path(environment['GOMODCACHE']).resolve()
    records=patch_records();mod=(SOURCE/'go.mod').read_bytes();sums=(SOURCE/'go.sum').read_bytes()
    identity=hashlib.sha256(json.dumps(records,sort_keys=True).encode()+mod+sums+Path(__file__).read_bytes()).hexdigest()
    directory=target/'source-overlays'/identity
    if not directory.resolve().is_relative_to(target):raise RuntimeError('GG_SDK_PATCH_CACHE_PATH')
    validate_scope(records)
    directory.parent.mkdir(parents=True,exist_ok=True)
    record=records[0]
    prefix=record['module']+'@'+record['version']+'/'
    expected=next((line.split()[2] for line in sums.decode().splitlines() if line.startswith(record['module']+' '+record['version']+' ')),None)
    if expected!=record['upstream_h1']:raise RuntimeError('GG_SDK_PATCH_MODULE_SUM')
    archive=modules/'cache/download'/record['module']/'@v'/(record['version']+'.zip')
    sdk=directory/'cometbft'
    patched_mod=mod+b'\nreplace github.com/cometbft/cometbft => '+json.dumps(sdk.as_posix()).encode()+b'\n'
    # Go forbids overlays inside GOMODCACHE. Verify the original Go module ZIP,
    # derive a separate exact tree, then select it ONLY in this build's modfile.
    # Neither the application's go.mod/go.sum nor upstream cache is changed.
    staging=None
    if not directory.exists():staging=Path(tempfile.mkdtemp(prefix='sdk-',dir=directory.parent))
    names=set();upstream=hashlib.sha256();patched=hashlib.sha256()
    try:
        with zipfile.ZipFile(archive) as package:
            for name in sorted(package.namelist()):
                if not name.startswith(prefix) or '\n' in name:raise RuntimeError('GG_SDK_PATCH_ZIP_PATH')
                relative=name[len(prefix):];parts=Path(relative).parts
                if not relative or Path(relative).is_absolute() or '..' in parts:raise RuntimeError('GG_SDK_PATCH_ZIP_PATH')
                raw=package.read(name)
                upstream.update((hashlib.sha256(raw).hexdigest()+'  '+name+'\n').encode())
                for item in records:
                    if relative==item['file']:raw=transform(raw,item)
                patched.update((hashlib.sha256(raw).hexdigest()+'  '+name+'\n').encode());names.add(relative)
                if staging is not None:
                    path=_fs(staging/'cometbft'/relative);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                else:
                    path=_fs(sdk/relative)
                    if path.is_symlink() or not path.is_file() or path.read_bytes()!=raw:raise RuntimeError('GG_SDK_PATCH_CACHE_CHANGED')
        if 'h1:'+base64.b64encode(upstream.digest()).decode()!=record['upstream_h1']:raise RuntimeError('GG_SDK_PATCH_MODULE_SUM')
        if 'h1:'+base64.b64encode(patched.digest()).decode()!=record['patched_h1']:raise RuntimeError('GG_SDK_PATCH_RESULT_MISMATCH')
        if staging is not None:
            (staging/'build.mod').write_bytes(patched_mod);(staging/'build.sum').write_bytes(sums)
            try:os.rename(staging,directory);staging=None
            except OSError:
                if not directory.is_dir():raise
                # Another verified builder completed the same immutable cache.
                return overlay_flags(target,environment)
        else:
            actual=set()
            for path in _fs(sdk).rglob('*'):
                if path.is_symlink():raise RuntimeError('GG_SDK_PATCH_CACHE_PATH')
                if path.is_file():actual.add(path.relative_to(_fs(sdk)).as_posix())
            if actual!=names or (directory/'build.mod').read_bytes()!=patched_mod or (directory/'build.sum').read_bytes()!=sums:
                raise RuntimeError('GG_SDK_PATCH_CACHE_CHANGED')
    finally:
        if staging is not None:
            if staging.resolve().parent!=directory.parent.resolve():raise RuntimeError('GG_SDK_PATCH_CACHE_PATH')
            shutil.rmtree(_fs(staging))
    return ['-modfile',str(directory/'build.mod')]
