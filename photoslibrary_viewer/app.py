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
from .library import (
    ALBUM_KIND_FOLDER, HIGHLIGHT_DAY_GROUP, HIGHLIGHT_MONTH, HIGHLIGHT_YEAR,
    SUB_PANORAMA, SUB_SCREEN_RECORDING, SUB_SCREENSHOT, SUB_SLOMO, SUB_TIMELAPSE,
    Asset, Library, Snapshot, top_places,
)
from .media import VIDEO_MIME, Media
from .search import SearchIndex

log = logging.getLogger("photoslibrary_viewer")

STATIC = Path(__file__).parent / "static"
IMAGE_CACHE = "public, max-age=604800"
DAY = 86400

# Smart views over the timeline: name -> predicate
SMART_VIEWS = {
    "favorites": lambda a: a.favorite,
    "videos": lambda a: a.is_video,
    "selfies": lambda a: a.selfie,
    "live": lambda a: a.is_live,
    "portrait": lambda a: a.portrait,
    "panoramas": lambda a: a.subtype == SUB_PANORAMA,
    "timelapse": lambda a: a.subtype == SUB_TIMELAPSE,
    "slomo": lambda a: a.subtype == SUB_SLOMO,
    "bursts": lambda a: a.burst is not None,
    "screenshots": lambda a: a.subtype == SUB_SCREENSHOT,
    "screenrec": lambda a: a.subtype == SUB_SCREEN_RECORDING,
    "edited": lambda a: a.edited,
    "hidden": lambda a: a.hidden,
    "places": lambda a: a.latitude is not None,
}


class Settings:
    def __init__(self) -> None:
        self.library = os.environ.get("PLV_LIBRARY", "")
        self.cache = os.environ.get("PLV_CACHE", "./cache")
        self.title = os.environ.get("PLV_TITLE", "")
        self.show_hidden = os.environ.get("PLV_SHOW_HIDDEN", "0") == "1"
        self.show_deleted = os.environ.get("PLV_SHOW_DELETED", "0") == "1"
        self.refresh = int(os.environ.get("PLV_REFRESH", "300"))
        self.user = os.environ.get("PLV_USER", "")
        self.password = os.environ.get("PLV_PASSWORD", "")
        self.tiles = os.environ.get(
            "PLV_MAP_TILES", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        self.tiles_attribution = os.environ.get(
            "PLV_MAP_ATTRIBUTION",
            '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        )


def _place_key(a: Asset) -> str:
    return f"{a.city}|{a.country}"


def _day_key(a: Asset) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(a.local_date))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.library:
        raise SystemExit("Set PLV_LIBRARY to the path of a .photoslibrary")
    cache = Path(settings.cache)
    cache.mkdir(parents=True, exist_ok=True)
    library = Library(
        settings.library, cache,
        show_hidden=settings.show_hidden, show_deleted=settings.show_deleted,
    )
    search = SearchIndex(library.path, cache)
    library.listeners.append(search.rebuild)
    library.refresh(force=True)
    media = Media(library.path, cache)
    title = settings.title or (
        library.path.stem if library.path.suffix == ".photoslibrary" else "Photos"
    )

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

    def card(pks: list[int], s: Snapshot, key: int | None = None) -> dict:
        return {
            "key": key if key in s.assets else (pks[len(pks) // 2] if pks else None),
            "count": len(pks),
            "places": top_places([s.assets[pk] for pk in pks]),
        }

    # ------------------------------------------------------------------ API

    @app.get("/api/info")
    def info() -> dict:
        s = snap()
        counts = {name: 0 for name in SMART_VIEWS}
        for pk in s.timeline:
            a = s.assets[pk]
            for name, pred in SMART_VIEWS.items():
                if pred(a):
                    counts[name] += 1
        counts["library"] = len(s.timeline)
        counts["days"] = sum(1 for pk in s.timeline if s.assets[pk].curated)
        if settings.show_deleted:
            counts["deleted"] = len(s.deleted)
        if not settings.show_hidden:
            counts.pop("hidden")
        return {
            "version": __version__,
            "title": title,
            "assets": len(s.timeline),
            "videos": counts["videos"],
            "counts": counts,
            "albums": sum(1 for a in s.albums.values() if not a.is_folder),
            "people": len(s.people),
            "memories": len(s.memories),
            "imports": len(s.imports),
            "cities": len({_place_key(s.assets[pk]) for pk in s.timeline if s.assets[pk].city}),
            "years": sum(1 for h in s.highlights.values() if h.kind == HIGHLIGHT_YEAR and h.assets),
            "loaded": s.loaded_at,
            "hidden": settings.show_hidden,
            "deleted": settings.show_deleted,
            "map": {"tiles": settings.tiles, "attribution": settings.tiles_attribution},
        }

    @app.get("/api/assets")
    def assets(view: str = "library") -> JSONResponse:
        s = snap()
        title = subtitle = ""
        group = "month"
        extra: dict = {}
        kind, _, arg = view.partition(":")
        if kind == "library":
            pks = s.timeline
        elif kind == "days":
            pks = [pk for pk in s.timeline if s.assets[pk].curated] or s.timeline
            group = "day"
        elif kind in SMART_VIEWS:
            if kind == "hidden" and not settings.show_hidden:
                raise HTTPException(404)
            pred = SMART_VIEWS[kind]
            pks = [pk for pk in s.timeline if pred(s.assets[pk])]
        elif kind == "deleted":
            if not settings.show_deleted:
                raise HTTPException(404)
            pks, group = s.deleted, "none"
        elif kind == "album":
            album = s.albums.get(_int(arg))
            if album is None:
                raise HTTPException(404)
            pks, title, group = album.assets, album.title, "none"
        elif kind == "person":
            person = s.people.get(_int(arg))
            if person is None:
                raise HTTPException(404)
            pks, title = person.assets, person.name
        elif kind == "memory":
            memory = next((m for m in s.memories if m.pk == _int(arg)), None)
            if memory is None:
                raise HTTPException(404)
            pks, title, subtitle, group = memory.assets, memory.title, memory.subtitle, "day"
        elif kind in ("month", "trip"):
            h = s.highlights.get(_int(arg))
            if h is None:
                raise HTTPException(404)
            pks = sorted(h.assets, key=lambda pk: s.assets[pk].date, reverse=True)
            title, subtitle, group = h.title, top_places([s.assets[pk] for pk in pks]), "day"
        elif kind == "import":
            sess = next((x for x in s.imports if x.pk == _int(arg)), None)
            if sess is None:
                raise HTTPException(404)
            pks, group = sess.assets, "none"
            title, subtitle = time.strftime("%Y-%m-%d %H:%M", time.localtime(sess.date)), sess.source
        elif kind == "place":
            pks = [pk for pk in s.timeline if s.assets[pk].city and _place_key(s.assets[pk]) == arg]
            city, _, country = arg.partition("|")
            title, subtitle = city, country
        elif kind == "search":
            pks, extra["chips"] = search.query(s, arg)
            title = arg
        else:
            raise HTTPException(400, "unknown view")
        items = []
        for pk in pks:
            a = s.assets[pk]
            items.append([pk, int(a.local_date), a.flags, round(a.duration)])
        payload = {"view": view, "title": title, "subtitle": subtitle, "group": group,
                   "items": items, **extra}
        if group == "day":
            by_day: dict[str, list[Asset]] = {}
            for pk in pks:
                by_day.setdefault(_day_key(s.assets[pk]), []).append(s.assets[pk])
            payload["days"] = {d: top_places(v) for d, v in by_day.items() if top_places(v)}
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

    @app.get("/api/memories")
    def memories() -> list:
        s = snap()
        return [
            {"id": m.pk, "title": m.title, "subtitle": m.subtitle, "favorite": m.favorite,
             "date": int(m.date), **card(m.assets, s, m.key_asset)}
            for m in s.memories
        ]

    @app.get("/api/years")
    def years() -> list:
        s = snap()
        out = [
            {"year": h.title, "start": int(h.start), **card(h.assets, s, h.key_asset)}
            for h in s.highlights.values() if h.kind == HIGHLIGHT_YEAR and h.assets
        ]
        return sorted(out, key=lambda r: r["start"], reverse=True)

    @app.get("/api/months")
    def months(year: str = "") -> list:
        s = snap()
        trips: dict[int, list] = {}
        for h in s.highlights.values():
            if h.kind == HIGHLIGHT_DAY_GROUP and h.assets and h.parent is not None:
                trips.setdefault(h.parent, []).append(
                    {"id": h.pk, "title": h.title, "trip": h.type == 1,
                     "start": int(h.start), **card(h.assets, s, h.key_asset)}
                )
        out = []
        for h in s.highlights.values():
            if h.kind != HIGHLIGHT_MONTH or not h.assets:
                continue
            parent = s.highlights.get(h.parent)
            if year and (parent is None or parent.title != year):
                continue
            out.append({
                "id": h.pk, "title": h.title, "start": int(h.start),
                "trips": sorted(trips.get(h.pk, []), key=lambda t: t["start"], reverse=True),
                **card(h.assets, s, h.key_asset),
            })
        return sorted(out, key=lambda r: r["start"], reverse=True)

    @app.get("/api/imports")
    def imports() -> list:
        s = snap()
        return [
            {"id": x.pk, "date": int(x.date), "source": x.source, **card(x.assets, s)}
            for x in s.imports
        ]

    @app.get("/api/places")
    def places() -> list:
        s = snap()
        groups: dict[str, list[int]] = {}
        for pk in s.timeline:
            a = s.assets[pk]
            if a.city:
                groups.setdefault(_place_key(a), []).append(pk)
        out = []
        for key, pks in groups.items():
            city, _, country = key.partition("|")
            geo = [s.assets[pk] for pk in pks if s.assets[pk].latitude is not None]
            out.append({
                "id": key, "city": city, "country": country, "key": pks[len(pks) // 2],
                "count": len(pks),
                "lat": sum(a.latitude for a in geo) / len(geo) if geo else None,
                "lon": sum(a.longitude for a in geo) / len(geo) if geo else None,
            })
        return sorted(out, key=lambda r: (-r["count"], r["city"]))

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
            "selfie": a.selfie,
            "portrait": a.portrait,
            "deleted": a.deleted,
            "deletedAt": int(a.deleted_at) if a.deleted else None,
            "lat": a.latitude,
            "lon": a.longitude,
            "city": a.city,
            "country": a.country,
            "address": a.address,
            "place": _place_key(a) if a.city else None,
            "importedBy": a.imported_by,
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

    @app.get("/manifest.webmanifest")
    def manifest() -> JSONResponse:
        """Makes the viewer installable as an app (Chrome/Edge: "Install app")."""
        name = settings.title or (
            library.path.stem if library.path.suffix == ".photoslibrary" else "Photos"
        )
        icons = [
            {"src": f"static/icons/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"}
            for n in (192, 512)
        ] + [
            {"src": f"static/icons/maskable-{n}.png", "sizes": f"{n}x{n}",
             "type": "image/png", "purpose": "maskable"}
            for n in (192, 512)
        ]
        return JSONResponse(
            {
                "name": name,
                "short_name": name[:24],
                "description": "Photos library viewer (read-only)",
                "id": "./",
                "start_url": "./",
                "scope": "./",
                "display": "standalone",
                "background_color": "#141417",
                "theme_color": "#1d1d22",
                "icons": icons,
            },
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

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
