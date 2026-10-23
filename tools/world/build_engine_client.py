"""Build the original protocol/SRP client beside the existing asset bridge."""
import hashlib,json,os,shutil,tempfile
from pathlib import Path
from build_engine_formats import run,source_digest,TARGET,PROJECT,native_directory,native_library_name

def build():
    run(['build','--release','--locked','-p','gg-engine-client'])
    source=TARGET/'release'/native_library_name('gg_engine_client');output=native_directory(PROJECT)
    output.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'gg.engine-client-build.v1','abi':1,'source_sha256':source_digest(),
             'binary_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'binary_bytes':source.stat().st_size}
    with tempfile.TemporaryDirectory(prefix='.gg-engine-client-',dir=output) as directory:
        temporary=Path(directory);shutil.copy2(source,temporary/source.name)
        (temporary/'engine-client-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
        for name in (source.name,'engine-client-build.json'):os.replace(temporary/name,output/name)
    print(json.dumps({'status':'PASS','binary_bytes':receipt['binary_bytes']}))

if __name__=='__main__':build()
