"""``python -m photoslibrary_viewer /path/to/Library.photoslibrary``"""

import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="photoslibrary-viewer",
        description="Browse a macOS Photos library (.photoslibrary) in the browser, read-only.",
    )
    parser.add_argument("library", nargs="?", default=os.environ.get("PLV_LIBRARY"),
                        help="path to the .photoslibrary (or set PLV_LIBRARY)")
    parser.add_argument("--host", default=os.environ.get("PLV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PLV_PORT", "8395")))
    parser.add_argument("--cache", default=os.environ.get("PLV_CACHE", "./cache"),
                        help="directory for the database copy and converted images")
    parser.add_argument("--show-hidden", action="store_true",
                        default=os.environ.get("PLV_SHOW_HIDDEN") == "1",
                        help="include photos marked as hidden")
    args = parser.parse_args()
    if not args.library:
        parser.error("no library given")
    os.environ["PLV_LIBRARY"] = args.library
    os.environ["PLV_CACHE"] = args.cache
    os.environ["PLV_SHOW_HIDDEN"] = "1" if args.show_hidden else "0"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
