"""User-selected raster references, copied by content into private MP state."""
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import warnings
from backend.platform_support import local_file_path
from backend.platform_files import atomic_replace

MAX_BYTES=8*1024*1024
MAX_PIXELS=16_000_000


def import_image(source,root):
    from PIL import Image
    path=local_file_path(source)
    if not path.is_file() or path.is_symlink():raise ValueError('MARKETPLACE_IMAGE_LOCAL_FILE')
    with path.open('rb') as stream: data=stream.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError('MARKETPLACE_IMAGE_SIZE')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            image=Image.open(io.BytesIO(data))
            if image.format not in {'PNG','JPEG','WEBP'} or image.width*image.height>MAX_PIXELS or getattr(image,'is_animated',False):raise ValueError('MARKETPLACE_IMAGE_FORMAT_OR_DIMENSIONS')
            width,height=image.size;extension={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[image.format];image.verify()
            with Image.open(io.BytesIO(data)) as decoded: decoded.load()
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise ValueError('MARKETPLACE_IMAGE_INVALID') from None
    key=hashlib.sha256(data).hexdigest()+'.'+extension;directory=Path(root)/'media';directory.mkdir(parents=True,exist_ok=True)
    target=directory/key
    if not target.exists():
        existing=[p for p in directory.iterdir() if p.is_file() and not p.is_symlink()]
        if len(existing)>=1024 or sum(p.stat().st_size for p in existing)+len(data)>512*1024*1024:raise ValueError('MARKETPLACE_IMAGE_LIBRARY_LIMIT')
        descriptor,name=tempfile.mkstemp(dir=directory,prefix='.image-',suffix='.tmp');temporary=Path(name)
        try:
            with os.fdopen(descriptor,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            temporary.chmod(0o600);atomic_replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
    return {'id':key,'url':target.resolve().as_uri(),'width':width,'height':height,'bytes':len(data),'status':'LOCAL_REFERENCE'}


def image_url(key,root):
    if not re.fullmatch(r'[a-f0-9]{64}\.(?:png|jpg|webp)',str(key)):return ''
    path=Path(root)/'media'/key
    return path.resolve().as_uri() if path.is_file() and not path.is_symlink() else ''
