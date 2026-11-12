"""Decode Photos' reverse-geocoding data (place names per photo).

``ZADDITIONALASSETATTRIBUTES.ZREVERSELOCATIONDATA`` holds an NSKeyedArchiver
binary plist of a ``PLRevGeoLocationInfo`` object. We only need a few strings
from it: the postal address (city, country, full address) and, as a fallback,
the ranked list of place names with their place type.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass

# placeType values seen in PLRevGeoMapItemAdditionalPlaceInfo
PLACE_COUNTRY = 1
PLACE_CITY = 4
PLACE_DISTRICT = 3


@dataclass(slots=True, frozen=True)
class Place:
    city: str = ""
    country: str = ""
    address: str = ""


EMPTY = Place()


def parse_reverse_geo(blob: bytes) -> Place:
    try:
        archive = plistlib.loads(blob)
        objects = archive["$objects"]
        root = objects[archive["$top"]["root"].data]
    except Exception:
        return EMPTY

    def deref(value):
        if isinstance(value, plistlib.UID):
            value = objects[value.data]
        return None if value == "$null" else value

    def text(value) -> str:
        value = deref(value)
        return value.strip() if isinstance(value, str) else ""

    city = country = address = ""
    postal = deref(root.get("postalAddress")) if isinstance(root, dict) else None
    if isinstance(postal, dict):
        city = text(postal.get("_city"))
        country = text(postal.get("_country"))
    if isinstance(root, dict):
        address = text(root.get("addressString"))
        if not city or not country:
            item = deref(root.get("mapItem"))
            infos = deref(item.get("sortedPlaceInfos")) if isinstance(item, dict) else None
            for ref in (infos or {}).get("NS.objects", []) if isinstance(infos, dict) else []:
                info = deref(ref)
                if not isinstance(info, dict):
                    continue
                kind = deref(info.get("placeType"))
                name = text(info.get("name"))
                if not city and kind in (PLACE_CITY, PLACE_DISTRICT) and name:
                    city = name
                elif not country and kind == PLACE_COUNTRY and name:
                    country = name
    return Place(city=city, country=country, address=address)
