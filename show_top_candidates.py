"""
Shows the top several candidate products per room/role -- real options
to choose between, instead of one forced pick.

Usage: python3 show_top_candidates.py [top_n]
"""

import json
import sys

from position_matcher import load_rooms, load_positions, get_top_candidates

top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 6

rooms = load_rooms("rooms.json")
positions = load_positions("positions.json")
with open("catalog.json") as f:
    catalog_full = json.load(f)
catalog = [c for c in catalog_full if c.get("include_in_automated_matching", True)]

results = get_top_candidates(rooms, positions, catalog, top_n=top_n)

for (room_id, role), data in results.items():
    print(f"\n=== {data['room_application']} / {role} "
          f"({len(data['position_ids'])} position(s), "
          f"needed ~{data['required_lumens_per_fixture']} lm/fixture) ===")
    if not data["candidates"]:
        print("  No candidates passed the filters.")
        continue
    for i, cand in enumerate(data["candidates"]):
        p = cand["product"]
        print(f"  #{i+1}  score={cand['score']:.3f}  {p.get('product_id')}  "
              f"{p.get('total_lumens')} lm, {p.get('input_watts')} W, "
              f"CCT {p.get('cct_k')}, CRI {p.get('cri')}, "
              f"${p.get('price', '?')}")
    print(f"  ({data['total_candidates_considered']} total passed the hard filters)")
