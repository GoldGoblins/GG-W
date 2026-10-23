"""Owned, bounded Qt textures for procedural GG guild emblems."""
import base64
from PySide6.QtCore import QObject, QByteArray
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick3D import QQuick3DTextureData


def aligned_attachment(socket_rotation, actor_rotation, offset):
    # glTF sockets retain the author's basis (including Blender's axis
    # conversion). Express the avatar-facing cloth in that actual basis.
    relative=socket_rotation.inverted()*actor_rotation
    return dict(position=relative.rotatedVector(offset),rotation=relative.toEulerAngles())


def emblem_texture_data(host, uri, owner):
    if not uri or not isinstance(owner, QObject):return None
    prefix='data:image/svg+xml;base64,'
    if not isinstance(uri,str) or not uri.startswith(prefix) or len(uri)>16384:return None
    entries=getattr(host,'_emblem_textures',None)
    if entries is None:entries={};host._emblem_textures=entries
    key=id(owner);entry=entries.get(key)
    if entry and entry[1]==uri:return entry[0]
    if entry is None and len(entries)>=128:return None
    try:image=QImage.fromData(QByteArray(base64.b64decode(uri[len(prefix):],validate=True)))
    except (ValueError,TypeError):return None
    if image.isNull() or image.width()!=256 or image.height()!=320:return None
    image=image.convertToFormat(QImage.Format.Format_RGBA8888).mirrored(False,True)
    if entry: texture=entry[0]
    else:
        texture=QQuick3DTextureData();QObject.setParent(texture,owner)
        QQmlEngine.setObjectOwnership(texture,QQmlEngine.ObjectOwnership.CppOwnership)
        owner.destroyed.connect(lambda:entries.pop(key,None))
        texture.setSize(image.size());texture.setFormat(QQuick3DTextureData.Format.RGBA8)
        texture.setHasTransparency(True)
    texture.setTextureData(bytes(image.constBits()))
    entries[key]=(texture,uri)
    return texture
