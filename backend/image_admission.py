"""Check encoded and decoded image budgets before Qt allocates pixel storage."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QImageReader


def decode_image(data: bytes, *, max_encoded_bytes: int, max_dimension: int,
                 max_decoded_bytes: int) -> QImage:
    if (not isinstance(data,bytes) or not data or len(data)>max_encoded_bytes
            or min(max_encoded_bytes,max_dimension,max_decoded_bytes)<=0):
        raise ValueError('IMAGE_ENCODED_BUDGET')
    # Keep Qt's own allocation guard active too. Never loosen a stricter cap
    # configured by the app or another reader; the cap is process-wide.
    cap=64
    existing=QImageReader.allocationLimit()
    if existing<=0 or existing>cap:QImageReader.setAllocationLimit(cap)
    buffer=QBuffer();buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader=QImageReader(buffer);reader.setDecideFormatFromContent(True)
    size=reader.size();width,height=size.width(),size.height()
    if (width<1 or height<1 or max(width,height)>max_dimension
            or width*height*4>max_decoded_bytes):
        raise ValueError('IMAGE_PIXEL_BUDGET')
    image=reader.read()
    if (image.isNull() or image.width()!=width or image.height()!=height
            or image.sizeInBytes()>max_decoded_bytes):
        raise ValueError('IMAGE_DECODE_FAILED')
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull() or image.sizeInBytes()>max_decoded_bytes:
        raise ValueError('IMAGE_DECODED_BUDGET')
    return image
