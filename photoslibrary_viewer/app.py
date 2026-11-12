"""HTTP server: JSON API plus image/video delivery for the browser UI."""

from __future__ import annotations

import base64
import hmac
import logging
import mimetypes
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .library import ALBUM_KIND_FOLDER, Asset, Library, Snapshot
from .media import VIDEO_MIME, Media

log = logging.getLogger("photoslibrary_viewer")

STATIC = Path(__file__).parent / "static"
IMAGE_CACHE = "public, max-age=604800"


class Settings:
    def __init__(self) -> None:
        self.library = os.environ.get("PLV_LIBRARY", "")
        self.cache = os.environ.get("PLV_CACHE", "./cache")
        self.title = os.environ.get("PLV_TITLE", "")
        self.show_hidden = os.environ.get("PLV_SHOW_HIDDEN", "0") == "1"
        self.refresh = int(os.environ.get("PLV_REFRESH", "300"))
        self.user = os.environ.get("PLV_USER", "")
        self.password = os.environ.get("PLV_PASSWORD", "")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.library:
        raise SystemExit("Set PLV_LIBRARY to the path of a .photoslibrary")
    cache = Path(settings.cache)
    cache.mkdir(parents=True, exist_ok=True)
    library = Library(settings.library, cache, show_hidden=settings.show_hidden)
    library.refresh(force=True)
    media = Media(library.path, cache)
    search = _SearchIndex()

    app = FastAPI(title="photoslibrary-viewer", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048)

    if settings.password:

        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            header = request.headers.get("authorization", "")
            ok = False
            if header.startswith("Basic "):
                try:
                    given = base64.b64decode(header[6:])
                    user, _, pw = given.partition(b":")
                    ok = hmac.compare_digest(pw, settings.password.encode()) and (
                        not settings.user or hmac.compare_digest(user, settings.user.encode())
                    )
                except Exception:
                    ok = False
            if not ok:
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="photos", charset="UTF-8"'},
                )
            return await call_next(request)

    if settings.refresh > 0:
        def watch() -> None:
            while True:
                time.sleep(settings.refresh)
                try:
                    library.refresh()
                except Exception:
                    log.exception("refresh failed")

        threading.Thread(target=watch, daemon=True, name="refresh").start()

    def snap() -> Snapshot:
        return library.snap

    def asset_or_404(pk: int) -> Asset:
        a = snap().assets.get(pk)
        if a is None:
            raise HTTPException(404)
        return a

    # ------------------------------------------------------------------ API

    @app.get("/api/info")
    def info() -> dict:
        s = snap()
        videos = sum(1 for a in s.assets.values() if a.is_video)
        return {
            "version": __version__,
            "title": settings.title or (
                library.path.stem if library.path.suffix == ".photoslibrary" else "Photos"
            ),
            "assets": len(s.assets),
            "videos": videos,
            "favorites": sum(1 for a in s.assets.values() if a.favorite),
            "albums": sum(1 for a in s.albums.values() if not a.is_folder),
            "people": len(s.people),
            "places": sum(1 for a in s.assets.values() if a.latitude is not None),
            "loaded": s.loaded_at,
            "hidden": settings.show_hidden,
        }

    @app.get("/api/assets")
    def assets(view: str = "library") -> JSONResponse:
        s = snap()
        title = ""
        kind, _, arg = view.partition(":")
        if kind == "library":
            pks = s.timeline
        elif kind == "favorites":
            pks = [pk for pk in s.timeline if s.assets[pk].favorite]
        elif kind == "videos":
            pks = [pk for pk in s.timeline if s.assets[pk].is_video]
        elif kind == "live":
            pks = [pk for pk in s.timeline if s.assets[pk].is_live]
        elif kind == "edited":
            pks = [pk for pk in s.timeline if s.assets[pk].edited]
        elif kind == "hidden":
            pks = [pk for pk in s.timeline if s.assets[pk].hidden]
        elif kind == "places":
            pks = [pk for pk in s.timeline if s.assets[pk].latitude is not None]
        elif kind == "album":
            album = s.albums.get(_int(arg))
            if album is None:
                raise HTTPException(404)
            pks, title = album.assets, album.title
        elif kind == "person":
            person = s.people.get(_int(arg))
            if person is None:
                raise HTTPException(404)
            pks, title = person.assets, person.name
        elif kind == "search":
            pks, title = search.query(s, arg), arg
        else:
            raise HTTPException(400, "unknown view")
        items = []
        for pk in pks:
            a = s.assets[pk]
            items.append([pk, int(a.date + a.tz_offset), a.flags, round(a.duration)])
        payload = {"view": view, "title": title, "items": items}
        if kind == "places":
            payload["geo"] = [
                [pk, round(s.assets[pk].latitude, 5), round(s.assets[pk].longitude, 5)]
                for pk in pks
            ]
        return JSONResponse(payload)

    @app.get("/api/albums")
    def albums() -> list:
        s = snap()
        children: dict[int | None, list] = {}
        for album in s.albums.values():
            parent = album.parent if album.parent in s.albums else None
            children.setdefault(parent, []).append(album)

        def build(parent: int | None) -> list:
            out = []
            for album in children.get(parent, []):
                node = {
                    "id": album.pk,
                    "title": album.title,
                    "folder": album.kind == ALBUM_KIND_FOLDER,
                    "count": len(album.assets),
                    "key": album.key_asset,
                }
                if node["folder"]:
                    node["children"] = build(album.pk)
                    if node["key"] is None:
                        node["key"] = next(
                            (c["key"] for c in node["children"] if c["key"]), None
                        )
                    node["count"] = sum(c["count"] for c in node["children"])
                out.append(node)
            return out

        return build(None)

    @app.get("/api/people")
    def people() -> list:
        s = snap()
        rows = [
            {"id": p.pk, "name": p.name, "count": len(p.assets), "face": p.key_face}
            for p in s.people.values()
        ]
        rows.sort(key=lambda r: (-r["count"], r["name"].casefold()))
        return rows

    @app.get("/api/asset/{pk}")
    def asset(pk: int) -> dict:
        s = snap()
        a = asset_or_404(pk)
        original = media.original(a)
        details = {
            "id": a.pk,
            "uuid": a.uuid,
            "date": int(a.date),
            "tz": a.tz_offset,
            "filename": a.original_filename,
            "title": a.title,
            "description": a.description,
            "keywords": a.keywords,
            "width": a.width,
            "height": a.height,
            "duration": a.duration,
            "video": a.is_video,
            "live": a.is_live and media.live_video(a) is not None,
            "edited": a.edited,
            "favorite": a.favorite,
            "lat": a.latitude,
            "lon": a.longitude,
            "size": original.stat().st_size if original else None,
            "available": original is not None,
            "playable": _playable(media, a),
            "albums": [
                {"id": pk_, "title": s.albums[pk_].title}
                for pk_ in s.asset_albums.get(a.pk, [])
                if pk_ in s.albums
            ],
            "people": [
                {"id": pk_, "name": s.people[pk_].name}
                for pk_ in s.asset_people.get(a.pk, [])
                if pk_ in s.people
            ],
        }
        details.update(_exif(library, a.pk))
        return details

    # ---------------------------------------------------------------- media

    def image(path: Path | None) -> FileResponse:
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": IMAGE_CACHE})

    @app.get("/t/{pk}")
    def thumb(pk: int):
        return image(media.thumb(asset_or_404(pk)))

    @app.get("/p/{pk}")
    def preview(pk: int):
        return image(media.preview(asset_or_404(pk)))

    @app.get("/f/{pk}")
    def full(pk: int):
        return image(media.full(asset_or_404(pk)))

    @app.get("/face/{face}")
    def face(face: int):
        s = snap()
        f = s.faces.get(face)
        if f is None or f.asset not in s.assets:
            raise HTTPException(404)
        return image(media.face(s.assets[f.asset], f))

    @app.get("/v/{pk}")
    def video(pk: int, request: Request):
        a = asset_or_404(pk)
        return _ranged(media.video(a), request)

    @app.get("/live/{pk}")
    def live(pk: int, request: Request):
        return _ranged(media.live_video(asset_or_404(pk)), request)

    @app.get("/o/{pk}")
    def original(pk: int):
        a = asset_or_404(pk)
        path = media.original(a)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, filename=a.original_filename or path.name)

    # --------------------------------------------------------------- static

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


# ---------------------------------------------------------------- helpers


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise HTTPException(400) from None


def _playable(media: Media, a: Asset) -> bool:
    if not a.is_video:
        return False
    path = media.video(a)
    return path is not None and path.suffix.lower() in {".mp4", ".m4v", ".mov", ".webm"}


def _exif(library: Library, pk: int) -> dict:
    """Camera details from ZEXTENDEDATTRIBUTES, read on demand."""
    db = library.cache_dir / "db" / "Photos.sqlite"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(ZEXTENDEDATTRIBUTES)")}
        if not cols:
            return {}
        want = [
            c for c in (
                "ZCAMERAMAKE", "ZCAMERAMODEL", "ZLENSMODEL", "ZISO", "ZAPERTURE",
                "ZSHUTTERSPEED", "ZFOCALLENGTH", "ZFOCALLENGTHIN35MM", "ZCODEC", "ZFPS",
            ) if c in cols
        ]
        row = con.execute(
            f"SELECT {', '.join(want)} FROM ZEXTENDEDATTRIBUTES WHERE ZASSET = ?", (pk,)
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    r = dict(row)
    make, model = r.get("ZCAMERAMAKE") or "", r.get("ZCAMERAMODEL") or ""
    # "Canon" + "Canon PowerShot G1 X" -> "Canon PowerShot G1 X"
    camera = model if make and model.lower().startswith(make.lower()) else f"{make} {model}".strip()
    return {
        "camera": camera or None,
        "lens": r.get("ZLENSMODEL"),
        "iso": r.get("ZISO"),
        "aperture": r.get("ZAPERTURE"),
        "shutter": r.get("ZSHUTTERSPEED"),
        "focal": r.get("ZFOCALLENGTH"),
        "focal35": r.get("ZFOCALLENGTHIN35MM"),
        "codec": r.get("ZCODEC"),
        "fps": r.get("ZFPS"),
    }


def _ranged(path: Path | None, request: Request) -> Response:
    """Serve a file with HTTP range support (needed for video seeking)."""
    if path is None:
        raise HTTPException(404)
    size = path.stat().st_size
    mime = VIDEO_MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if mime == "video/quicktime":
        # Browsers play H.264/HEVC .mov files when told it is MP4.
        mime = "video/mp4"
    mime = mime or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": IMAGE_CACHE}
    rng = request.headers.get("range", "")
    if not rng.startswith("bytes="):
        headers["Content-Length"] = str(size)
        return StreamingResponse(_read(path, 0, size), media_type=mime, headers=headers)
    first, _, last = rng[6:].split(",")[0].partition("-")
    try:
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:  # suffix range: last N bytes
            start = max(size - int(last), 0)
            end = size - 1
    except ValueError:
        start, end = 0, size - 1
    if start >= size or start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    return StreamingResponse(
        _read(path, start, length), status_code=206, media_type=mime, headers=headers
    )


def _read(path: Path, start: int, length: int, chunk: int = 512 * 1024) -> Iterator[bytes]:
    with path.open("rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


class _SearchIndex:
    """Case-insensitive substring search over names, titles, keywords,
    album titles and people; rebuilt whenever the snapshot changes."""

    def __init__(self) -> None:
        self._for: Snapshot | None = None
        self._text: list[tuple[int, str]] = []
        self._lock = threading.Lock()

    def _build(self, s: Snapshot) -> None:
        text = []
        for pk in s.timeline:
            a = s.assets[pk]
            parts = [a.original_filename, a.title, a.description, *a.keywords]
            parts += [s.albums[x].title for x in s.asset_albums.get(pk, []) if x in s.albums]
            parts += [s.people[x].name for x in s.asset_people.get(pk, []) if x in s.people]
            text.append((pk, "\n".join(p for p in parts if p).casefold()))
        self._text, self._for = text, s

    def query(self, s: Snapshot, q: str) -> list[int]:
        with self._lock:
            if self._for is not s:
                self._build(s)
        terms = [t for t in q.casefold().split() if t]
        if not terms:
            return []
        return [pk for pk, text in self._text if all(t in text for t in terms)]
