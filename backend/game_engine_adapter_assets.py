"""Map legacy addon asset names into the packaged, local GG asset tree."""
from pathlib import Path
from urllib.parse import unquote,urlparse
from backend.platform_support import local_file_path
from backend.game_engine_legacy import manifest_path
PROJECT=Path(__file__).resolve().parents[1]
def asset_path(value):
    key=str(value or '').replace('\\','/')
    if key.startswith('file:'):
        url=urlparse(key)
        if url.netloc not in ('','localhost'):raise ValueError('Escaping game asset')
        path=local_file_path(key).resolve()
    elif key.casefold().startswith('interface/addons/'):path=(PROJECT/'qml/game/framexml'/key[len('Interface/AddOns/'):]).resolve()
    else:path=(PROJECT/'qml'/key.removeprefix('qml/')).resolve()
    root=(PROJECT/'qml').resolve()
    if not path.is_relative_to(root):raise ValueError('Escaping game asset')
    relative=path.relative_to(root).as_posix()
    migrated=manifest_path(relative)
    if migrated!=relative:
        path=(root/migrated).resolve()
        if not path.is_relative_to(root):raise ValueError('Escaping game asset')
    if not path.exists():
        # The original asset namespace is case insensitive. Resolve each segment
        # inside our own tree; ambiguous names and symlinks never widen the root.
        candidate=root
        for segment in path.relative_to(root).parts:
            direct=candidate/segment
            if not direct.exists() and candidate.is_dir():
                matches=[p for p in candidate.iterdir() if p.name.casefold()==segment.casefold()]
                if len(matches)>1:raise ValueError('Ambiguous game asset name')
                if matches:direct=matches[0]
            candidate=direct.resolve()
            if not candidate.is_relative_to(root):raise ValueError('Escaping game asset')
        path=candidate
    return path

def texture_path(value):
    path=asset_path(value)
    if path==PROJECT/'qml/game/framexml/white.png' and not path.is_file():
        return PROJECT/'qml/components/engine/white.png'
    if not path.suffix and not path.is_file():
        for suffix in ('.blp','.tga','.png','.svg'):
            candidate=asset_path(str(path)+suffix)
            if candidate.is_file():return candidate
    return path
