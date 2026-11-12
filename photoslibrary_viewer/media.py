"""Locate and, where needed, convert the image and video files of an asset.

Photos keeps several renditions per asset (paths relative to the library):

* ``originals/<dir>/<file>``                         – the imported original
* ``originals/<dir>/<uuid>_3.mov``                   – Live Photo movie
* ``resources/derivatives/masters/<X>/<uuid>_4_5005_c.jpeg`` – grid thumbnail
* ``resources/derivatives/<X>/<uuid>_1_105_c.jpeg``  – screen-size preview
* ``resources/renders/<X>/<uuid>_1_201_a.(jpeg|heic)`` – edited full image
* ``resources/renders/<X>/<uuid>_2_*_a.mov``         – edited video

``<X>`` is the first character of the UUID. Older libraries spell the folder
``Resources`` with a capital R, so both spellings are tried. Whatever the
browser cannot show directly (HEIC, TIFF, missing derivatives) is converted
to JPEG once and kept in the cache directory.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from PIL import Image, ImageOps

from .library import Asset, Face

try:  # optional: HEIC/HEIF support
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF = True
except ImportError:  # pragma: no cover
    HEIF = False

log = logging.getLogger(__name__)

BROWSER_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
BROWSER_VIDEO_EXT = {".mp4", ".m4v", ".mov", ".webm"}
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".3gp": "video/3gpp",
    ".mpg": "video/mpeg",
}

THUMB_SIZE = 480
PREVIEW_SIZE = 1600
FULL_SIZE = 3200
FACE_SIZE = 256
FULL_MAX_BYTES = 12 * 1024 * 1024


class Media:
    def __init__(self, library_path: Path, cache_dir: Path) -> None:
        self.root = library_path
        self.cache = cache_dir / "img"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.resources = next(
            (self.root / n for n in ("resources", "Resources") if (self.root / n).is_dir()),
            self.root / "resources",
        )
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ----------------------------------------------------------- locations

    def original(self, a: Asset) -> Path | None:
        p = self.root / "originals" / a.directory / a.filename
        if p.is_file():
            return p
        # Pre-Photos-5 layout (iPhoto / Photos ≤4): Masters/<dir>/<file>
        p = self.root / "Masters" / a.directory / a.filename
        return p if p.is_file() else None

    def live_video(self, a: Asset) -> Path | None:
        if not a.is_live:
            return None
        p = self.root / "originals" / a.directory / f"{a.uuid}_3.mov"
        return p if p.is_file() else None

    def _first(self, *paths: Path) -> Path | None:
        return next((p for p in paths if p.is_file()), None)

    def thumb_derivative(self, a: Asset) -> Path | None:
        x = a.uuid[0]
        d = self.resources / "derivatives"
        return self._first(
            d / "masters" / x / f"{a.uuid}_4_5005_c.jpeg",
            d / x / f"{a.uuid}_1_105_c.jpeg",
            d / x / f"{a.uuid}_1_102_o.jpeg",
        )

    def preview_derivative(self, a: Asset) -> Path | None:
        x = a.uuid[0]
        d = self.resources / "derivatives" / x
        return self._first(
            d / f"{a.uuid}_1_105_c.jpeg",
            d / f"{a.uuid}_1_102_o.jpeg",
            d / f"{a.uuid}_1_101_o.jpeg",
            d / f"{a.uuid}_1_100_o.jpeg",
        )

    def edited_image(self, a: Asset) -> Path | None:
        if not a.edited or a.is_video:
            return None
        r = self.resources / "renders" / a.uuid[0]
        return self._first(r / f"{a.uuid}_1_201_a.jpeg", r / f"{a.uuid}_1_201_a.heic")

    def edited_video(self, a: Asset) -> Path | None:
        if not a.edited:
            return None
        r = self.resources / "renders" / a.uuid[0]
        if not r.is_dir():
            return None
        return self._first(
            r / f"{a.uuid}_2_0_a.mov",
            r / f"{a.uuid}_2_100_a.mov",
            *sorted(r.glob(f"{a.uuid}_2_*_a.mov")),
        )

    def video(self, a: Asset) -> Path | None:
        return self.edited_video(a) or self.original(a)

    # ----------------------------------------------------------- renditions

    def thumb(self, a: Asset) -> Path | None:
        return self.thumb_derivative(a) or self._converted(a, "t", THUMB_SIZE)

    def preview(self, a: Asset) -> Path | None:
        """Screen-size image; for edited photos the edit wins."""
        if a.edited and not a.is_video and self.edited_image(a):
            return self._converted(a, "p", PREVIEW_SIZE)
        return self.preview_derivative(a) or self._converted(a, "p", PREVIEW_SIZE)

    def full(self, a: Asset) -> Path | None:
        """Largest image the browser can show (videos: their poster)."""
        if a.is_video:
            return self.preview(a)
        src = self.edited_image(a) or self.original(a)
        if src is None:
            return self.preview(a)
        # Browsers apply EXIF orientation themselves; only very large or
        # unsupported files (HEIC, TIFF, RAW) are converted.
        if src.suffix.lower() in BROWSER_IMAGE_EXT and src.stat().st_size <= FULL_MAX_BYTES:
            return src
        return self._converted(a, "f", FULL_SIZE)

    def face(self, a: Asset, f: Face) -> Path | None:
        out = self.cache / a.uuid[0] / f"{a.uuid}_face{f.pk}.jpeg"
        if out.is_file():
            return out
        src = self.preview_derivative(a) or self.thumb_derivative(a)
        if src is None:
            return None
        with self._lock(str(out)), Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            # Face centres are normalised with the origin at the bottom left;
            # ZSIZE is the face diameter relative to the longer image side.
            cx, cy = f.center_x * w, (1 - f.center_y) * h
            half = max(f.size * max(w, h) * 0.85, 16)
            box = (
                int(max(cx - half, 0)),
                int(max(cy - half, 0)),
                int(min(cx + half, w)),
                int(min(cy + half, h)),
            )
            crop = im.crop(box).convert("RGB")
            crop.thumbnail((FACE_SIZE, FACE_SIZE))
            _save_jpeg(crop, out)
        return out

    # ----------------------------------------------------------- conversion

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _converted(self, a: Asset, tag: str, size: int) -> Path | None:
        out = self.cache / a.uuid[0] / f"{a.uuid}_{tag}{size}.jpeg"
        if out.is_file():
            return out
        if a.is_video:
            src = self.preview_derivative(a) or self.thumb_derivative(a)
        else:
            src = self.edited_image(a) or self.original(a) or self.preview_derivative(a)
        if src is None:
            return None
        if src.suffix.lower() in {".heic", ".heif"} and not HEIF:
            log.warning("cannot convert %s: pillow-heif not installed", src)
            return None
        with self._lock(str(out)):
            if out.is_file():
                return out
            try:
                with Image.open(src) as im:
                    im.draft("RGB", (size, size))  # fast JPEG downscale
                    im = ImageOps.exif_transpose(im)
                    im = im.convert("RGB")
                    im.thumbnail((size, size), Image.Resampling.LANCZOS)
                    _save_jpeg(im, out)
            except Exception as e:  # unreadable or unsupported file
                log.warning("cannot convert %s: %s", src, e)
                return None
        return out


def _save_jpeg(im: Image.Image, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    im.save(tmp, "JPEG", quality=85, optimize=True, progressive=True)
    tmp.replace(out)
