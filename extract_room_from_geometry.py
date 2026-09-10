"""
Fallback room extraction for IFC files with NO IfcSpace data -- derives
an approximate room polygon from the floor slab's own geometry instead
of proper room/space boundaries. Built specifically for files like
FATHERBEDROOM_.ifc: bare architectural shell (walls + floor + envelope),
no room classification, no fixture data at all.

Validated: the floor-slab-vs-wall classification heuristic below correctly
and unambiguously identified the single floor slab among 11 unnamed
objects in a real file (20.28 sq m footprint, 0.076m thin, at floor
level -- cleanly separated from 6 wall-like objects and the outer shell).

Since there's no room-type text anywhere in a file like this, you supply
it manually -- often the filename itself is the best hint (e.g.
"FATHERBEDROOM_.ifc" -> bedroom).

Usage: python3 extract_room_from_geometry.py <ifc_file> <room_type>
Example: python3 extract_room_from_geometry.py FATHERBEDROOM_.ifc bedroom

room_type must be a key in requirements_table.py's RESIDENTIAL_REQUIREMENTS.

Output: rooms.json with one room, ZERO positions (that's expected --
placement_generator.py generates positions from scratch anyway, which is
exactly what this kind of fixture-less file needs).
"""

import sys

import ifcopenshell
import ifcopenshell.geom

from position_matcher import RoomRequirement, save_rooms_and_positions
from requirements_table import RESIDENTIAL_REQUIREMENTS


def _convex_hull(points):
    """Same implementation already validated in ifc_extractor.py."""
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _get_xyz(shape):
    verts = shape.geometry.verts
    return verts[0::3], verts[1::3], verts[2::3]


def _classify_objects(model, settings):
    """Same heuristic tested against real data: a floor slab is thin
    vertically with a large horizontal footprint, near z=0. A wall is
    tall (>2m) and thin in one horizontal dimension."""
    proxies = model.by_type("IfcBuildingElementProxy")
    floor_candidates = []
    wall_heights = []

    for p in proxies:
        try:
            shape = ifcopenshell.geom.create_shape(settings, p)
        except RuntimeError:
            continue
        xs, ys, zs = _get_xyz(shape)
        w = max(xs) - min(xs)
        d = max(ys) - min(ys)
        h = max(zs) - min(zs)
        z_bottom = min(zs)
        footprint = w * d

        if h < 0.2 and footprint > 5 and abs(z_bottom) < 0.3:
            floor_candidates.append((p, footprint, list(zip(xs, ys))))
        elif h > 2.0 and min(w, d) < 0.6:
            wall_heights.append(h)

    return floor_candidates, wall_heights


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 extract_room_from_geometry.py <ifc_file> <room_type>")
        print(f"Known room_type values: {list(RESIDENTIAL_REQUIREMENTS.keys())}")
        sys.exit(1)

    ifc_path, room_type = sys.argv[1], sys.argv[2]

    if room_type not in RESIDENTIAL_REQUIREMENTS:
        print(f"'{room_type}' not in requirements_table.py's RESIDENTIAL_REQUIREMENTS.")
        print(f"Known types: {list(RESIDENTIAL_REQUIREMENTS.keys())}")
        sys.exit(1)

    model = ifcopenshell.open(ifc_path)
    settings = ifcopenshell.geom.settings()
    try:
        settings.set(settings.USE_WORLD_COORDS, True)
    except AttributeError:
        settings.set("use-world-coords", True)

    floor_candidates, wall_heights = _classify_objects(model, settings)

    if not floor_candidates:
        print("No floor-slab-like object found (thin, large horizontal footprint, "
              "near floor level). This fallback heuristic doesn't apply to this "
              "file -- room boundaries would need to be defined some other way.")
        sys.exit(1)

    if len(floor_candidates) > 1:
        print(f"Found {len(floor_candidates)} floor-slab-like candidates -- "
              f"using the largest footprint, but verify this is right for a "
              f"multi-room file (this heuristic assumes one room per file).")
    floor_obj, footprint, xy_points = max(floor_candidates, key=lambda c: c[1])
    polygon = _convex_hull(xy_points)

    # The convex hull's TRUE area (shoelace formula) can differ from the
    # simple bounding-box footprint above if the room isn't a plain
    # rectangle. Also: a convex hull can't represent a concave notch or
    # L-shape -- it fills those in -- so if this room genuinely has one,
    # the hull will overestimate its real area. Comparing the two numbers
    # here tells us whether that's a real concern or not.
    hull_area = abs(sum(
        polygon[i][0] * polygon[(i + 1) % len(polygon)][1] -
        polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
        for i in range(len(polygon))
    )) / 2

    print(f"Floor slab: GlobalId={floor_obj.GlobalId}, {len(polygon)}-point polygon")
    print(f"  Bounding-box footprint: {footprint:.2f} sq m")
    print(f"  True polygon (hull) area: {hull_area:.2f} sq m")
    if abs(hull_area - footprint) / footprint > 0.05:
        print(f"  NOTE: these differ by more than 5% -- this room's real shape isn't a "
              f"plain rectangle. The convex hull fills in any concave notches/alcoves, "
              f"so if you know this room has one, the polygon here is an approximation, "
              f"not the exact outline.")
    else:
        print(f"  These are close -- this room is essentially rectangular.")

    if wall_heights:
        ceiling_height = max(wall_heights)
        print(f"Ceiling height estimated from wall geometry: {ceiling_height:.3f}m")
    else:
        ceiling_height = 2.7
        print(f"WARNING: no wall-like objects found to estimate ceiling height -- "
              f"using a generic default of {ceiling_height}m. Verify this manually "
              f"before trusting downstream lumen-method calculations.")

    req = RESIDENTIAL_REQUIREMENTS[room_type]
    room = RoomRequirement(
        room_id=floor_obj.GlobalId, application=req["application"], polygon=polygon,
        ceiling_height_m=ceiling_height, target_lux=req["target_lux"],
        cct_k=req["cct_k"], min_cri=req["min_cri"],
    )

    save_rooms_and_positions([room], [])
    print(f"\nSaved 1 room (0 positions -- expected, run placement_generator.py "
          f"next to generate them from scratch) to rooms.json")
    print(f"Next: python3 run_full_pipeline.py won't work here since it re-reads the "
          f"IFC directly. Use placement_generator.py + the rest of the pipeline "
          f"manually from this rooms.json instead.")


if __name__ == "__main__":
    main()