"""Read chat paste data without treating text or empty images as CLI commands."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile
import uuid

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread
from PySide6.QtGui import QGuiApplication

_images: tempfile.TemporaryDirectory | None = None


def _wait_for_clipboard(milliseconds: int) -> None:
    if QCoreApplication.instance() is not None:
        # Service delayed clipboard rendering without re-entering key input.
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 10)
        QThread.msleep(milliseconds)


def read_paste(*, image_paths: bool = True) -> tuple[str, str]:
    """Return terminal input and an optional user-facing clipboard error."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return "", ""
    advertised_image = False
    image = None
    for delay in ((0, 15, 35, 70) if os.name == "nt" else (0,)):
        if delay:
            _wait_for_clipboard(delay)
        mime = clipboard.mimeData()
        if mime is not None and mime.hasImage():
            advertised_image = True
            image = clipboard.image()
            if not image.isNull():
                break
        else:
            text = clipboard.text() or ""
            if text:
                return text, ""
    else:
        if advertised_image:
            return "", "Bilden i urklipp kunde inte läsas. Kopiera bilden på nytt från källan."
        return "", ""
    if image is not None:
        if not image_paths:
            # Preserve the other terminal's native image-paste protocol.
            clipboard.setImage(image.copy())
            return "\x16", ""
        # Give the CLI a stable image attachment. Reading the system clipboard
        # again inside the child races Windows clipboard owners and monitors.
        # Files remain available for pending messages until the desktop exits.
        global _images
        try:
            if _images is None:
                _images = tempfile.TemporaryDirectory(prefix="gg-chat-images-")
            path = Path(_images.name) / (uuid.uuid4().hex + ".png")
            if not image.save(str(path), "PNG"):
                path.unlink(missing_ok=True)
                return "", "Bilden kunde inte förberedas för inklistring. Försök igen."
        except OSError:
            return "", "Bilden kunde inte förberedas för inklistring. Försök igen."
        return '"' + path.as_posix() + '"', ""
    return "", ""
