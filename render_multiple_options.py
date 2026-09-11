"""
Renders the SAME room multiple times, once per top candidate product --
not just different camera angles of one auto-matched winner, but genuinely
different real .ies files driving the light each time, for direct visual
comparison between real options.

Usage: python3 render_multiple_options.py <room_id> [top_n] [view]
Default view is full_room (the wide overview); pass any other view name
(corner, front, top, etc.) to use that instead.
"""

import sys
import json
from pathlib import Path

from position_matcher import load_rooms, load_positions, get_top_candidates
from render_from_ifc import load_ies_light, render, get_full_room_view, get_views


def build_lights_for_product(positions, product, min_x, min_y):
    """Builds a lights list using ONE SPECIFIC product for every position
    in this group, instead of each position's own auto-matched winner --
    this is what lets us render 'what if every fixture here used Product
    X' for a real side-by-side comparison."""
    ies_file = product.get("source_ies_file")
    if not ies_file or not Path(ies_file).exists():
        return None
    lights = []
    for pos in positions:
        local_pos = (pos.x - min_x, pos.y - min_y, pos.z)
        light = load_ies_light(ies_file, local_pos)
        light["position_id"] = pos.position_id
        light["product_id"] = product.get("product_id")
        lights.append(light)
    return lights


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 render_multiple_options.py <room_id> [top_n] [view]")
        sys.exit(1)
    room_id = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    view_name = sys.argv[3] if len(sys.argv) > 3 else "full_room"

    rooms = load_rooms("rooms.json")
    positions = load_positions("positions.json")
    room = next((r for r in rooms if r.room_id == room_id), None)
    if room is None:
        print(f"Room '{room_id}' not found in rooms.json")
        sys.exit(1)

    try:
        with open("catalog.json") as f:
            catalog_full = json.load(f)
    except FileNotFoundError:
        print("Missing catalog.json.")
        sys.exit(1)
    catalog = [c for c in catalog_full if c.get("include_in_automated_matching", True)]

    results = get_top_candidates(rooms, positions, catalog, top_n=top_n)

    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    min_x, min_y = min(xs), min(ys)
    width = max(xs) - min_x
    depth = max(ys) - min_y
    height = room.ceiling_height_m

    room_positions = [p for p in positions if p.room_id == room_id]

    rendered = []
    for (rid, role), data in results.items():
        if rid != room_id:
            continue
        role_positions = [p for p in room_positions if p.position_id in data["position_ids"]]
        print(f"\n{role}: {len(data['candidates'])} candidate(s) to render "
              f"({data['total_candidates_considered']} total passed filters)")

        if not data["candidates"]:
            print("  No candidates available -- catalog.json needs more coverage for this role.")
            continue

        for i, cand in enumerate(data["candidates"]):
            product = cand["product"]
            lights = build_lights_for_product(role_positions, product, min_x, min_y)
            if lights is None:
                print(f"  #{i+1} {product.get('product_id')}: SKIPPED -- no .ies file at "
                      f"'{product.get('source_ies_file')}'")
                continue

            if view_name == "full_room":
                v = get_full_room_view(width, depth, height)
                supersample = 1
            else:
                views = get_views(width, depth, height)
                if "fixtures" not in views and view_name == "fixtures":
                    from render_from_ifc import get_fixture_view
                    views["fixtures"] = get_fixture_view(lights, width, depth, height)
                v = views.get(view_name, get_full_room_view(width, depth, height))
                supersample = 2

            out_path = f"option{i+1}_{product.get('product_id')}_{view_name}.png"
            render(lights, v["cam_pos"], v["look_at"], width, depth, height,
                   fov_deg=v["fov_deg"], out_path=out_path, supersample=supersample)
            print(f"  #{i+1} {product.get('product_id')} (score={cand['score']:.3f}, "
                  f"{product.get('total_lumens')} lm, {product.get('input_watts')} W) "
                  f"-> {out_path}")
            rendered.append(out_path)

    print(f"\n{len(rendered)} option(s) rendered: {rendered}")


if __name__ == "__main__":
    main()
