"""
Closes the loop between the bulk-scraped ieslibrary.com index and the
actual matching/rendering pipeline: given a room, computes how many
lumens per fixture it actually needs (real lumen-method math), searches
ieslibrary_index.json for the closest real match, fetches that one
specific file, and adds it to catalog.json -- automatically, not by
manually browsing 90,000 entries.

Usage: python3 select_and_add_from_ieslibrary.py <room_id>

Requires: ieslibrary_index.json (fetch_ieslibrary_index.py -- even a
partial index works) and rooms.json (from ifc_extractor.py or
extract_room_from_geometry.py). Requires: pip install certifi
"""

import json
import re
import ssl
import sys
import urllib.request

import certifi

from position_matcher import load_rooms
from placement_generator import generate_fixture_grid
from ies_parser import parse_ies_file
from download_ies_files import sanitize_filename, OUTPUT_DIR

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
BASE_URL = "https://ieslibrary.com"
HEADERS = {"User-Agent": "ies-library-selector/0.1 (personal lighting-design project)"}


def parse_lumens_watts(lamp_str):
    """'2800 lm,24 W' -> (2800.0, 24.0)"""
    lumens_match = re.search(r"([\d.]+)\s*lm", lamp_str or "")
    watts_match = re.search(r"([\d.]+)\s*W", lamp_str or "")
    lumens = float(lumens_match.group(1)) if lumens_match else None
    watts = float(watts_match.group(1)) if watts_match else None
    return lumens, watts


def select_best_candidate(entries, required_lumens, band=(0.5, 2.0)):
    """Same filter-then-score philosophy as position_matcher.py: hard
    filter to a plausible lumen band first, then rank by closeness to the
    real requirement with efficacy as a tiebreaker. Skips entries with an
    empty manufacturer name -- the placeholder/junk records flagged
    earlier in this project."""
    candidates = []
    for e in entries:
        if not e.get("hasIes"):
            continue
        if not (e.get("manufacturString") or "").strip():
            continue
        lumens, watts = parse_lumens_watts(e.get("lamp", ""))
        if lumens is None or watts is None or watts == 0:
            continue
        if not (required_lumens * band[0] <= lumens <= required_lumens * band[1]):
            continue
        efficacy = lumens / watts
        candidates.append((e, lumens, watts, efficacy))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (abs(c[1] - required_lumens), -c[3]))
    return candidates[0]


def fetch_file(entry):
    manufacturer = sanitize_filename(entry.get("manufacturString", "unknown"))
    model = sanitize_filename(entry.get("luminaire", entry.get("hash", "unknown")))
    file_hash = entry.get("hash", "")
    out_dir = OUTPUT_DIR / manufacturer
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{model}_{file_hash}.ies"

    if not out_path.exists():
        url = BASE_URL + entry["downloadUrlIes"]
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as response:
            out_path.write_bytes(response.read())
    return out_path


def build_catalog_entry(entry, ies_path, application):
    parsed = None
    try:
        parsed = parse_ies_file(str(ies_path))
    except Exception as e:
        print(f"WARNING: couldn't parse downloaded file for extra detail: {e}")

    lumens, watts = parse_lumens_watts(entry.get("lamp", ""))
    manufacturer = entry.get("manufacturString", "unknown")
    model = entry.get("luminaire", entry.get("hash"))
    product_id = f"{sanitize_filename(manufacturer)}_{sanitize_filename(model)}_{entry['hash'][:8]}"

    cct_k = "TODO_confirm_cct_check_datasheet"
    cri = "TODO_confirm_cri_check_datasheet"
    if parsed:
        # Same lesson as earlier in this project: the parser's own
        # validated total_lumens (which corrects for symmetry-integration
        # errors) is more trustworthy than the raw metadata string.
        desc_text = f"{parsed.get('luminaire_description', '')} {parsed.get('lamp_description', '')}"
        cct_match = re.search(r"(\d{4})\s*K\b", desc_text)
        cri_match = re.search(r"CRI\s*[>]?\s*(\d{2})\b", desc_text, re.IGNORECASE)
        if cct_match:
            cct_k = int(cct_match.group(1))
        if cri_match:
            cri = int(cri_match.group(1))
        if parsed.get("total_lumens"):
            lumens = parsed["total_lumens"]
        if parsed.get("input_watts"):
            watts = parsed["input_watts"]

    return {
        "product_id": product_id,
        "manufacturer": manufacturer,
        "description": model,
        "total_lumens": lumens,
        "input_watts": watts,
        "cct_k": cct_k,
        "cri": cri,
        "mounting_type": "recessed_ceiling",  # TODO_confirm -- assumed, not in ieslibrary metadata
        "suitable_roles": ["ambient"],
        "application": [application],
        "aesthetic_tags": ["TODO_assign_style_tags"],
        "include_in_automated_matching": True,
        "price": "TODO_add_price",
        "source_ies_file": str(ies_path),
        "_source": "ieslibrary.com",
        "_download_count": entry.get("downloadCount"),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 select_and_add_from_ieslibrary.py <room_id>")
        sys.exit(1)
    room_id = sys.argv[1]

    try:
        with open("ieslibrary_index.json") as f:
            entries = json.load(f)
    except FileNotFoundError:
        print("Missing ieslibrary_index.json -- run fetch_ieslibrary_index.py first "
              "(even a partial index works).")
        sys.exit(1)

    rooms = load_rooms("rooms.json")
    room = next((r for r in rooms if r.room_id == room_id), None)
    if room is None:
        print(f"Room '{room_id}' not found in rooms.json")
        sys.exit(1)

    result = generate_fixture_grid(room)
    required_lumens = result["total_lumens_required"] / result["n_fixtures"]
    print(f"Room '{room.application}': {result['n_fixtures']} fixtures, "
          f"~{required_lumens:.0f} lm needed per fixture")

    best = select_best_candidate(entries, required_lumens)
    if best is None:
        print(f"No candidate in ieslibrary_index.json falls within a plausible "
              f"lumen range of {required_lumens:.0f} lm. Your index may still be "
              f"partial -- fetch more of it, or this may need a wider band.")
        sys.exit(1)

    entry, lumens, watts, efficacy = best
    print(f"Selected: {entry.get('manufacturString')} {entry.get('luminaire')} "
          f"({lumens:.0f} lm, {watts:.0f} W, {efficacy:.1f} lm/W, "
          f"{entry.get('downloadCount')} downloads)")

    ies_path = fetch_file(entry)
    print(f"Fetched: {ies_path}")

    catalog_entry = build_catalog_entry(entry, ies_path, room.application)

    try:
        with open("catalog.json") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        catalog = []
    catalog = [c for c in catalog if c.get("product_id") != catalog_entry["product_id"]]
    catalog.append(catalog_entry)
    with open("catalog.json", "w") as f:
        json.dump(catalog, f, indent=2)

    print(f"\nAdded '{catalog_entry['product_id']}' to catalog.json.")
    todos = [k for k, v in catalog_entry.items() if isinstance(v, str) and v.startswith("TODO_")]
    if todos:
        print(f"NOTE: these fields still need your confirmation: {todos}")
    print(f"\nNext: python3 continue_pipeline.py, then "
          f"python3 render_from_ifc.py {room_id} fixtures,front")


if __name__ == "__main__":
    main()
