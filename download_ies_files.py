"""
Downloads the actual .ies files listed in ieslibrary_index.json (built by
fetch_ieslibrary_index.py). Built for real scale (potentially ~90,000
files), which means two things a small script wouldn't need:

  1. RESUMABLE -- skips any file already saved to disk before requesting
     it again. A multi-hour run WILL get interrupted at some point
     (laptop sleep, network drop, closed terminal) -- without this,
     that means starting over from zero.
  2. Modest concurrency -- a small worker pool (default 4) instead of
     strictly one-at-a-time, cutting total time substantially while
     staying well within what a normal browser does loading a page
     (which commonly opens 6+ simultaneous connections). Each worker
     still paces itself, so this isn't a burst of thousands of
     simultaneous requests -- just a few real people's worth of traffic
     instead of one.

Usage:
    python3 download_ies_files.py --limit 200      # test run first
    python3 download_ies_files.py                  # full run (hours)
    python3 download_ies_files.py                  # re-run any time --
                                                     # already-downloaded
                                                     # files are skipped

Requires: pip install certifi
Reads: ieslibrary_index.json
Writes: ies_downloads/<manufacturer>/<model>_<hash>.ies
"""

import argparse
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import certifi

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
BASE_URL = "https://ieslibrary.com"
OUTPUT_DIR = Path("ies_downloads")
DELAY_PER_WORKER_SECONDS = 0.6
DEFAULT_WORKERS = 4

HEADERS = {
    "User-Agent": "ies-library-downloader/0.1 (personal lighting-design project; "
                   "respectful pacing, resumable)",
}


def sanitize_filename(name: str) -> str:
    """Filesystem-safe -- luminaire model names can contain spaces, degree
    symbols, slashes, etc. (e.g. '84302RK3 25°')."""
    name = re.sub(r"[^\w\-.]", "_", name)
    return re.sub(r"_+", "_", name).strip("_")


def download_one(entry: dict) -> tuple:
    manufacturer = sanitize_filename(entry.get("manufacturString", "unknown"))
    model = sanitize_filename(entry.get("luminaire", entry.get("hash", "unknown")))
    file_hash = entry.get("hash", "")
    download_path = entry.get("downloadUrlIes", "")

    if not entry.get("hasIes") or not download_path:
        return ("skipped_no_ies", entry.get("hash"))

    out_dir = OUTPUT_DIR / manufacturer
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{model}_{file_hash}.ies"

    if out_path.exists() and out_path.stat().st_size > 0:
        return ("already_exists", str(out_path))

    url = BASE_URL + download_path
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as response:
            content = response.read()
        out_path.write_bytes(content)
        time.sleep(DELAY_PER_WORKER_SECONDS)
        return ("downloaded", str(out_path))
    except Exception as e:
        return ("error", f"{file_hash}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Only process this many entries (for testing).")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                         help=f"Parallel download workers (default {DEFAULT_WORKERS}).")
    parser.add_argument("--manufacturer", type=str, default=None,
                         help="Only download this manufacturer (case-insensitive substring match).")
    parser.add_argument("--manifest-only", action="store_true",
                         help="Don't download anything -- just rebuild downloaded_manifest.json "
                              "from whatever's already on disk. Useful to check progress.")
    args = parser.parse_args()

    try:
        with open("ieslibrary_index.json") as f:
            entries = json.load(f)
    except FileNotFoundError:
        print("Missing ieslibrary_index.json -- run fetch_ieslibrary_index.py first.")
        return

    if args.manifest_only:
        build_manifest(entries)
        return

    if args.manufacturer:
        needle = args.manufacturer.lower()
        entries = [e for e in entries if needle in e.get("manufacturString", "").lower()]
        print(f"Filtered to manufacturer matching '{args.manufacturer}': {len(entries)} entries")

    if args.limit:
        entries = entries[:args.limit]

    print(f"Processing {len(entries)} entries with {args.workers} workers "
          f"(already-downloaded files will be skipped automatically)...")

    counts = {"downloaded": 0, "already_exists": 0, "skipped_no_ies": 0, "error": 0}
    errors = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, e): e for e in entries}
        for future in as_completed(futures):
            status, detail = future.result()
            counts[status] += 1
            if status == "error":
                errors.append(detail)
            completed += 1
            if completed % 100 == 0 or completed == len(entries):
                print(f"  {completed}/{len(entries)} processed -- "
                      f"{counts['downloaded']} downloaded, "
                      f"{counts['already_exists']} already had, "
                      f"{counts['error']} errors")

    print(f"\nDone. {counts}")
    if errors:
        print(f"\nFirst few errors (re-running this script will retry them automatically, "
              f"since only successful downloads are skipped):")
        for e in errors[:10]:
            print(f"  {e}")

    build_manifest(entries)


def build_manifest(entries):
    """Rebuilds a manifest by checking, for each entry, whether its file
    actually exists on disk -- not by tracking during the download loop
    itself, so this stays correct even if a run was interrupted partway
    and resumed later. Safe to call any time, including standalone via
    --manifest-only, to check progress without downloading anything."""
    manifest = []
    for e in entries:
        manufacturer = sanitize_filename(e.get("manufacturString", "unknown"))
        model = sanitize_filename(e.get("luminaire", e.get("hash", "unknown")))
        file_hash = e.get("hash", "")
        local_path = OUTPUT_DIR / manufacturer / f"{model}_{file_hash}.ies"
        if local_path.exists() and local_path.stat().st_size > 0:
            manifest.append({
                "local_path": str(local_path),
                "manufacturer": e.get("manufacturString"),
                "model": e.get("luminaire"),
                "hash": file_hash,
                "lamp": e.get("lamp"),  # e.g. "2800 lm,24 W" -- combined lumens+watts
                "issuedate": e.get("issuedate"),
                "preview_image": e.get("preview"),
            })

    with open("downloaded_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nWrote downloaded_manifest.json with {len(manifest)} entries "
          f"(files actually confirmed present on disk).")


if __name__ == "__main__":
    main()