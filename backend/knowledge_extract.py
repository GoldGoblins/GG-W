"""Disposable QtPdf worker for local knowledge text and page rasters.

The desktop invokes this module through ``run_bounded``. No document code,
links, external tools, credentials or model calls are used.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import sys

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 512
MAX_TEXT_CHARS = 2_000_000
MAX_PAGE_CHARS = 200_000
MAX_RASTER_SIDE = 2200


def extract(path: Path, *, page: int | None = None, output: Path | None = None) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtPdf import QPdfDocument

    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("FILE_SIZE_LIMIT")
    with path.open("rb") as handle:
        if not handle.read(8).startswith(b"%PDF-"):
            raise ValueError("INVALID_PDF")
    app = QGuiApplication.instance() or QGuiApplication(["GG PDF reader"])
    document = QPdfDocument()
    try:
        error = document.load(str(path))
        if error in (QPdfDocument.Error.IncorrectPassword,
                     QPdfDocument.Error.UnsupportedSecurityScheme):
            raise ValueError("PDF_PASSWORD_REQUIRED")
        if error != QPdfDocument.Error.None_:
            raise ValueError("INVALID_PDF")
        count = document.pageCount()
        if not 1 <= count <= MAX_PAGES:
            raise ValueError("PDF_PAGE_LIMIT")
        if page is not None:
            if not output or not 1 <= page <= count:
                raise ValueError("INVALID_PAGE")
            size = document.pagePointSize(page - 1)
            if not all(math.isfinite(v) and v > 0 for v in (size.width(), size.height())):
                raise ValueError("INVALID_PAGE_SIZE")
            ratio = min(1600 / size.width(), MAX_RASTER_SIDE / size.height())
            target = QSize(max(1, round(size.width() * ratio)),
                           max(1, round(size.height() * ratio)))
            image = document.render(page - 1, target)
            if image.isNull() or not image.save(str(output), "PNG"):
                raise ValueError("PDF_RENDER_FAILED")
            return {"status": "PAGE_READY", "page": page, "pages": count,
                    "width": image.width(), "height": image.height()}
        pages, total = [], 0
        for index in range(count):
            text = document.getAllText(index).text()
            total += len(text)
            if total > MAX_TEXT_CHARS or len(text) > MAX_PAGE_CHARS:
                raise ValueError("PDF_TEXT_LIMIT")
            size = document.pagePointSize(index)
            pages.append({"page": index + 1, "text": text,
                          "width": size.width(), "height": size.height(),
                          "needs_ocr": not bool(text.strip())})
        return {"status": "EXTRACTED", "pages": pages,
                "needs_ocr": [p["page"] for p in pages if p["needs_ocr"]]}
    finally:
        document.close()
        del document
        # QtPdf releases Windows file mappings when its object is destroyed.
        gc.collect()
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("extract", "render"))
    parser.add_argument("source")
    parser.add_argument("--page", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if os.name == "nt":
            from backend.platform_process import apply_windows_worker_limits
            apply_windows_worker_limits(memory_bytes=512 * 1024 * 1024, cpu_seconds=35)
        value = extract(Path(args.source),
                        page=args.page if args.mode == "render" else None,
                        output=Path(args.output) if args.output else None)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        value = {"status": "ERROR", "reason": reason}
    # Source text goes only over the private pipe to the caller, never logging.
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    return 0 if value["status"] != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
