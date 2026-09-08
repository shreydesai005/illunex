"""
Demonstrates the full flow on synthetic data, standing in for:
  - what your geometry-extraction stage (ezdxf/IfcOpenShell) would hand you
    for rooms, and what your placement algorithm already decided for
    positions
  - what gldf_extractor.py / ies_parser.py would hand you for the catalog,
    once run against your real 3-4 manufacturer catalogs

Run: python3 example_usage.py
"""

import json
from position_matcher import RoomRequirement, LightingPosition, match_positions_to_catalog

# --- 1. Rooms, as your geometry-extraction stage would produce them ---
rooms = [
    RoomRequirement(
        room_id="conf_room_1",
        application="conference_room",
        polygon=[(0, 0), (8, 0), (8, 6), (0, 6)],   # 8m x 6m room
        ceiling_height_m=3.0,
        target_lux=500,
        cct_k=4000,
        min_cri=80,
    ),
]

# --- 2. Positions, already fixed by your placement algorithm ---
# 6 ambient downlights in a grid + 2 wall washers on the presentation wall
positions = [
    LightingPosition("L1", "conf_room_1", 2, 1.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("L2", "conf_room_1", 4, 1.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("L3", "conf_room_1", 6, 1.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("L4", "conf_room_1", 2, 4.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("L5", "conf_room_1", 4, 4.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("L6", "conf_room_1", 6, 4.5, 3.0, "recessed_ceiling", "ambient"),
    LightingPosition("W1", "conf_room_1", 1, 6, 3.0, "recessed_ceiling", "wall_wash"),
    LightingPosition("W2", "conf_room_1", 7, 6, 3.0, "recessed_ceiling", "wall_wash"),
]

# --- 3. Catalog, normalized -- this is what ies_parser.py / gldf_extractor.py
#         output feeds into, after you add application/mounting/aesthetic tags ---
catalog = [
    {
        "product_id": "TC-PANEL-5200",
        "application": "conference_room", "mounting_type": "recessed_ceiling",
        "total_lumens": 5200, "input_watts": 42.0, "cct_k": 4000, "cri": 90,
        "aesthetic_tags": ["minimalist"], "price": 145,
    },
    {
        "product_id": "TC-PANEL-6800",
        "application": "conference_room", "mounting_type": "recessed_ceiling",
        "total_lumens": 6800, "input_watts": 50.0, "cct_k": 4000, "cri": 90,
        "aesthetic_tags": ["minimalist"], "price": 168,
    },
    {
        "product_id": "TC-WW-400",
        "application": "conference_room", "mounting_type": "recessed_ceiling",
        "total_lumens": 1100, "input_watts": 11.0, "cct_k": 4000, "cri": 85,
        "aesthetic_tags": ["minimalist"], "price": 65,
    },
    {
        "product_id": "GENERIC-WAREHOUSE-HB",
        "application": "warehouse", "mounting_type": "pendant",
        "total_lumens": 12000, "input_watts": 90, "cct_k": 5000, "cri": 70,
        "aesthetic_tags": ["industrial"], "price": 120,
    },
]

results = match_positions_to_catalog(rooms, positions, catalog,
                                      style_profile=["minimalist"])

for pos_id, r in results.items():
    product = r["product"]["product_id"] if r["product"] else "NO MATCH FOUND"
    score_str = f"{r['score']:.3f}" if r["score"] is not None else "N/A"
    print(f"{pos_id}: -> {product}  "
          f"(needed ~{r['required_lumens_per_fixture']} lm/fixture, "
          f"UF={r['utilization_factor']}, "
          f"{r['candidates_considered']} candidates considered, "
          f"score={score_str})")
