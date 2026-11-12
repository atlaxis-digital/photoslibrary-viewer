import plistlib

from photoslibrary_viewer.places import parse_reverse_geo
from photoslibrary_viewer.search import normalize


def _archive() -> bytes:
    UID = plistlib.UID
    objects = [
        "$null",
        {"postalAddress": UID(2), "addressString": UID(5), "mapItem": UID(0)},
        {"_city": UID(3), "_country": UID(4)},
        "Bad Mitterndorf",
        "Österreich",
        "Tauplitzalm 69, 8982 Bad Mitterndorf, Österreich",
    ]
    return plistlib.dumps(
        {"$archiver": "NSKeyedArchiver", "$top": {"root": UID(1)}, "$objects": objects,
         "$version": 100000},
        fmt=plistlib.FMT_BINARY,
    )


def test_reverse_geo():
    p = parse_reverse_geo(_archive())
    assert (p.city, p.country) == ("Bad Mitterndorf", "Österreich")
    assert p.address.startswith("Tauplitzalm")


def test_reverse_geo_garbage():
    assert parse_reverse_geo(b"not a plist").city == ""


def test_normalize():
    assert normalize("Mailänder STRAẞE") == "mailander strasse"
