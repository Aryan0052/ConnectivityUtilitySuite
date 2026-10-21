"""Large artwork (4K background, 3000 x 2000 product photos) is decoded in a background thread and kept
in a reduced size, so the GUI thread never spends time on PNG decoding or on scaling huge pictures.

    preload(path, max_w, max_h)  start decoding now (returns at once)
    load(path, max_w, max_h)     the decoded QImage - waits only if the thread is still busy, and decodes on
                                 the spot if preload() was never called
    pixmap(path, max_w, max_h)   same as load() but as QPixmap (QPixmap must be made on the GUI thread)

Only QImage is used in the thread (QImage is thread safe, QPixmap is not).
"""
import threading

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

_jobs = {}              # (path, max_w, max_h) -> {"event": Event, "image": QImage}
_lock = threading.Lock()


def _reduce(image, max_w, max_h):
    if image.isNull() or not (max_w and max_h) or (image.width() <= max_w and image.height() <= max_h):
        return image
    return image.scaled(QSize(max_w, max_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)


def preload(path, max_w=0, max_h=0, extra=()):
    """Decode path once in a thread and keep it at max_w x max_h (0 = full size). `extra` is a tuple of
    further (max_w, max_h) sizes made from the same decoding."""
    sizes = [(max_w, max_h)] + [tuple(e) for e in extra]
    with _lock:
        fresh = [size for size in sizes if (str(path), *size) not in _jobs]
        if not fresh:
            return
        jobs = {}
        for size in fresh:
            jobs[size] = {"event": threading.Event(), "image": QImage()}
            _jobs[(str(path), *size)] = jobs[size]

    def work():
        try:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            full = reader.read()
        except Exception:
            full = QImage()
        for size, job in jobs.items():
            try:
                job["image"] = _reduce(full, *size)
            except Exception:
                job["image"] = QImage()
            job["event"].set()

    threading.Thread(target=work, name="image-preload", daemon=True).start()


def load(path, max_w=0, max_h=0):
    key = (str(path), max_w, max_h)
    preload(*key)
    job = _jobs[key]
    job["event"].wait()
    return job["image"]


def pixmap(path, max_w=0, max_h=0):
    image = load(path, max_w, max_h)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()
