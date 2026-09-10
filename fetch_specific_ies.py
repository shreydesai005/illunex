"""
Fetches ONE specific .ies file on demand, by hash, from your existing
ieslibrary_index.json -- the alternative to bulk-downloading all ~90,000
files. Use this once you've filtered the index down to products you're
actually considering for a real project.

Usage:
    python3 fetch_specific_ies.py <hash>
    python3 fetch_specific_ies.py --manufacturer BEGA --min-lumens 1000 --max-lumens 3000
        (lists matching candidates without downloading -- use this to find
        hashes worth fetching, then fetch just those)

Requires: pip install certifi
"""

import argparse
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

from download_ies_files import sanitize_filename, OUTPUT_DIR, HEADERS

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
BASE_URL = "https://ieslibrary.com"


def parse_lumens(lamp_str: str):
    """'2800 lm,24 W' -> 2800.0 -- returns None if unparseable."""
    match = re.search(r"([\d.]+)\s*lm", lamp_str or "")
    return float(match.group(1)) if match else None


def find_candidates(entries, manufacturer=None, min_lumens=None, max_lumens=None, search=None):
    results = []
    for e in entries:
        if manufacturer and manufacturer.lower() not in (e.get("manufacturString") or "").lower():
            continue
        if search and search.lower() not in (e.get("luminaire") or "").lower():
            continue
        lumens = parse_lumens(e.get("lamp", ""))
        if min_lumens and (lumens is None or lumens < min_lumens):
            continue
        if max_lumens and (lumens is None or lumens > max_lumens):
            continue
        results.append(e)
    return results


def fetch_by_hash(entries, target_hash):
    entry = next((e for e in entries if e.get("hash") == target_hash), None)
    if entry is None:
        print(f"Hash '{target_hash}' not found in ieslibrary_index.json")
        return

    manufacturer = sanitize_filename(entry.get("manufacturString", "unknown"))
    model = sanitize_filename(entry.get("luminaire", target_hash))
    out_dir = OUTPUT_DIR / manufacturer
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{model}_{target_hash}.ies"

    if out_path.exists():
        print(f"Already have it: {out_path}")
        return

    url = BASE_URL + entry["downloadUrlIes"]
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as response:
        content = response.read()
    out_path.write_bytes(content)
    print(f"Downloaded: {out_path} ({entry.get('manufacturString')} {entry.get('luminaire')}, "
          f"{entry.get('lamp')})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("hash", nargs="?", help="Specific file hash to download")
    parser.add_argument("--manufacturer", type=str, default=None)
    parser.add_argument("--search", type=str, default=None, help="Substring match on model/luminaire name")
    parser.add_argument("--min-lumens", type=float, default=None)
    parser.add_argument("--max-lumens", type=float, default=None)
    args = parser.parse_args()

    try:
        with open("ieslibrary_index.json") as f:
            entries = json.load(f)
    except FileNotFoundError:
        print("Missing ieslibrary_index.json -- run fetch_ieslibrary_index.py first "
              "(even a partial index, from --max-pages, works fine for browsing candidates).")
        sys.exit(1)

    if args.hash:
        fetch_by_hash(entries, args.hash)
        return

    candidates = find_candidates(entries, args.manufacturer, args.min_lumens,
                                  args.max_lumens, args.search)
    print(f"{len(candidates)} matching candidates (metadata only, nothing downloaded):\n")
    for e in candidates[:50]:
        print(f"  {e.get('hash')}  {e.get('manufacturString'):15}  {e.get('luminaire'):20}  {e.get('lamp')}")
    if len(candidates) > 50:
        print(f"  ... and {len(candidates) - 50} more (showing first 50)")
    print(f"\nTo download one: python3 fetch_specific_ies.py <hash>")


if __name__ == "__main__":
    main()
