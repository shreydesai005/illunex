"""
Generates fixture positions from scratch, given only room geometry and
lighting requirements -- no pre-existing CAD positions needed. This is
the "where should lights go" stage, upstream of position_matcher.py.

Design principle: this does NOT need to know which specific catalog
product will end up in each spot. It uses a generic "typical fixture"
assumption (configurable) to compute a physically sensible count and
grid, respecting two constraints:
  1. Enough total lumens to hit the room's target lux (lumen method)
  2. Spacing tight enough for reasonable uniformity (max spacing-to-
     mounting-height ratio) -- a room can have enough total lumens with
     too few, too-bright fixtures spread too far apart to look even.
Whichever constraint demands MORE fixtures wins.

Output is a list of LightingPosition objects -- the exact same dataclass
position_matcher.py already consumes, so nothing downstream changes.
Fixture SELECTION (which real product goes in each spot) is unchanged:
feed this function's output into match_positions_to_catalog() exactly
like real CAD-extracted positions.
"""

import math
from dataclasses import replace

from position_matcher import (
    RoomRequirement, LightingPosition,
    polygon_area, room_index, estimate_utilization_factor, _bbox_length_width,
)


def generate_fixture_grid(
    room: RoomRequirement,
    assumed_lumens_per_fixture: float = 900,
    max_spacing_to_height_ratio: float = 1.0,
    wall_offset_fraction: float = 0.5,
    role: str = "ambient",
    mounting_type: str = "recessed_ceiling",
) -> list:
    """
    assumed_lumens_per_fixture: a generic placeholder, not a real product's
      value -- used only to get a sensible fixture COUNT before any real
      product is chosen. 900lm is a reasonable mid-range residential
      downlight; override per project if your typical stock differs.
    max_spacing_to_height_ratio: SHR cap. 1.0 is conservative/safe for even
      coverage; some fixture types tolerate up to ~1.3-1.5, but starting
      conservative avoids under-provisioning uniformity.
    wall_offset_fraction: fixtures are inset from the wall by this fraction
      of one grid cell's spacing -- standard practice, avoids placing a
      fixture flush against a wall.
    """
    area = polygon_area(room.polygon)
    length, width = _bbox_length_width(room.polygon)
    mount_h = max(room.ceiling_height_m - room.task_height_m, 0.5)

    k = room_index(length, width, mount_h)
    uf = estimate_utilization_factor(k)

    # Constraint 1: total lumens needed
    total_lumens_required = (room.target_lux * area) / (uf * room.maintenance_factor)
    n_from_lumens = math.ceil(total_lumens_required / assumed_lumens_per_fixture)

    # Constraint 2: spacing tight enough for uniformity
    max_spacing = max_spacing_to_height_ratio * mount_h
    min_cols_for_spacing = max(1, math.ceil(length / max_spacing))
    min_rows_for_spacing = max(1, math.ceil(width / max_spacing))
    n_from_spacing = min_cols_for_spacing * min_rows_for_spacing

    # Whichever constraint demands more fixtures wins. Grow the grid from
    # the spacing-driven minimum (which already respects the room's aspect
    # ratio) until it also satisfies the lumen-driven count.
    rows, cols = min_rows_for_spacing, min_cols_for_spacing
    while rows * cols < n_from_lumens:
        # grow whichever dimension is proportionally further from the
        # room's real aspect ratio, to keep the grid looking natural
        if (cols / rows) < (length / width):
            cols += 1
        else:
            rows += 1

    n_fixtures = rows * cols
    binding_constraint = "lumens" if n_from_lumens >= n_from_spacing else "spacing/uniformity"

    positions = _lay_out_grid(room, rows, cols, wall_offset_fraction, role, mounting_type)

    return {
        "positions": positions,
        "rows": rows,
        "cols": cols,
        "n_fixtures": n_fixtures,
        "binding_constraint": binding_constraint,
        "n_from_lumens": n_from_lumens,
        "n_from_spacing": n_from_spacing,
        "total_lumens_required": round(total_lumens_required, 1),
        "room_index": round(k, 2),
        "utilization_factor": uf,
        "mounting_height_m": round(mount_h, 3),
        "max_spacing_m": round(max_spacing, 3),
    }


def _lay_out_grid(room, rows, cols, wall_offset_fraction, role, mounting_type):
    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    length = max_x - min_x
    width = max_y - min_y

    cell_w = length / cols
    cell_h = width / rows

    positions = []
    idx = 0
    fixture_z = room.ceiling_height_m - 0.02  # sit slightly below the ceiling plane,
    # not exactly on it -- matches how real recessed fixtures are actually mounted
    # (your real Unit-02 fixtures sat 0.012m below their 2.9m ceiling), and avoids
    # an exact-tie in ray intersection distance between the fixture disc and the
    # ceiling plane itself, which silently made every generated fixture invisible
    # in renders (the ceiling always "won" the tie, however narrowly).
    for r in range(rows):
        for c in range(cols):
            x = min_x + (c + 0.5) * cell_w
            y = min_y + (r + 0.5) * cell_h
            positions.append(LightingPosition(
                position_id=f"gen_{room.room_id}_{idx}",
                room_id=room.room_id,
                x=round(x, 3), y=round(y, 3), z=fixture_z,
                mounting_type=mounting_type,
                role=role,
            ))
            idx += 1
    return positions


if __name__ == "__main__":
    # Sanity check against your REAL TV Room from Unit-02 -- same polygon,
    # ceiling height, and target lux we already validated earlier -- to see
    # whether this proposes something different from the 4 fixtures that
    # were actually modeled.
    room = RoomRequirement(
        room_id="test_tv_room", application="living_room",
        polygon=[(0.115, -6.435), (3.34, -6.435), (3.34, -1.6), (0.115, -1.6)],
        ceiling_height_m=2.9, target_lux=200, cct_k=2700, min_cri=80,
    )
    result = generate_fixture_grid(room)
    print(f"Proposed grid: {result['rows']} rows x {result['cols']} cols = "
          f"{result['n_fixtures']} fixtures")
    print(f"Binding constraint: {result['binding_constraint']}")
    print(f"  (lumens alone would need {result['n_from_lumens']}, "
          f"spacing alone would need {result['n_from_spacing']})")
    print(f"Room index: {result['room_index']}, UF: {result['utilization_factor']}, "
          f"mounting height: {result['mounting_height_m']}m, "
          f"max spacing: {result['max_spacing_m']}m")
    print(f"Total lumens required: {result['total_lumens_required']}")
    print()
    for p in result["positions"]:
        print(p)