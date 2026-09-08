"""
Fetches ALL pages of metadata from ieslibrary.com's real API (found via
DevTools -- POST https://ieslibrary.com/browse/api/pageIes/data.json,
page/pageSize/search/favoritesOnly as form-urlencoded params).

This only fetches metadata (manufacturer, model, lumens/watts, and the
download URL for each fixture) -- not the actual .ies files themselves.
At ~90,000+ fixtures / 24 per page, that's 3,750+ requests; doing this as
its own fast pass first means you can see the full real scope and filter
by manufacturer before committing to downloading potentially gigabytes
of actual files.

Being a respectful citizen of someone else's server: real delay between
requests, an honest User-Agent identifying this as a script for a
personal project (not pretending to be a browser), and a --max-pages
flag to test on a small slice before running the full thing.

Usage:
    python3 fetch_ieslibrary_index.py --max-pages 5      # test run first
    python3 fetch_ieslibrary_index.py                    # full run (slow)

Requires: pip install certifi
Outputs: ieslibrary_index.json (a manifest, not the files themselves)
"""

import argparse
import json
import ssl
import time
import urllib.parse
import urllib.request

import certifi

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
API_URL = "https://ieslibrary.com/browse/api/pageIes/data.json"
PAGE_SIZE = 24
DELAY_SECONDS = 0.6  # real pacing, not hammering their server

HEADERS = {
    "User-Agent": "ies-library-indexer/0.1 (personal lighting-design project; "
                   "respectful pacing, indexing metadata only)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def fetch_page(page: int):
    payload = urllib.parse.urlencode({
        "page": page, "pageSize": PAGE_SIZE, "search": "", "favoritesOnly": "false",
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=None,
                         help="Stop after this many pages (for testing). Omit for a full run.")
    args = parser.parse_args()

    all_entries = []
    page = 0
    while True:
        if args.max_pages is not None and page >= args.max_pages:
            print(f"Reached --max-pages limit ({args.max_pages}), stopping.")
            break

        try:
            entries = fetch_page(page)
        except Exception as e:
            print(f"ERROR on page {page}: {e}")
            print("Stopping here -- whatever was collected so far is still saved below.")
            break

        if not entries:
            print(f"Page {page} returned empty -- reached the end of the catalog.")
            break

        all_entries.extend(entries)
        manufacturers_seen = len(set(e.get("manufacturString", "") for e in all_entries))
        print(f"Page {page}: +{len(entries)} entries (total: {len(all_entries)}, "
              f"{manufacturers_seen} distinct manufacturers so far)")

        page += 1
        time.sleep(DELAY_SECONDS)

    with open("ieslibrary_index.json", "w") as f:
        json.dump(all_entries, f, indent=2)

    print(f"\nWrote {len(all_entries)} entries to ieslibrary_index.json")
    manufacturers = sorted(set(e.get("manufacturString", "") for e in all_entries))
    print(f"Manufacturers found ({len(manufacturers)}): {manufacturers}")


if __name__ == "__main__":
    main()
