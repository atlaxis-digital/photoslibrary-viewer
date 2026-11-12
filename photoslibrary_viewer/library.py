"""Read-only access to a macOS Photos library (``*.photoslibrary``).

The library database (``database/Photos.sqlite``) is a Core Data store whose
table and column names shift between macOS releases. Entity numbers (the
``Z_<n>`` prefixes of join tables) are therefore resolved at runtime from
``Z_PRIMARYKEY`` instead of being hard-coded.

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
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Core Data timestamps count seconds from 2001-01-01 UTC.
CORE_DATA_EPOCH = 978307200

KIND_PHOTO = 0
KIND_VIDEO = 1

ALBUM_KIND_USER = 2
ALBUM_KIND_ROOT_FOLDER = 3999
ALBUM_KIND_FOLDER = 4000

# Bit flags packed into the compact asset list sent to the browser.
FLAG_VIDEO = 1
FLAG_FAVORITE = 2
FLAG_LIVE = 4
FLAG_EDITED = 8
FLAG_HIDDEN = 16

DB_FILES = ("Photos.sqlite", "Photos.sqlite-wal", "Photos.sqlite-shm")


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
    keywords: list[str] = field(default_factory=list)

    @property
    def is_video(self) -> bool:
        return self.kind == KIND_VIDEO

    @property
    def is_live(self) -> bool:
        # ZKINDSUBTYPE 2 marks a Live Photo (still + paired movie).
        return self.kind == KIND_PHOTO and self.subtype == 2

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


class Snapshot:
    """Everything loaded from one copy of the database."""

    def __init__(self) -> None:
        self.assets: dict[int, Asset] = {}
        self.timeline: list[int] = []  # asset pks, newest first
        self.albums: dict[int, Album] = {}
        self.root_folder: int | None = None
        self.people: dict[int, Person] = {}
        self.faces: dict[int, Face] = {}
        self.asset_albums: dict[int, list[int]] = {}
        self.asset_people: dict[int, list[int]] = {}
        self.by_uuid: dict[str, int] = {}
        self.loaded_at = time.time()
        self.source_mtime = 0.0


class Library:
    def __init__(
        self,
        path: str | os.PathLike,
        cache_dir: str | os.PathLike,
        show_hidden: bool = False,
    ) -> None:
        self.path = Path(path)
        self.cache_dir = Path(cache_dir)
        self.show_hidden = show_hidden
        self._lock = threading.Lock()
        self.snapshot: Snapshot | None = None
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
            db_path = self._copy_database()
            snap = self._load(db_path)
            snap.source_mtime = mtime
            self.snapshot = snap
            log.info(
                "loaded %d assets, %d albums, %d people in %.1fs",
                len(snap.assets), len(snap.albums), len(snap.people), time.time() - t0,
            )
            return True

    def _copy_database(self) -> Path:
        """Copy Photos.sqlite (+WAL) into the cache so the source stays untouched."""
        target = self.cache_dir / "db"
        tmp = self.cache_dir / "db.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for name in DB_FILES:
            src = self.path / "database" / name
            if src.exists():
                shutil.copyfile(src, tmp / name)
        # Fold the WAL into the main file so the copy is self-contained.
        con = sqlite3.connect(tmp / "Photos.sqlite")
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute("PRAGMA journal_mode=DELETE")
        finally:
            con.close()
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
        return target / "Photos.sqlite"

    def _load(self, db_path: Path) -> Snapshot:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return _Loader(con, self.show_hidden).load()
        finally:
            con.close()

    # --------------------------------------------------------------- helpers

    @property
    def snap(self) -> Snapshot:
        if self.snapshot is None:
            self.refresh()
        assert self.snapshot is not None
        return self.snapshot


class _Loader:
    def __init__(self, con: sqlite3.Connection, show_hidden: bool) -> None:
        self.con = con
        self.show_hidden = show_hidden
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

    def find_join(self, left: str, right: str) -> tuple[str, str, str, str | None] | None:
        """Locate the Core Data join table between two entities.

        Returns (table, left_column, right_column, order_column). Join tables
        are named Z_<leftEnt><RELATION> with columns Z_<leftEnt><x> and
        Z_<rightEnt><y>; the relation names vary, so match on the prefixes.
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
        self._load_assets(s)
        self._load_keywords(s)
        self._load_albums(s)
        self._load_people(s)
        return s

    def _load_assets(self, s: Snapshot) -> None:
        c = self.con
        has_aaa = "ZADDITIONALASSETATTRIBUTES" in self.tables
        has_desc = "ZASSETDESCRIPTION" in self.tables
        adjusted = self.col("ZASSET", "ZADJUSTMENTSSTATE", "ZHASADJUSTMENTS", default="0")
        subtype = self.col("ZASSET", "ZKINDSUBTYPE", default="0")
        visibility = self.col("ZASSET", "ZVISIBILITYSTATE", default="0")
        uti = self.col("ZASSET", "ZUNIFORMTYPEIDENTIFIER", default="''")
        sql = f"""
            SELECT a.Z_PK, a.ZUUID, a.ZDATECREATED, a.ZKIND, a.{subtype} AS subtype,
                   a.ZWIDTH, a.ZHEIGHT, a.ZDURATION, a.ZFAVORITE, a.ZHIDDEN,
                   a.{adjusted} AS adjusted, a.ZDIRECTORY, a.ZFILENAME,
                   a.ZLATITUDE, a.ZLONGITUDE, a.{uti} AS uti,
                   {"aa.ZORIGINALFILENAME" if has_aaa else "NULL"} AS original_filename,
                   {"aa.ZTITLE" if has_aaa else "NULL"} AS title,
                   {"aa.ZTIMEZONEOFFSET" if has_aaa else "0"} AS tz,
                   {"d.ZLONGDESCRIPTION" if has_aaa and has_desc else "NULL"} AS descr
            FROM ZASSET a
            {"LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK" if has_aaa else ""}
            {"LEFT JOIN ZASSETDESCRIPTION d ON d.ZASSETATTRIBUTES = aa.Z_PK" if has_aaa and has_desc else ""}
            WHERE a.ZTRASHEDSTATE = 0
              AND a.{visibility} = 0
              AND a.ZUUID IS NOT NULL
        """
        rows = []
        for r in c.execute(sql):
            hidden = bool(r["ZHIDDEN"])
            if hidden and not self.show_hidden:
                continue
            lat, lon = r["ZLATITUDE"], r["ZLONGITUDE"]
            if lat is None or lon is None or lat < -90 or lat > 90 or (lat == 0 and lon == 0):
                lat = lon = None
            date = (r["ZDATECREATED"] or 0) + CORE_DATA_EPOCH
            a = Asset(
                pk=r["Z_PK"],
                uuid=r["ZUUID"],
                date=date,
                tz_offset=int(r["tz"] or 0),
                kind=r["ZKIND"] or 0,
                subtype=r["subtype"] or 0,
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
            )
            s.assets[a.pk] = a
            s.by_uuid[a.uuid] = a.pk
            rows.append(a)
        rows.sort(key=lambda a: a.date, reverse=True)
        s.timeline = [a.pk for a in rows]

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
                if album is None or r["asset"] not in s.assets:
                    continue
                album.assets.append(r["asset"])
                s.asset_albums.setdefault(r["asset"], []).append(album.pk)
        for album in s.albums.values():
            # sort_key 0 = manual order (as stored); anything else: by date.
            if album.sort_key != 0:
                album.assets.sort(
                    key=lambda pk: s.assets[pk].date, reverse=not album.sort_ascending
                )
            if album.key_asset not in s.assets:
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
            if r["asset"] not in s.assets:
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
