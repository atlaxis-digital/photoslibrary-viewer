"""Read-only access to a macOS Photos library (``*.photoslibrary``).

The library database (``database/Photos.sqlite``) is a Core Data store whose
table and column names shift between macOS releases. Entity numbers (the
``Z_<n>`` prefixes of join tables) are therefore resolved at runtime from
``Z_PRIMARYKEY`` instead of being hard-coded, and optional columns are looked
up before use.

The source library is never written to: the database is copied into the cache
directory and only that copy is opened.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .places import parse_reverse_geo

log = logging.getLogger(__name__)

# Core Data timestamps count seconds from 2001-01-01 UTC.
CORE_DATA_EPOCH = 978307200

KIND_PHOTO = 0
KIND_VIDEO = 1

# ZKINDSUBTYPE values
SUB_PANORAMA = 1
SUB_LIVE = 2
SUB_SCREENSHOT = 10
SUB_SLOMO = 101
SUB_TIMELAPSE = 102
SUB_SCREEN_RECORDING = 103

ALBUM_KIND_USER = 2
ALBUM_KIND_IMPORT = 1506
ALBUM_KIND_ROOT_FOLDER = 3999
ALBUM_KIND_FOLDER = 4000

# ZPHOTOSHIGHLIGHT.ZKIND
HIGHLIGHT_DAY = 0
HIGHLIGHT_MONTH = 1
HIGHLIGHT_YEAR = 2
HIGHLIGHT_DAY_GROUP = 3  # trips and weekends spanning several days

# Bit flags packed into the compact asset list sent to the browser.
FLAG_VIDEO = 1
FLAG_FAVORITE = 2
FLAG_LIVE = 4
FLAG_EDITED = 8
FLAG_HIDDEN = 16
FLAG_DELETED = 32

SEP = "\uf8ff"  # separator Photos puts into highlight titles

DB_FILES = ("Photos.sqlite", "Photos.sqlite-wal", "Photos.sqlite-shm")


def _date(value: float | None) -> float:
    return (value or 0) + CORE_DATA_EPOCH if value else 0.0


@dataclass(slots=True)
class Asset:
    pk: int
    uuid: str
    date: float  # unix seconds (UTC)
    tz_offset: int  # seconds east of UTC at capture time, 0 if unknown
    kind: int
    subtype: int
    width: int
    height: int
    duration: float
    favorite: bool
    hidden: bool
    edited: bool
    directory: str
    filename: str
    original_filename: str
    title: str
    description: str
    latitude: float | None
    longitude: float | None
    uti: str
    selfie: bool = False
    portrait: bool = False
    burst: str | None = None
    deleted: bool = False
    deleted_at: float = 0.0
    import_session: int | None = None
    imported_by: str = ""
    day_highlight: int | None = None
    curated: bool = False  # part of Photos' own selection for the Days view
    city: str = ""
    country: str = ""
    address: str = ""
    keywords: list[str] = field(default_factory=list)

    @property
    def is_video(self) -> bool:
        return self.kind == KIND_VIDEO

    @property
    def is_live(self) -> bool:
        return self.kind == KIND_PHOTO and self.subtype == SUB_LIVE

    @property
    def local_date(self) -> float:
        """Capture time as 'wall clock' seconds (format as UTC)."""
        return self.date + self.tz_offset

    @property
    def flags(self) -> int:
        f = 0
        if self.is_video:
            f |= FLAG_VIDEO
        if self.favorite:
            f |= FLAG_FAVORITE
        if self.is_live:
            f |= FLAG_LIVE
        if self.edited:
            f |= FLAG_EDITED
        if self.hidden:
            f |= FLAG_HIDDEN
        if self.deleted:
            f |= FLAG_DELETED
        return f


@dataclass(slots=True)
class Album:
    pk: int
    uuid: str
    title: str
    kind: int
    parent: int | None
    sort_key: int
    sort_ascending: bool
    key_asset: int | None
    assets: list[int] = field(default_factory=list)  # asset pks, album order

    @property
    def is_folder(self) -> bool:
        return self.kind == ALBUM_KIND_FOLDER


@dataclass(slots=True)
class Person:
    pk: int
    uuid: str
    name: str
    key_face: int | None
    assets: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Face:
    pk: int
    asset: int
    person: int | None
    center_x: float
    center_y: float
    size: float


@dataclass(slots=True)
class Memory:
    pk: int
    title: str
    subtitle: str
    date: float
    favorite: bool
    key_asset: int | None
    assets: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Highlight:
    pk: int
    kind: int
    type: int
    title: str
    start: float
    end: float
    parent: int | None
    day_group: int | None
    key_asset: int | None = None
    assets: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ImportSession:
    pk: int
    date: float
    assets: list[int] = field(default_factory=list)
    source: str = ""


class Snapshot:
    """Everything loaded from one copy of the database."""

    def __init__(self) -> None:
        self.assets: dict[int, Asset] = {}  # includes deleted items
        self.timeline: list[int] = []  # visible asset pks, newest first
        self.deleted: list[int] = []  # recently deleted, most recent first
        self.albums: dict[int, Album] = {}
        self.root_folder: int | None = None
        self.people: dict[int, Person] = {}
        self.faces: dict[int, Face] = {}
        self.memories: list[Memory] = []
        self.highlights: dict[int, Highlight] = {}
        self.imports: list[ImportSession] = []
        self.asset_albums: dict[int, list[int]] = {}
        self.asset_people: dict[int, list[int]] = {}
        self.by_uuid: dict[str, int] = {}
        self.loaded_at = time.time()
        self.source_mtime = 0.0

    def visible(self, pk: int) -> bool:
        a = self.assets.get(pk)
        return a is not None and not a.deleted


class Library:
    def __init__(
        self,
        path: str | os.PathLike,
        cache_dir: str | os.PathLike,
        show_hidden: bool = False,
        show_deleted: bool = False,
    ) -> None:
        self.path = Path(path)
        self.cache_dir = Path(cache_dir)
        self.show_hidden = show_hidden
        self.show_deleted = show_deleted
        self._lock = threading.Lock()
        self.snapshot: Snapshot | None = None
        self.listeners: list = []  # called with the new snapshot after a reload
        if not (self.path / "database" / "Photos.sqlite").is_file():
            raise FileNotFoundError(
                f"{self.path} does not look like a Photos library "
                "(database/Photos.sqlite is missing)"
            )

    # ------------------------------------------------------------------ load

    def _source_mtime(self) -> float:
        db = self.path / "database"
        return max(
            (db / name).stat().st_mtime for name in DB_FILES if (db / name).exists()
        )

    def refresh(self, force: bool = False) -> bool:
        """Reload if the source database changed. Returns True if reloaded."""
        with self._lock:
            mtime = self._source_mtime()
            if not force and self.snapshot and self.snapshot.source_mtime == mtime:
                return False
            t0 = time.time()
            db_path = copy_sqlite(self.path / "database", "Photos.sqlite", self.cache_dir / "db")
            snap = self._load(db_path)
            snap.source_mtime = mtime
            self.snapshot = snap
            log.info(
                "loaded %d assets, %d albums, %d people, %d memories in %.1fs",
                len(snap.timeline), len(snap.albums), len(snap.people),
                len(snap.memories), time.time() - t0,
            )
        for listener in self.listeners:
            try:
                listener(snap)
            except Exception:
                log.exception("listener failed")
        return True

    def _load(self, db_path: Path) -> Snapshot:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return _Loader(con, self.show_hidden, self.show_deleted).load()
        finally:
            con.close()

    @property
    def snap(self) -> Snapshot:
        if self.snapshot is None:
            self.refresh()
        assert self.snapshot is not None
        return self.snapshot


def copy_sqlite(src_dir: Path, name: str, target: Path) -> Path:
    """Copy an SQLite database (+WAL/SHM) into ``target`` and fold the WAL in,
    so the copy is self-contained and the source is never opened."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for suffix in ("", "-wal", "-shm"):
        src = src_dir / f"{name}{suffix}"
        if src.exists():
            shutil.copyfile(src, tmp / f"{name}{suffix}")
    con = sqlite3.connect(tmp / name)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")
    finally:
        con.close()
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return target / name


class _Loader:
    def __init__(self, con: sqlite3.Connection, show_hidden: bool, show_deleted: bool) -> None:
        self.con = con
        self.show_hidden = show_hidden
        self.show_deleted = show_deleted
        self.ent = {
            row["Z_NAME"]: row["Z_ENT"]
            for row in con.execute("SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY")
        }
        self.tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self._cols: dict[str, set[str]] = {}

    def cols(self, table: str) -> set[str]:
        if table not in self._cols:
            self._cols[table] = {
                r[1] for r in self.con.execute(f"PRAGMA table_info({table})")
            }
        return self._cols[table]

    def col(self, table: str, *candidates: str, default: str = "NULL") -> str:
        """First candidate column that exists, else a SQL literal default."""
        have = self.cols(table)
        for c in candidates:
            if c in have:
                return c
        return default

    def find_join(
        self, left: str, right: str, suffix: str = ""
    ) -> tuple[str, str, str, str | None] | None:
        """Locate the Core Data join table between two entities.

        Returns (table, left_column, right_column, order_column). Join tables
        are named Z_<ent><RELATION> with columns Z_<leftEnt><x> and
        Z_<rightEnt><y>; the relation names vary, so match on the prefixes.
        ``suffix`` narrows the choice when several relations exist.
        """
        le, re_ = self.ent.get(left), self.ent.get(right)
        if le is None or re_ is None:
            return None
        lpat = re.compile(rf"Z_{le}[A-Z]")
        rpat = re.compile(rf"Z_{re_}[A-Z]")
        # Prefer tables owned by the left entity (Z_<le>...), e.g. Z_30ASSETS.
        ordered = sorted(self.tables, key=lambda t: (not lpat.match(t), t))
        for table in ordered:
            if not re.fullmatch(r"Z_\d+[A-Z0-9_]+", table):
                continue
            if suffix and not table.endswith(suffix):
                continue
            cols = self.cols(table)
            lcol = [c for c in cols if lpat.match(c)]
            rcol = [c for c in cols if rpat.match(c)]
            if len(lcol) == 1 and len(rcol) == 1 and lcol[0] != rcol[0]:
                fok = [c for c in cols if c.startswith("Z_FOK")]
                return table, lcol[0], rcol[0], (fok[0] if fok else None)
        return None

    # -------------------------------------------------------------------

    def load(self) -> Snapshot:
        s = Snapshot()
        steps = (
            self._load_assets, self._load_keywords, self._load_albums, self._load_people,
            self._load_memories, self._load_highlights, self._load_imports,
        )
        for step in steps:
            try:
                step(s)
            except sqlite3.Error:
                # A schema we don't know must not take the whole viewer down.
                log.exception("could not load %s", step.__name__)
        return s

    def _load_assets(self, s: Snapshot) -> None:
        A = "ZASSET"
        has_aaa = "ZADDITIONALASSETATTRIBUTES" in self.tables
        has_desc = "ZASSETDESCRIPTION" in self.tables

        def ac(*names: str, default: str = "NULL") -> str:
            c = self.col(A, *names, default="")
            return f"a.{c}" if c else default

        def aa(*names: str, default: str = "NULL") -> str:
            if not has_aaa:
                return default
            c = self.col("ZADDITIONALASSETATTRIBUTES", *names, default="")
            return f"aa.{c}" if c else default

        sql = f"""
            SELECT a.Z_PK, a.ZUUID, a.ZDATECREATED, a.ZKIND,
                   {ac("ZKINDSUBTYPE", default="0")} AS subtype,
                   a.ZWIDTH, a.ZHEIGHT, a.ZDURATION, a.ZFAVORITE, a.ZHIDDEN,
                   {ac("ZADJUSTMENTSSTATE", "ZHASADJUSTMENTS", default="0")} AS adjusted,
                   a.ZDIRECTORY, a.ZFILENAME, a.ZLATITUDE, a.ZLONGITUDE,
                   {ac("ZUNIFORMTYPEIDENTIFIER", default="''")} AS uti,
                   a.ZTRASHEDSTATE AS trashed,
                   {ac("ZTRASHEDDATE")} AS trashed_date,
                   {ac("ZDEPTHTYPE", default="0")} AS depth,
                   {ac("ZAVALANCHEUUID")} AS burst,
                   {ac("ZIMPORTSESSION")} AS import_session,
                   {ac("ZHIGHLIGHTBEINGASSETS")} AS day_highlight,
                   {ac("ZHIGHLIGHTBEINGSUMMARYASSETS")} AS summary,
                   {ac("ZISDETECTEDSCREENSHOT", default="0")} AS screenshot,
                   {aa("ZORIGINALFILENAME")} AS original_filename,
                   {aa("ZTITLE")} AS title,
                   {aa("ZTIMEZONEOFFSET", default="0")} AS tz,
                   {aa("ZCAMERACAPTUREDEVICE", default="0")} AS capture_device,
                   {aa("ZIMPORTEDBYDISPLAYNAME", default="''")} AS imported_by,
                   {aa("ZREVERSELOCATIONDATA")} AS revgeo,
                   {"d.ZLONGDESCRIPTION" if has_aaa and has_desc else "NULL"} AS descr
            FROM ZASSET a
            {"LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK" if has_aaa else ""}
            {"LEFT JOIN ZASSETDESCRIPTION d ON d.ZASSETATTRIBUTES = aa.Z_PK" if has_aaa and has_desc else ""}
            WHERE {ac("ZVISIBILITYSTATE", default="0")} = 0
              AND a.ZUUID IS NOT NULL
        """
        visible: list[Asset] = []
        deleted: list[Asset] = []
        for r in self.con.execute(sql):
            trashed = bool(r["trashed"])
            if trashed and not self.show_deleted:
                continue
            hidden = bool(r["ZHIDDEN"])
            if hidden and not self.show_hidden:
                continue
            lat, lon = r["ZLATITUDE"], r["ZLONGITUDE"]
            if lat is None or lon is None or lat < -90 or lat > 90 or (lat == 0 and lon == 0):
                lat = lon = None
            subtype = r["subtype"] or 0
            if r["screenshot"] and subtype == 0 and (r["ZKIND"] or 0) == KIND_PHOTO:
                subtype = SUB_SCREENSHOT
            a = Asset(
                pk=r["Z_PK"],
                uuid=r["ZUUID"],
                date=_date(r["ZDATECREATED"]),
                tz_offset=int(r["tz"] or 0),
                kind=r["ZKIND"] or 0,
                subtype=subtype,
                width=r["ZWIDTH"] or 0,
                height=r["ZHEIGHT"] or 0,
                duration=float(r["ZDURATION"] or 0),
                favorite=bool(r["ZFAVORITE"]),
                hidden=hidden,
                edited=bool(r["adjusted"]),
                directory=r["ZDIRECTORY"] or "",
                filename=r["ZFILENAME"] or "",
                original_filename=r["original_filename"] or r["ZFILENAME"] or "",
                title=r["title"] or "",
                description=r["descr"] or "",
                latitude=lat,
                longitude=lon,
                uti=r["uti"] or "",
                selfie=r["capture_device"] == 1,
                portrait=bool(r["depth"]),
                burst=r["burst"],
                deleted=trashed,
                deleted_at=_date(r["trashed_date"]),
                import_session=r["import_session"],
                imported_by=r["imported_by"] or "",
                day_highlight=r["day_highlight"],
                curated=r["summary"] is not None,
            )
            if r["revgeo"]:
                place = parse_reverse_geo(r["revgeo"])
                a.city, a.country, a.address = place.city, place.country, place.address
            s.assets[a.pk] = a
            s.by_uuid[a.uuid] = a.pk
            (deleted if trashed else visible).append(a)
        visible.sort(key=lambda a: a.date, reverse=True)
        deleted.sort(key=lambda a: a.deleted_at, reverse=True)
        s.timeline = [a.pk for a in visible]
        s.deleted = [a.pk for a in deleted]

    def _load_keywords(self, s: Snapshot) -> None:
        if "ZKEYWORD" not in self.tables or "ZADDITIONALASSETATTRIBUTES" not in self.tables:
            return
        j = self.find_join("AdditionalAssetAttributes", "Keyword")
        if not j:
            return
        table, lcol, rcol, _ = j
        sql = f"""
            SELECT aa.ZASSET AS asset, k.ZTITLE AS title
            FROM {table} jt
            JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.Z_PK = jt.{lcol}
            JOIN ZKEYWORD k ON k.Z_PK = jt.{rcol}
        """
        for r in self.con.execute(sql):
            a = s.assets.get(r["asset"])
            if a and r["title"]:
                a.keywords.append(r["title"])

    def _load_albums(self, s: Snapshot) -> None:
        key_asset = self.col("ZGENERICALBUM", "ZCUSTOMKEYASSET", "ZKEYASSET")
        sort_key = self.col("ZGENERICALBUM", "ZCUSTOMSORTKEY", default="0")
        sort_asc = self.col("ZGENERICALBUM", "ZCUSTOMSORTASCENDING", default="1")
        fok_parent = self.col("ZGENERICALBUM", "Z_FOK_PARENTFOLDER", default="0")
        sql = f"""
            SELECT Z_PK, ZUUID, ZTITLE, ZKIND, ZPARENTFOLDER,
                   {sort_key} AS sort_key, {sort_asc} AS sort_asc,
                   {key_asset} AS key_asset, {fok_parent} AS fok
            FROM ZGENERICALBUM
            WHERE ZTRASHEDSTATE = 0 AND ZKIND IN (?, ?, ?)
            ORDER BY fok, Z_PK
        """
        for r in self.con.execute(
            sql, (ALBUM_KIND_USER, ALBUM_KIND_FOLDER, ALBUM_KIND_ROOT_FOLDER)
        ):
            if r["ZKIND"] == ALBUM_KIND_ROOT_FOLDER:
                s.root_folder = r["Z_PK"]
                continue
            s.albums[r["Z_PK"]] = Album(
                pk=r["Z_PK"],
                uuid=r["ZUUID"] or "",
                title=r["ZTITLE"] or "",
                kind=r["ZKIND"],
                parent=r["ZPARENTFOLDER"],
                sort_key=r["sort_key"] or 0,
                sort_ascending=bool(r["sort_asc"]),
                key_asset=r["key_asset"],
            )
        j = self.find_join("Album", "Asset")
        if j:
            table, lcol, rcol, fok = j
            order = f"jt.{fok}" if fok else f"jt.{rcol}"
            sql = f"SELECT jt.{lcol} AS album, jt.{rcol} AS asset FROM {table} jt ORDER BY {order}"
            for r in self.con.execute(sql):
                album = s.albums.get(r["album"])
                if album is None or not s.visible(r["asset"]):
                    continue
                album.assets.append(r["asset"])
                s.asset_albums.setdefault(r["asset"], []).append(album.pk)
        for album in s.albums.values():
            # sort_key 0 = manual order (as stored); anything else: by date.
            if album.sort_key != 0:
                album.assets.sort(
                    key=lambda pk: s.assets[pk].date, reverse=not album.sort_ascending
                )
            if not s.visible(album.key_asset) or album.key_asset not in album.assets:
                album.key_asset = album.assets[0] if album.assets else None

    def _load_people(self, s: Snapshot) -> None:
        if "ZPERSON" not in self.tables or "ZDETECTEDFACE" not in self.tables:
            return
        f_asset = self.col("ZDETECTEDFACE", "ZASSETFORFACE", "ZASSET")
        f_person = self.col("ZDETECTEDFACE", "ZPERSONFORFACE", "ZPERSON")
        f_hidden = self.col("ZDETECTEDFACE", "ZHIDDEN", default="0")
        f_visible = self.col("ZDETECTEDFACE", "ZASSETVISIBLE", default="1")
        merge = self.col("ZPERSON", "ZMERGETARGETPERSON")
        uuid = self.col("ZPERSON", "ZPERSONUUID", default="''")
        for r in self.con.execute(
            f"""SELECT Z_PK, {uuid} AS uuid, ZFULLNAME, ZDISPLAYNAME, ZKEYFACE
                FROM ZPERSON WHERE {merge} IS NULL"""
        ):
            name = (r["ZFULLNAME"] or r["ZDISPLAYNAME"] or "").strip()
            if not name or name.startswith("_UNKNOWN_"):
                continue
            s.people[r["Z_PK"]] = Person(
                pk=r["Z_PK"], uuid=r["uuid"] or "", name=name, key_face=r["ZKEYFACE"]
            )
        first_face: dict[int, int] = {}
        for r in self.con.execute(
            f"""SELECT Z_PK, {f_asset} AS asset, {f_person} AS person,
                       ZCENTERX, ZCENTERY, ZSIZE
                FROM ZDETECTEDFACE
                WHERE {f_asset} IS NOT NULL AND {f_hidden} = 0 AND {f_visible} = 1"""
        ):
            if not s.visible(r["asset"]):
                continue
            face = Face(
                pk=r["Z_PK"],
                asset=r["asset"],
                person=r["person"],
                center_x=r["ZCENTERX"] or 0.0,
                center_y=r["ZCENTERY"] or 0.0,
                size=r["ZSIZE"] or 0.0,
            )
            s.faces[face.pk] = face
            person = s.people.get(face.person)
            if person is not None:
                person.assets.append(face.asset)
                first_face.setdefault(person.pk, face.pk)
        for person in list(s.people.values()):
            person.assets = sorted(
                set(person.assets), key=lambda pk: s.assets[pk].date, reverse=True
            )
            if not person.assets:
                del s.people[person.pk]
                continue
            if person.key_face not in s.faces:
                person.key_face = first_face.get(person.pk)
            for pk in person.assets:
                s.asset_people.setdefault(pk, []).append(person.pk)

    def _load_memories(self, s: Snapshot) -> None:
        if "ZMEMORY" not in self.tables:
            return
        j = self.find_join("Memory", "Asset", suffix="MEMORIESBEINGCURATEDASSETS") or self.find_join(
            "Memory", "Asset", suffix="MEMORIESBEINGREPRESENTATIVEASSETS"
        )
        if not j:
            return
        table, mcol, acol, _ = j
        members: dict[int, list[int]] = {}
        for r in self.con.execute(f"SELECT {mcol} AS m, {acol} AS a FROM {table}"):
            if s.visible(r["a"]):
                members.setdefault(r["m"], []).append(r["a"])
        rejected = self.col("ZMEMORY", "ZREJECTED", default="0")
        favorite = self.col("ZMEMORY", "ZFAVORITE", default="0")
        for r in self.con.execute(
            f"""SELECT Z_PK, ZTITLE, ZSUBTITLE, ZCREATIONDATE, ZKEYASSET,
                       {favorite} AS fav
                FROM ZMEMORY WHERE {rejected} = 0"""
        ):
            assets = sorted(set(members.get(r["Z_PK"], [])), key=lambda pk: s.assets[pk].date)
            if not assets:
                continue
            key = r["ZKEYASSET"] if r["ZKEYASSET"] in assets else assets[0]
            s.memories.append(Memory(
                pk=r["Z_PK"],
                title=" ".join((r["ZTITLE"] or "").split()),
                subtitle=" ".join((r["ZSUBTITLE"] or "").split()),
                date=_date(r["ZCREATIONDATE"]),
                favorite=bool(r["fav"]),
                key_asset=key,
                assets=assets,
            ))
        s.memories.sort(key=lambda m: m.date, reverse=True)

    def _load_highlights(self, s: Snapshot) -> None:
        T = "ZPHOTOSHIGHLIGHT"
        if T not in self.tables:
            return
        for r in self.con.execute(
            f"""SELECT Z_PK, ZKIND, {self.col(T, "ZTYPE", default="0")} AS type,
                       ZTITLE, ZSUBTITLE, ZSTARTDATE, ZENDDATE,
                       {self.col(T, "ZSTARTTIMEZONEOFFSET", default="0")} AS tz,
                       {self.col(T, "ZPARENTPHOTOSHIGHLIGHT")} AS parent,
                       {self.col(T, "ZPARENTDAYGROUPPHOTOSHIGHLIGHT")} AS day_group
                FROM {T}"""
        ):
            # Titles carry U+F8FF separators ("17.–25. Juni 2026<U+F8FF>Juni 2026").
            raw = r["ZTITLE"] or r["ZSUBTITLE"] or ""
            title = " ".join(raw.replace(SEP, " ").split())
            if r["ZKIND"] == HIGHLIGHT_DAY_GROUP and SEP in raw:
                title = raw.split(SEP)[0]
            tz = r["tz"] or 0
            s.highlights[r["Z_PK"]] = Highlight(
                pk=r["Z_PK"], kind=r["ZKIND"], type=r["type"] or 0, title=title.strip(),
                start=_date(r["ZSTARTDATE"]) + tz, end=_date(r["ZENDDATE"]) + tz,
                parent=r["parent"], day_group=r["day_group"],
            )
        # Key photos chosen by Photos for each level.
        for col in ("ZHIGHLIGHTBEINGKEYASSETPRIVATE", "ZDAYGROUPHIGHLIGHTBEINGKEYASSETPRIVATE",
                    "ZMONTHHIGHLIGHTBEINGKEYASSETPRIVATE", "ZYEARHIGHLIGHTBEINGKEYASSETPRIVATE"):
            if col not in self.cols("ZASSET"):
                continue
            for r in self.con.execute(f"SELECT Z_PK, {col} AS h FROM ZASSET WHERE {col} IS NOT NULL"):
                h = s.highlights.get(r["h"])
                if h and s.visible(r["Z_PK"]):
                    h.key_asset = r["Z_PK"]
        # Members: day -> its month and day group (trip).
        for pk in reversed(s.timeline):  # oldest first
            day = s.highlights.get(s.assets[pk].day_highlight)
            if day is None:
                continue
            day.assets.append(pk)
            for up in (day.parent, day.day_group):
                h = s.highlights.get(up)
                if h is not None:
                    h.assets.append(pk)
                    year = s.highlights.get(h.parent) if h.kind == HIGHLIGHT_MONTH else None
                    if year is not None and up == day.parent:
                        year.assets.append(pk)
        for h in s.highlights.values():
            if h.key_asset is None and h.assets:
                h.key_asset = h.assets[len(h.assets) // 2]

    def _load_imports(self, s: Snapshot) -> None:
        sessions: dict[int, ImportSession] = {}
        for pk in s.timeline:
            a = s.assets[pk]
            if a.import_session is None:
                continue
            sess = sessions.setdefault(a.import_session, ImportSession(pk=a.import_session, date=0.0))
            sess.assets.append(pk)
        dates = {}
        start = self.col("ZGENERICALBUM", "ZSTARTDATE", "ZCREATIONDATE")
        for r in self.con.execute(
            f"SELECT Z_PK, {start} AS d FROM ZGENERICALBUM WHERE ZKIND = ?", (ALBUM_KIND_IMPORT,)
        ):
            dates[r["Z_PK"]] = _date(r["d"])
        for sess in sessions.values():
            sess.assets.sort(key=lambda pk: s.assets[pk].date)
            sess.date = dates.get(sess.pk) or max(s.assets[pk].date for pk in sess.assets)
            sources = Counter(s.assets[pk].imported_by for pk in sess.assets if s.assets[pk].imported_by)
            sess.source = sources.most_common(1)[0][0] if sources else ""
        s.imports = sorted(sessions.values(), key=lambda x: x.date, reverse=True)


def top_places(assets: list[Asset], limit: int = 2) -> str:
    """'Tübingen, Stuttgart' – the most frequent cities (or countries)."""
    cities = Counter(a.city for a in assets if a.city)
    if cities:
        return ", ".join(c for c, _ in cities.most_common(limit))
    countries = Counter(a.country for a in assets if a.country)
    return ", ".join(c for c, _ in countries.most_common(limit))
