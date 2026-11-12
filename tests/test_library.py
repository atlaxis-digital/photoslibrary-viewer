"""Loader tests against a minimal synthetic Photos database.

Entity numbers are deliberately chosen so that one is a prefix of another
(3 vs 30), which is how real libraries look and what broke naive matching.
"""

import sqlite3
from pathlib import Path

from photoslibrary_viewer.library import CORE_DATA_EPOCH, Library

SCHEMA = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME VARCHAR);
INSERT INTO Z_PRIMARYKEY VALUES (1,'AdditionalAssetAttributes'),(3,'Asset'),(29,'GenericAlbum'),
  (30,'Album'),(47,'Keyword'),(20,'DetectedFace'),(54,'Person');
CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT, ZDATECREATED REAL, ZKIND INT, ZKINDSUBTYPE INT,
  ZWIDTH INT, ZHEIGHT INT, ZDURATION REAL, ZFAVORITE INT, ZHIDDEN INT, ZADJUSTMENTSSTATE INT,
  ZDIRECTORY TEXT, ZFILENAME TEXT, ZLATITUDE REAL, ZLONGITUDE REAL, ZUNIFORMTYPEIDENTIFIER TEXT,
  ZTRASHEDSTATE INT, ZVISIBILITYSTATE INT);
CREATE TABLE ZADDITIONALASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, ZASSET INT, ZORIGINALFILENAME TEXT,
  ZTITLE TEXT, ZTIMEZONEOFFSET INT);
CREATE TABLE ZKEYWORD (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT);
CREATE TABLE Z_1KEYWORDS (Z_1ASSETATTRIBUTES INT, Z_47KEYWORDS INT);
CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT, ZTITLE TEXT, ZKIND INT, ZPARENTFOLDER INT,
  ZCUSTOMSORTKEY INT, ZCUSTOMSORTASCENDING INT, ZCUSTOMKEYASSET INT, Z_FOK_PARENTFOLDER INT, ZTRASHEDSTATE INT);
CREATE TABLE Z_29KEYASSETS (Z_29ALBUMSBEINGKEYASSETS INT, Z_3KEYASSETS INT, Z_FOK_3KEYASSETS INT);
CREATE TABLE Z_30ASSETS (Z_30ALBUMS INT, Z_3ASSETS INT, Z_FOK_3ASSETS INT);
CREATE TABLE ZPERSON (Z_PK INTEGER PRIMARY KEY, ZPERSONUUID TEXT, ZFULLNAME TEXT, ZDISPLAYNAME TEXT,
  ZKEYFACE INT, ZMERGETARGETPERSON INT);
CREATE TABLE ZDETECTEDFACE (Z_PK INTEGER PRIMARY KEY, ZASSETFORFACE INT, ZPERSONFORFACE INT, ZHIDDEN INT,
  ZASSETVISIBLE INT, ZCENTERX REAL, ZCENTERY REAL, ZSIZE REAL);
"""


def make_library(tmp_path: Path) -> Path:
    lib = tmp_path / "Test.photoslibrary"
    (lib / "database").mkdir(parents=True)
    con = sqlite3.connect(lib / "database" / "Photos.sqlite")
    con.executescript(SCHEMA)
    t = 700_000_000  # Core Data seconds
    assets = [
        # pk, uuid, date, kind, subtype, fav, hidden, adjusted, trashed, visibility
        (1, "A1", t + 100, 0, 0, 1, 0, 0, 0, 0),
        (2, "B2", t + 300, 1, 0, 0, 0, 1, 0, 0),
        (3, "C3", t + 200, 0, 2, 0, 0, 0, 0, 0),
        (4, "D4", t + 400, 0, 0, 0, 1, 0, 0, 0),  # hidden
        (5, "E5", t + 500, 0, 0, 0, 0, 0, 1, 0),  # trashed
        (6, "F6", t + 600, 0, 0, 0, 0, 0, 0, 2),  # burst, not picked
    ]
    for pk, uuid, date, kind, sub, fav, hid, adj, tr, vis in assets:
        con.execute(
            "INSERT INTO ZASSET VALUES (?,?,?,?,?,100,100,0,?,?,?,'X',?,-180,-180,'public.jpeg',?,?)",
            (pk, uuid, date, kind, sub, fav, hid, adj, f"{uuid}.jpeg", tr, vis),
        )
        con.execute("INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (?,?,?,?,3600)",
                    (pk, pk, f"IMG_{pk}.JPG", "", ))
    con.execute("INSERT INTO ZKEYWORD VALUES (1, 'beach')")
    con.execute("INSERT INTO Z_1KEYWORDS VALUES (1, 1)")
    con.executemany("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?,?,?,?,?,0)", [
        (10, "root", None, 3999, None, 0, 1, None, 0),
        (11, "f", "Trips", 4000, 10, 0, 1, None, 1),
        (12, "a", "Beach", 2, 11, 0, 1, None, 1),
    ])
    # manual order: 3 before 1
    con.executemany("INSERT INTO Z_30ASSETS VALUES (12, ?, ?)", [(3, 1), (1, 2)])
    con.execute("INSERT INTO Z_29KEYASSETS VALUES (12, 2, 1)")  # must not be mistaken for membership
    con.execute("INSERT INTO ZPERSON VALUES (20, 'p', 'Alex', NULL, 30, NULL)")
    con.execute("INSERT INTO ZPERSON VALUES (21, 'q', 'Merged', NULL, NULL, 20)")
    con.execute("INSERT INTO ZDETECTEDFACE VALUES (30, 1, 20, 0, 1, .5, .5, .1)")
    con.execute("INSERT INTO ZDETECTEDFACE VALUES (31, 3, 20, 0, 1, .5, .5, .1)")
    con.commit()
    con.close()
    return lib


def test_load(tmp_path):
    lib = Library(make_library(tmp_path), tmp_path / "cache")
    lib.refresh(force=True)
    s = lib.snap
    assert s.timeline == [2, 3, 1]  # newest first; hidden, trashed, burst excluded
    a1 = s.assets[1]
    assert a1.favorite and a1.date == 700_000_100 + CORE_DATA_EPOCH and a1.tz_offset == 3600
    assert a1.original_filename == "IMG_1.JPG" and a1.keywords == ["beach"]
    assert s.assets[2].is_video and s.assets[2].edited
    assert s.assets[3].is_live
    assert s.root_folder == 10
    assert s.albums[11].is_folder and s.albums[12].parent == 11
    assert s.albums[12].assets == [3, 1]  # manual order kept, key-asset table ignored
    assert list(s.people) == [20] and s.people[20].assets == [3, 1]
    assert s.asset_people[1] == [20] and s.asset_albums[3] == [12]


def test_hidden_opt_in(tmp_path):
    lib = Library(make_library(tmp_path), tmp_path / "cache", show_hidden=True)
    lib.refresh(force=True)
    assert 4 in lib.snap.assets and lib.snap.assets[4].hidden


def test_source_untouched(tmp_path):
    path = make_library(tmp_path)
    before = sorted(p.name for p in (path / "database").iterdir())
    Library(path, tmp_path / "cache").refresh(force=True)
    assert sorted(p.name for p in (path / "database").iterdir()) == before
