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

- **Timeline** of all photos and videos, grouped by month, with a year
  scrubber; smooth even with 50 000+ items (virtualized grid)
- **Albums and folders** in their original nesting and order
- **People**: named people with face thumbnails
- **Favorites, Videos, Live Photos, Edited** smart views
- **Edited versions** are shown; the untouched original is one click away
- **Videos** stream with seeking; **Live Photos** play their motion clip
- **HEIC** photos are converted to JPEG on the fly for browsers that can't
  show HEIC (converted files are cached)
- **Info panel**: date with capture time zone, camera, lens, exposure,
  location (OpenStreetMap link), albums, people and keywords
- **Search** across file names, titles, captions, keywords, album names and
  people
- Keyboard (← → Esc `i` Space `/`), swipe gestures, light and dark mode,
  English and German UI
- Optional HTTP Basic auth

## How it works

```
Library.photoslibrary/
├── database/Photos.sqlite      → copied to the cache, then read
├── originals/…                 → served for download / full view
└── resources/
    ├── derivatives/…           → thumbnails and screen-size previews
    └── renders/…               → your edited versions
```

On start (and whenever `Photos.sqlite` changes) the database is **copied into
the cache directory** and only the copy is opened, so the library is never
locked or modified and can sit on a read-only mount. Everything else is read
on demand. Table and column names of the Photos database change between macOS
releases; the viewer resolves them at runtime instead of hard-coding them.

Tested with a library last opened by Photos on macOS 15 (data model 18600,
~57 000 items, 295 albums). Older Photos 5+ libraries (macOS 10.15 and later)
should work. Reports for other versions are welcome.

## Quick start

### Docker

```sh
docker build -t photoslibrary-viewer .
docker run -d --name photos -p 127.0.0.1:8395:8395 \
  -v "/path/to/My Library.photoslibrary:/library:ro" \
  -v photos-cache:/cache \
  -e PLV_TITLE="My Photos" \
  photoslibrary-viewer
```

Open <http://127.0.0.1:8395>.

### Python (3.10+)

```sh
pip install .
photoslibrary-viewer "/path/to/My Library.photoslibrary" --cache ./cache
```

### Where should the library live?

Windows cannot read Mac-formatted (APFS/HFS+) drives. Common setups:

- **Server or NAS** (recommended): keep a copy of the library on a Linux
  server or NAS, run the viewer there and open it from any device.
- **Directly on Windows**: copy the library to an NTFS/exFAT drive or a
  network share, then run the Python version on Windows.

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
- Smart albums, Memories, Shared Albums and iCloud-only items ("optimize Mac
  storage") are not shown. Items without a local original still show their
  preview if Photos stored one.
- Videos play if the browser supports the codec (H.264 everywhere; HEVC
  depends on browser and hardware). Other formats (AVI, 3GP) can be
  downloaded.
- Place names are not resolved; locations link to OpenStreetMap.

## Prior art

[osxphotos](https://github.com/RhetTbull/osxphotos) documents the Photos
database in great depth and is the tool of choice for **exporting** a library
on a Mac. This project takes a different approach: no export and no Mac, just
a browser view of the library as it is.

## License

MIT, see [LICENSE](LICENSE).
