"""
Continues the pipeline from rooms.json (produced by
extract_room_from_geometry.py) -- generates actual fixture positions
using the real lumen-method + spacing math, then saves them so
run_project.py / render_from_ifc.py can pick up from here.

Usage: python3 continue_pipeline.py
"""

from position_matcher import load_rooms, save_rooms_and_positions
from placement_generator import generate_fixture_grid


def main():
    rooms = load_rooms("rooms.json")
    room = rooms[0]

    result = generate_fixture_grid(room)
    print(f"Room: {room.application}, target {room.target_lux} lux")
    print(f"Placement: {result['rows']}x{result['cols']} grid = {result['n_fixtures']} fixtures "
          f"(binding constraint: {result['binding_constraint']})")
    print(f"  (lumens alone would need {result['n_from_lumens']}, "
          f"spacing alone would need {result['n_from_spacing']})")

    save_rooms_and_positions(rooms, result["positions"])
    print(f"\nSaved {len(result['positions'])} generated positions to positions.json")
    print("Next: python3 run_project.py (needs a real catalog.json), or "
          "python3 render_from_ifc.py <room_id> to render it.")


if __name__ == "__main__":
    main()
