"""
The full pipeline in one command: a real IFC file goes in, and out comes
a mathematically-placed, real-product-selected, multi-angle rendered
result. Ties together every piece built across this project:

  1. ifc_extractor.py    -- reads real room geometry from your IFC
  2. placement_generator.py -- computes WHERE lights go, from the lumen
     method + spacing/uniformity math (not reading pre-existing fixture
     positions -- deciding them from scratch)
  3. position_matcher.py -- picks the real catalog product for each
     generated position
  4. render_from_ifc.py  -- renders the result from multiple angles

Usage:
    python3 run_full_pipeline.py <ifc_file> [room_id] [views]

Examples:
    python3 run_full_pipeline.py Unit-02.ifc
        (all rooms, default views)
    python3 run_full_pipeline.py Unit-02.ifc 2H5YeoVaROWb0biZuwK43Q
        (just one room, default views)
    python3 run_full_pipeline.py Unit-02.ifc 2H5YeoVaROWb0biZuwK43Q corner,top
        (one room, specific views)

Requires ifcopenshell (for step 1) and a completed catalog.json (for step 3)
-- see README.md for the full setup. This can't be run or tested in the
sandbox that built it (no network to install ifcopenshell there); it's
built from the same, already-individually-tested pieces everything else
in this project uses.
"""

import sys
import json

from ifc_extractor import extract_rooms
from requirements_table import RESIDENTIAL_REQUIREMENTS, SKIP_ROOM_TYPES
from placement_generator import generate_fixture_grid
from position_matcher import save_rooms_and_positions
from render_from_ifc import build_scene_from_real_data, render, get_views


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_full_pipeline.py <ifc_file> [room_id] [views]")
        sys.exit(1)

    ifc_path = sys.argv[1]
    room_id_filter = sys.argv[2] if len(sys.argv) > 2 else None
    requested_views = sys.argv[3].split(",") if len(sys.argv) > 3 else \
        ["corner", "front", "top", "bottom_worms_eye"]

    # --- Step 1: real room geometry from the real IFC ---
    print(f"--- Extracting rooms from {ifc_path} ---")
    rooms = extract_rooms(ifc_path, RESIDENTIAL_REQUIREMENTS, SKIP_ROOM_TYPES)
    if room_id_filter:
        rooms = [r for r in rooms if r.room_id == room_id_filter]
        if not rooms:
            print(f"Room '{room_id_filter}' not found. Run ifc_extractor.py directly "
                  f"first to see the real room_id values in this file.")
            sys.exit(1)
    print(f"Found {len(rooms)} room(s) to place lighting in.\n")

    # --- Step 2: mathematically decide WHERE lights go, per room ---
    print("--- Computing fixture placement (lumen method + spacing/uniformity) ---")
    all_positions = []
    for room in rooms:
        result = generate_fixture_grid(room)
        all_positions.extend(result["positions"])
        print(f"  {room.application} ({room.room_id[:8]}...): "
              f"{result['rows']}x{result['cols']} grid = {result['n_fixtures']} fixtures "
              f"(binding constraint: {result['binding_constraint']})")
    print(f"\nGenerated {len(all_positions)} positions total.\n")

    # Save in the same format every other script in this project reads --
    # this is what makes step 4 able to reuse render_from_ifc.py unmodified.
    save_rooms_and_positions(rooms, all_positions)

    # --- Step 3 + 4: real product matching + multi-angle render, per room ---
    print("--- Matching real products and rendering ---")
    for room in rooms:
        print(f"\n{room.application} ({room.room_id[:8]}...):")
        try:
            width, depth, height, lights = build_scene_from_real_data(room.room_id)
        except FileNotFoundError as e:
            print(f"  ERROR: missing {e.filename} -- make sure catalog.json exists "
                  f"(see build_catalog.py / fill_catalog_todos.py).")
            continue

        if not lights:
            print(f"  No positions matched a real product -- check catalog.json coverage "
                  f"for application '{room.application}'. Skipping render for this room.")
            continue

        print(f"  {len(lights)} position(s) matched to real products:")
        for light in lights:
            print(f"    {light['source_file']}: {light['total_lumens']:.0f} lm")

        # Companion manifest: exactly which real product/IES file ended up
        # at each position, saved alongside the rendered images -- not just
        # printed to console and lost once the terminal scrolls past it.
        products_used = [{
            "position_id": light["position_id"],
            "product_id": light["product_id"],
            "source_ies_file": light["source_file"],
            "total_lumens": light["total_lumens"],
            "input_watts": light["input_watts"],
            "price": light["price"],
        } for light in lights]
        manifest_path = f"final_{room.room_id[:8]}_products_used.json"
        with open(manifest_path, "w") as f:
            json.dump(products_used, f, indent=2)
        print(f"  Wrote {manifest_path}")

        views = get_views(width, depth, height)
        for view_name in requested_views:
            if view_name not in views:
                print(f"  Unknown view '{view_name}', skipping.")
                continue
            v = views[view_name]
            out_path = f"final_{room.room_id[:8]}_{view_name}.png"
            render(lights, v["cam_pos"], v["look_at"], width, depth, height,
                   fov_deg=v["fov_deg"], out_path=out_path)

    print("\nDone. Rendered images are named final_<room>_<view>.png in this folder.")


if __name__ == "__main__":
    main()