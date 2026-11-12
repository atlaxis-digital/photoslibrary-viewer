# photoslibrary-viewer

Browse a macOS Photos library (`*.photoslibrary`) from **any web browser**, on
Windows, Linux, a phone or a tablet, without a Mac and without exporting
anything first.

The viewer reads the library the way Photos stores it: originals, the
previews Photos has already rendered, your edits, albums and folders, people,
favorites, keywords, captions and camera details. It never writes to the
library.

> Not affiliated with or endorsed by Apple Inc. "Photos" and "macOS" are
> trademarks of Apple Inc.

## Features

Most of the "smart" parts are already computed by Photos and stored in the
library; the viewer shows them as they are.

**Browsing**
- **All Photos** timeline grouped by month, with a year scrubber; smooth even
  with 50 000+ items (virtualized grid)
- **Days** (Photos' own curated selection, with place names per day),
  **Months** (with trips and weekends) and **Years**
- **Memories** with Photos' own titles and photo selection
- **People** with face thumbnails, **Places** on a map (clustered photo pins)
  and as a list of cities, **Favorites**, **Imports** (with their source app)
- **Albums and folders** in their original nesting and order
- **Media types**: Videos, Selfies, Live Photos, Portrait, Panoramas,
  Time-lapse, Slo-mo, Bursts, Screenshots, Screen Recordings, Edited
- **Recently Deleted** and **Hidden** (both opt-in)

**Viewing**
- **Zoom & pan**: mouse wheel, pinch, double-click for 100 %, drag to move
- **Slideshow** (fullscreen, videos play to the end; `S` or the ▶ button)
- **Fullscreen** for the whole app or a single photo/video (button or `F`)
- **Edited versions** are shown; the untouched original is one click away
- **Videos** stream with seeking; **Live Photos** play their motion clip
- **HEIC** photos are converted to JPEG on the fly for browsers that can't
  show HEIC (converted files are cached)
- **Info panel**: place name and address, date with capture time zone,
  camera, lens, exposure, albums, people, keywords, import source

**Finding**
- **Search** that combines the library's own data (file names, titles,
  captions, keywords, albums, people, places) with **the search index Photos
  maintains itself**: things it recognised in the photos ("beach",
  "mountain"), text found in images, camera models, seasons, media types.
  Matching index entries are shown as chips above the results.

**Everything else**
- Keyboard: ← → Esc `F` `S` `i` `+` `-` `0` Space `/`; swipe gestures
- Light and dark mode, English and German UI
- **Installable as an app** in Chrome, Edge and on iOS/Android home screens
- Optional HTTP Basic auth

## How it works

```
Library.photoslibrary/
├── database/Photos.sqlite      → copied to the cache, then read
├── database/search/psi.sqlite  → Photos' search index, copied, used by search
├── originals/…                 → served for download / full view
└── resources/
    ├── derivatives/…           → thumbnails and screen-size previews
    └── renders/…               → your edited versions
```

On start (and whenever `Photos.sqlite` changes) the databases are **copied
into the cache directory** and only the copies are opened, so the library is never
locked or modified and can sit on a read-only mount. Everything else is read
on demand. Table and column names of the Photos database change between macOS
releases; the viewer resolves them at runtime instead of hard-coding them.

Tested with a library last opened by Photos on macOS 15 (data model 18600,
~57 000 items, 295 albums). Older Photos 5+ libraries (macOS 10.15 and later)
should work. Reports for other versions are welcome.

## Installation

The viewer is a small web server: it runs on one machine that can read the
library, and you open it in a browser, on that machine or on any other device
in your network. There is no separate desktop program, but Chrome and Edge can
install it as an app (see below).

Tested on Linux, with both Docker and Python. Windows and macOS should work
the same way; reports are welcome.

### Option A: Docker (server, NAS, any OS with Docker)

No clone needed, Docker builds straight from GitHub:

```sh
docker build -t photoslibrary-viewer https://github.com/atlaxis-digital/photoslibrary-viewer.git
docker run -d --name photos --restart unless-stopped -p 127.0.0.1:8395:8395 \
  -v "/path/to/My Library.photoslibrary:/library:ro" \
  -v photos-cache:/cache \
  -e PLV_TITLE="My Photos" \
  photoslibrary-viewer
```

Then open <http://127.0.0.1:8395>. To reach it from other devices, publish
the port on your LAN address instead of `127.0.0.1` (and read
[Security](#security)), or put it behind your reverse proxy.

### Option B: Python 3.10+ (also directly on Windows)

```sh
pip install git+https://github.com/atlaxis-digital/photoslibrary-viewer
photoslibrary-viewer "/path/to/My Library.photoslibrary" --cache ./cache
```

On Windows (PowerShell), with the library copied to drive `D:`:

```powershell
py -m pip install git+https://github.com/atlaxis-digital/photoslibrary-viewer
py -m photoslibrary_viewer "D:\My Library.photoslibrary" --cache "$env:LOCALAPPDATA\photoslibrary-viewer"
```

Then open <http://127.0.0.1:8395>. Use `--host 0.0.0.0` to allow other
devices in your network. Without Git installed, download the ZIP from GitHub
and run `pip install <unpacked folder>` instead.

### Use it like an app

- **Chrome / Edge (Windows, macOS, Linux, Android):** open the viewer and
  click the install icon in the address bar, or use the menu entry
  *Install app* (Chrome: *Cast, save and share → Install page as app*). It then
  opens in its own window with its own icon in the taskbar or start menu.
- **iPhone / iPad (Safari):** Share → *Add to Home Screen*.

Browsers only offer installation on a secure connection: `http://127.0.0.1`
or `http://localhost` work as they are; from another device you need HTTPS with
a certificate the device trusts (e.g. a reverse proxy with Let's Encrypt or a
local CA such as [mkcert](https://github.com/FiloSottile/mkcert)).

### Where should the library live?

Windows cannot read Mac-formatted (APFS/HFS+) drives. Common setups:

- **Server or NAS** (recommended): keep a copy of the library on a Linux
  server or NAS, run the viewer there and open it from any device.
- **Directly on Windows**: copy the library to an NTFS/exFAT drive or a
  network share, then use option B on Windows.

Don't let Photos on the Mac open a library that sits on a network share. Apple
doesn't support that and it can corrupt the library. Treat the copy the viewer
reads as a mirror (for example `rsync -a --delete` from the Mac) and keep the
working library on a local drive.

## Configuration

| Variable          | CLI flag        | Default            | Meaning                                        |
|-------------------|-----------------|--------------------|------------------------------------------------|
| `PLV_LIBRARY`     | positional      | –                  | Path to the `.photoslibrary`                   |
| `PLV_CACHE`       | `--cache`       | `./cache`          | Database copy and converted images             |
| `PLV_HOST`        | `--host`        | `127.0.0.1`        | Bind address (`0.0.0.0` in Docker)             |
| `PLV_PORT`        | `--port`        | `8395`             | Port                                           |
| `PLV_TITLE`       |                 | library name       | Title shown in the sidebar                     |
| `PLV_SHOW_HIDDEN` | `--show-hidden` | `0`                | `1` includes photos marked as hidden           |
| `PLV_SHOW_DELETED`|                 | `0`                | `1` adds the Recently Deleted view             |
| `PLV_MAP_TILES`   |                 | OpenStreetMap      | Tile URL template for the Places map           |
| `PLV_MAP_ATTRIBUTION` |             | © OpenStreetMap    | Attribution shown on the map                   |
| `PLV_REFRESH`     |                 | `300`              | Seconds between checks for a changed database  |
| `PLV_USER`        |                 | –                  | Basic auth user name (optional)                |
| `PLV_PASSWORD`    |                 | –                  | Enables Basic auth when set                    |

## Security

Your photo library is private. The viewer has **no authentication unless
`PLV_PASSWORD` is set**, and it binds to localhost by default. Reach it
through your LAN, a VPN (WireGuard, Tailscale, …) or a reverse proxy with
proper authentication. Don't expose it to the internet as is.

## Limitations

- Read-only by design: no editing, favoriting or album changes.
- Smart albums, Shared Albums and iCloud-only items ("optimize Mac storage")
  are not shown. Items without a local original still show their preview if
  Photos stored one. Memories show their photos, not the generated movie.
- Videos play if the browser supports the codec (H.264 everywhere; HEVC
  depends on browser and hardware). Other formats (AVI, 3GP) can be
  downloaded.
- The Places map loads map tiles from OpenStreetMap by default, so the
  areas you look at are requested from their servers. Set `PLV_MAP_TILES` to
  your own tile server to avoid that. Everything else stays on your server.
- Days, Months, Memories, place names and the search index exist only for
  photos Photos has already analysed on the Mac.

## Prior art

[osxphotos](https://github.com/RhetTbull/osxphotos) documents the Photos
database in great depth and is the tool of choice for **exporting** a library
on a Mac. This project takes a different approach: no export and no Mac, just
a browser view of the library as it is.

## License

MIT, see [LICENSE](LICENSE). Bundled: [Leaflet](https://leafletjs.com)
(BSD-2-Clause) and
[Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster)
(MIT), see their `LICENSE` files under `photoslibrary_viewer/static/vendor/`.
