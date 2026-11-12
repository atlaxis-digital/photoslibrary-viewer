"""Search: our own text plus the search index Photos maintains itself.

Photos keeps a search index in ``database/search/psi.sqlite``: "groups" are
searchable strings (things it recognised in the photos, places, people,
albums, text found in images, camera models, dates, …) linked to assets.
Asset UUIDs are stored as two signed 64-bit integers.

Every query term must match (AND). A term matches an asset if it starts a word in
the asset's own text (file name, title, caption, keywords, albums, people,
place) or in one of the asset's search-index groups.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import struct
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from .library import Snapshot, copy_sqlite

log = logging.getLogger(__name__)

# Our own name groups (negative so they never clash with Photos' categories)
OWN_PLACE, OWN_ALBUM, OWN_PERSON, OWN_KEYWORD = -1, -2, -3, -4

# Rough meaning of psi.sqlite group categories, for the result chips.
CATEGORY_LABELS = {
    OWN_PLACE: "place",
    OWN_ALBUM: "album",
    OWN_PERSON: "person",
    OWN_KEYWORD: "keyword",
    **{c: "place" for c in range(1, 15)},
    1300: "person",
    1400: "album",
    1500: "scene",
    1501: "scene",
    1203: "text",
    2100: "file",
    2300: "camera",
    **{c: "date" for c in range(1100, 1110)},
    **{c: "type" for c in range(1900, 1920)},
}


def normalize(text: str) -> str:
    """Lower case, accents removed: 'Mailänder' -> 'mailander'."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


@dataclass(slots=True)
class Group:
    text: str
    norm: str
    words: tuple[str, ...]
    category: int
    assets: list[int]


class SearchIndex:
    def __init__(self, library_path: Path, cache_dir: Path) -> None:
        self.library_path = library_path
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None
        self._text: list[tuple[int, str]] = []
        self._groups: list[Group] = []

    # ------------------------------------------------------------- building

    def rebuild(self, s: Snapshot) -> None:
        text = []
        for pk in s.timeline:
            a = s.assets[pk]
            parts = [a.original_filename, a.title, a.description, a.city, a.country,
                     a.address, *a.keywords]
            parts += [s.albums[x].title for x in s.asset_albums.get(pk, []) if x in s.albums]
            parts += [s.people[x].name for x in s.asset_people.get(pk, []) if x in s.people]
            text.append((pk, normalize("\n".join(p for p in parts if p))))
        groups = self._own_groups(s) + self._load_psi(s)
        with self._lock:
            self._text, self._groups, self._snap = text, groups, s
        log.info("search index: %d assets, %d Photos search groups", len(text), len(groups))

    def _own_groups(self, s: Snapshot) -> list[Group]:
        """Places, albums, people and keywords from the library itself, so
        they show up as result chips just like Photos' own index entries."""
        named: dict[tuple[int, str], list[int]] = {}
        for pk in s.timeline:
            a = s.assets[pk]
            for cat, name in ((OWN_PLACE, a.city), (OWN_PLACE, a.country)):
                if name:
                    named.setdefault((cat, name), []).append(pk)
            for kw in a.keywords:
                named.setdefault((OWN_KEYWORD, kw), []).append(pk)
        for album in s.albums.values():
            if album.title and album.assets:
                named.setdefault((OWN_ALBUM, album.title), []).extend(album.assets)
        for person in s.people.values():
            named.setdefault((OWN_PERSON, person.name), []).extend(person.assets)
        out = []
        for (cat, name), pks in named.items():
            norm = normalize(name)
            out.append(Group(name, norm, tuple(norm.split()), cat, pks))
        return out

    def _load_psi(self, s: Snapshot) -> list[Group]:
        src = self.library_path / "database" / "search"
        if not (src / "psi.sqlite").is_file():
            return []
        try:
            db = copy_sqlite(src, "psi.sqlite", self.cache_dir / "psi")
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except (OSError, sqlite3.Error) as e:
            log.warning("Photos search index not usable: %s", e)
            return []
        try:
            rowid_to_pk: dict[int, int] = {}
            for rowid, u0, u1 in con.execute("SELECT rowid, uuid_0, uuid_1 FROM assets"):
                u = str(uuid.UUID(bytes=struct.pack("<qq", u0, u1))).upper()
                pk = s.by_uuid.get(u)
                if pk is not None and s.visible(pk):
                    rowid_to_pk[rowid] = pk
            members: dict[int, list[int]] = {}
            for gid, aid in con.execute("SELECT groupid, assetid FROM ga"):
                pk = rowid_to_pk.get(aid)
                if pk is not None:
                    members.setdefault(gid, []).append(pk)
            groups = []
            for gid, category, content, norm in con.execute(
                "SELECT rowid, category, content_string, normalized_string FROM groups"
            ):
                assets = members.get(gid)
                if not assets or not content:
                    continue
                content = content.rstrip("\x00").strip()
                norm = normalize((norm or content).rstrip("\x00").strip())
                if not norm:
                    continue
                groups.append(Group(content, norm, tuple(norm.split()), category, assets))
            return groups
        except sqlite3.Error as e:
            log.warning("Photos search index not readable: %s", e)
            return []
        finally:
            con.close()

    # -------------------------------------------------------------- queries

    def _ensure(self, s: Snapshot) -> None:
        if self._snap is not s:
            self.rebuild(s)

    def query(self, s: Snapshot, q: str) -> tuple[list[int], list[dict]]:
        """Matching asset pks (newest first) and the index entries that matched."""
        self._ensure(s)
        terms = [t for t in normalize(q).split() if t]
        if not terms:
            return [], []
        result: set[int] | None = None
        hits: dict[int, Group] = {}
        for term in terms:
            # word prefix, like Photos: "rom" finds "Rom", not "Strom"
            pat = re.compile(r"(?:^|\W)" + re.escape(term))
            found = {pk for pk, text in self._text if term in text and pat.search(text)}
            for i, g in enumerate(self._groups):
                if any(w.startswith(term) for w in g.words):
                    found.update(g.assets)
                    hits[i] = g
            result = found if result is None else result & found
            if not result:
                break
        result = result or set()
        order = [pk for pk in s.timeline if pk in result]
        # Chips: whole-query matches first, then by number of photos.
        full = normalize(q).strip()
        chips = sorted(
            hits.values(),
            key=lambda g: (not g.norm.startswith(full), -len(set(g.assets) & result)),
        )
        seen, out = set(), []
        for g in chips:
            n = len(set(g.assets) & result)
            if not n or g.norm in seen or g.category == 2100:
                continue
            seen.add(g.norm)
            out.append({"text": g.text, "kind": CATEGORY_LABELS.get(g.category, ""), "count": n})
            if len(out) >= 8:
                break
        return order, out
