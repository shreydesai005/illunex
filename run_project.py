"""
Run the full pipeline on REAL data:
  - rooms.json / positions.json -- produced by running ifc_extractor.py
    against your real IFC file
  - catalog.json -- your catalog_draft.json (from build_catalog.py) with
    every TODO_ field filled in by hand

Usage: python3 run_project.py
Expects rooms.json, positions.json, and catalog.json in the same folder.
"""

import json
import sys

from position_matcher import load_rooms, load_positions, match_positions_to_catalog


def _has_unfinished_todo(product: dict) -> bool:
    for v in product.values():
        if isinstance(v, str) and v.startswith("TODO_"):
            return True
        if isinstance(v, list) and any(isinstance(x, str) and x.startswith("TODO_") for x in v):
            return True
    return False


def main():
    try:
        rooms = load_rooms("rooms.json")
        positions = load_positions("positions.json")
    except FileNotFoundError as e:
        print(f"Missing {e.filename} -- run ifc_extractor.py against your real IFC file first.")
        sys.exit(1)

    try:
        with open("catalog.json") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        print("Missing catalog.json -- finish filling in the TODO_ fields in "
              "catalog_draft.json and save it as catalog.json.")
        sys.exit(1)

    unfinished = [c["product_id"] for c in catalog if _has_unfinished_todo(c)]
    if unfinished:
        print(f"WARNING: these products still have unfinished TODO_ fields and "
              f"will likely fail to match anything: {unfinished}\n")

    # Only feed products meant for automated matching (floor lamps etc. were
    # already flagged include_in_automated_matching=False by build_catalog.py)
    catalog = [c for c in catalog if c.get("include_in_automated_matching", True)]

    results = match_positions_to_catalog(rooms, positions, catalog)

    positions_by_id = {p.position_id: p for p in positions}
    rooms_by_id = {r.room_id: r for r in rooms}

    print("=== Per-position matches ===")
    for pos_id, r in results.items():
        product = r["product"]["product_id"] if r["product"] else "NO MATCH"
        score = f"{r['score']:.3f}" if r["score"] is not None else "N/A"
        room_id = positions_by_id[pos_id].room_id
        room_label = rooms_by_id[room_id].application
        print(f"{pos_id} [{room_label}]: -> {product}  "
              f"(needed ~{r['required_lumens_per_fixture']} lm, "
              f"{r['candidates_considered']} candidates, score={score})")

    print("\n=== Per-room summary ===")
    by_room = {}
    for pos_id, r in results.items():
        room_id = positions_by_id[pos_id].room_id
        by_room.setdefault(room_id, []).append(r)

    for room_id, room_results in by_room.items():
        room = rooms_by_id[room_id]
        matched = [r for r in room_results if r["product"]]
        total_lumens = sum(r["product"]["total_lumens"] for r in matched)

        # Every position in the same (room, role) group carries the same
        # required_lumens_per_fixture, computed whether or not a match was
        # found -- summing it across all positions gives the room's true
        # total lumen requirement, which is a stronger check than "did each
        # fixture individually clear the tolerance band."
        total_required = sum(r["required_lumens_per_fixture"] for r in room_results)
        pct_of_target = (total_lumens / total_required * 100) if total_required else 0

        flag = ""
        if matched and pct_of_target < 85:
            flag = f"  <-- WARNING: only ~{pct_of_target:.0f}% of the lumens needed to hit " \
                   f"{room.target_lux} lux -- matched fixtures individually passed the " \
                   f"per-fixture tolerance band, but collectively this room is likely " \
                   f"under-lit. Needs a stronger product in the catalog for this application, " \
                   f"or more fixtures in the CAD placement."

        print(f"{room.application} ({room_id[:8]}...): "
              f"{len(matched)}/{len(room_results)} fixtures matched, "
              f"target {room.target_lux} lux, "
              f"~{total_lumens:.0f}/{total_required:.0f} total lumens delivered{flag}")

    unmatched_positions = [pos_id for pos_id, r in results.items() if not r["product"]]
    if unmatched_positions:
        print(f"\n{len(unmatched_positions)} position(s) got NO MATCH -- likely "
              f"means no catalog product fits that room's application/mounting/lumen "
              f"requirements. Check the candidates_considered count above for each: "
              f"0 candidates means a hard filter (application/mounting/CRI/CCT) "
              f"excluded everything; a low nonzero count with no match shouldn't "
              f"happen and would indicate a bug worth reporting back.")


if __name__ == "__main__":
    main()