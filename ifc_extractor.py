"""
Extracts room (IfcSpace) polygons and lighting fixture positions from an
IFC file using IfcOpenShell, converting them into the RoomRequirement /
LightingPosition objects position_matcher.py already expects.

HONESTY NOTE: I could not install or run ifcopenshell in this sandbox
(no network access here), so the ifcopenshell-specific calls below
(open, by_type, create_shape, get_local_placement, get_container) follow
documented, stable API patterns but are NOT verified against a real file
or a real installed version. Two things in particular can differ by
ifcopenshell version and should be checked first:
  - geom.settings(): older versions (0.6.x) use enum-style
    settings.set(settings.USE_WORLD_COORDS, True); newer versions (0.7+)
    use string keys: settings.set("use-world-coords", True). Try both if
    the first one raises an error.
  - Some helper module paths (ifcopenshell.util.element, .placement) have
    been stable for a long time, but confirm they import cleanly for
    whatever version `pip install ifcopenshell` gives you.

The pure-geometry logic (convex hull, role inference from a name string)
IS tested independently in this sandbox and can be trusted.

REQUIRES: pip install ifcopenshell

WHAT'S DIFFERENT FROM THE DXF APPROACH:
  - Room assignment usually comes for (nearly) free: BIM authoring tools
    typically link each fixture to its containing IfcSpace via
    IfcRelContainedInSpatialStructure. _get_containing_space() reads this
    relationship directly -- no point-in-polygon guessing needed, unlike
    the DXF version. If your fixtures aren't linked this way, you'll see
    a warning and need a geometric fallback.
  - Room type often comes from IfcSpace.Name / LongName directly, instead
    of guessing from a layer-naming convention.

ASSUMPTIONS TO VERIFY AGAINST YOUR REAL FILE (run inspect_file() first):
  - Fixtures were authored as IfcLightFixture entities. Some BIM tools
    export them as generic IfcFlowTerminal or IfcBuildingElementProxy
    with a type/classification instead -- if extract_positions() returns
    nothing, check inspect_file()'s output and adjust the by_type() call.
  - Each IfcSpace has a usable Name or LongName. If not filled in
    consistently, replace _infer_room_type() with a manual
    {room_guid: room_type} mapping you maintain by hand.
  - Room footprints here are taken as the convex hull of the space's 3D
    geometry projected to the XY plane -- fine for area/room-index
    estimates, but an L-shaped or non-convex room will come back as its
    convex hull, not its true outline. Flag this if your rooms aren't
    simple rectangles.
"""

import re

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.geom

from position_matcher import RoomRequirement, LightingPosition


def _safe_by_type(model, entity_type):
    """Some entity types don't exist in older IFC schemas -- IfcLightFixture
    is an IFC4+ addition, not valid in IFC2X3, and querying for it there
    crashes with a RuntimeError rather than just returning nothing. Confirmed
    against a real IFC2X3 file: this returns an empty list instead of
    crashing, so schema-version differences degrade gracefully instead of
    stopping the whole script."""
    try:
        return model.by_type(entity_type)
    except RuntimeError:
        return []


def inspect_file(ifc_path: str):
    """Run this FIRST against your real file to see what's actually in it."""
    model = ifcopenshell.open(ifc_path)
    print(f"IFC schema version: {model.schema}")
    for entity_type in ("IfcSpace", "IfcLightFixture", "IfcFlowTerminal", "IfcBuildingElementProxy"):
        entities = _safe_by_type(model, entity_type)
        print(f"{entity_type}: {len(entities)} found")
        for e in entities[:3]:
            print(f"  - GlobalId={e.GlobalId}, Name={getattr(e, 'Name', None)}, "
                  f"LongName={getattr(e, 'LongName', None)}, "
                  f"ObjectType={getattr(e, 'ObjectType', None)}")


def extract_rooms(ifc_path: str, requirements_by_room_type: dict, skip_room_types: dict = None) -> list:
    """
    requirements_by_room_type: e.g.
      {"conference_room": {"application": "conference_room", "target_lux": 500,
                            "cct_k": 4000, "min_cri": 80, "ceiling_height_m": 3.0}}
    skip_room_types: {room_type: reason_string} -- rooms whose type matches a
      key here are deliberately excluded (utility spaces, outdoor areas, etc.)
      and print an INFO line instead of a WARNING.
    """
    skip_room_types = skip_room_types or {}
    model = ifcopenshell.open(ifc_path)
    settings = ifcopenshell.geom.settings()
    try:
        settings.set(settings.USE_WORLD_COORDS, True)   # older ifcopenshell API
    except AttributeError:
        settings.set("use-world-coords", True)          # newer ifcopenshell API

    rooms = []
    for space in model.by_type("IfcSpace"):
        room_type = _infer_room_type(space)

        if room_type in skip_room_types:
            print(f"INFO: skipping space '{space.Name}' (type '{room_type}') -- "
                  f"{skip_room_types[room_type]}")
            continue

        req = requirements_by_room_type.get(room_type)
        if req is None:
            print(f"WARNING: no requirements entry for room type '{room_type}' "
                  f"(space {space.GlobalId}, name={space.Name}) -- skipping.")
            continue

        polygon, measured_height = _get_space_footprint_and_height(space, settings)
        if polygon is None or len(polygon) < 3:
            print(f"WARNING: couldn't extract a usable footprint for space "
                  f"{space.GlobalId} -- skipping.")
            continue

        # Prefer the height actually measured from this room's geometry over
        # the requirements table's guess -- real data showed the guessed
        # per-room-type values (2.4-2.7m) didn't match what the model's
        # fixtures were actually mounted at (a consistent 2.888m across every
        # room), so trust the model over the table whenever it looks sane.
        ceiling_height = measured_height if measured_height and measured_height > 1.5 \
            else req.get("ceiling_height_m", 3.0)
        if measured_height and abs(measured_height - req.get("ceiling_height_m", 3.0)) > 0.15:
            print(f"INFO: room '{space.Name}' measured ceiling height "
                  f"({measured_height:.3f}m) differs from the table default "
                  f"({req.get('ceiling_height_m', 3.0)}m) -- using the measured value.")

        rooms.append(RoomRequirement(
            room_id=space.GlobalId,
            application=req["application"],
            polygon=polygon,
            ceiling_height_m=ceiling_height,
            target_lux=req["target_lux"],
            cct_k=req["cct_k"],
            min_cri=req["min_cri"],
        ))
    return rooms


def _infer_room_type(space) -> str:
    """Adjust to however your models actually name/classify spaces.
    Strips a trailing room number (e.g. "Bedroom 2" -> "bedroom") so
    multiple instances of the same room type share one requirements-table
    entry, while each still keeps its own GlobalId for area/position purposes."""
    label = space.LongName or space.Name or ""
    label = label.strip().lower().replace(" ", "_")
    label = re.sub(r"_\d+$", "", label)
    return label


def _get_space_footprint_and_height(space, settings):
    """2D (x, y) footprint as the convex hull of the space's projected
    3D vertices, plus the measured floor-to-ceiling height (max z - min z
    of the space's own geometry). See the non-convex-room caveat in the
    module docstring re: the footprint being a hull, not the exact outline."""
    try:
        shape = ifcopenshell.geom.create_shape(settings, space)
    except RuntimeError:
        return None, None
    verts = shape.geometry.verts  # flat list: x1,y1,z1,x2,y2,z2,...
    points_xy = [(verts[i], verts[i + 1]) for i in range(0, len(verts), 3)]
    zs = [verts[i + 2] for i in range(0, len(verts), 3)]
    polygon = _convex_hull(points_xy)
    height = (max(zs) - min(zs)) if zs else None
    return polygon, height


def _convex_hull(points):
    """Tested independently in this sandbox -- trustworthy."""
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


def extract_positions(ifc_path: str, rooms: list) -> list:
    model = ifcopenshell.open(ifc_path)
    room_ids = {r.room_id for r in rooms}
    positions = []

    fixtures = _safe_by_type(model, "IfcLightFixture")
    if not fixtures:
        # IfcLightFixture doesn't exist at all in IFC2X3 (confirmed against
        # a real file) -- older-schema files typically represent fixtures as
        # a generic IfcFlowTerminal or IfcBuildingElementProxy instead, with
        # the fixture-ness only identifiable from the Name/ObjectType text.
        # Filter for "light" as a reasonable starting heuristic; adjust to
        # match what inspect_file() actually shows for your file's naming.
        print("No IfcLightFixture entities (may not exist in this file's schema -- "
              "IfcLightFixture is IFC4+ only). Falling back to IfcFlowTerminal/"
              "IfcBuildingElementProxy entities whose Name mentions 'light'.")
        candidates = _safe_by_type(model, "IfcFlowTerminal") + _safe_by_type(model, "IfcBuildingElementProxy")
        fixtures = [c for c in candidates if "light" in (c.Name or "").lower()]
        print(f"Found {len(fixtures)} fallback candidate(s) this way -- verify these "
              f"are really light fixtures and not, say, light switches or other "
              f"'light'-named non-fixture elements, then adjust the filter if needed.")

    for fixture in fixtures:
        role, mounting_type, include = _classify_fixture(fixture)
        if not include:
            print(f"INFO: skipping fixture {fixture.GlobalId} ('{fixture.Name}') -- "
                  f"classified as portable/furniture, not part of automated "
                  f"catalog matching. Remove it from FIXTURE_CLASSIFICATION_RULES "
                  f"if you want these selected automatically too.")
            continue

        x, y, z = _get_position(fixture)
        room_id = _get_containing_space(fixture, room_ids)

        if room_id is None:
            print(f"WARNING: fixture {fixture.GlobalId} isn't linked to any "
                  f"extracted room via IfcRelContainedInSpatialStructure -- "
                  f"skipping. May need a geometric (point-in-polygon) fallback.")
            continue

        positions.append(LightingPosition(
            position_id=fixture.GlobalId,
            room_id=room_id,
            x=x, y=y, z=z,
            mounting_type=mounting_type,
            role=role,
        ))
    return positions


def _get_position(fixture):
    matrix = ifcopenshell.util.placement.get_local_placement(fixture.ObjectPlacement)
    return matrix[0][3], matrix[1][3], matrix[2][3]


def _get_containing_space(element, valid_room_ids):
    """Walks IfcRelContainedInSpatialStructure -- the relationship BIM tools
    set directly, so unlike DXF you usually don't need point-in-polygon at all."""
    container = ifcopenshell.util.element.get_container(element)
    if container is not None and container.GlobalId in valid_room_ids:
        return container.GlobalId
    return None


FIXTURE_CLASSIFICATION_RULES = [
    # (keyword, role, mounting_type, include_in_automated_matching)
    # Order matters: more specific keywords should come before generic ones
    # that might also match (e.g. "track" before "spot").
    ("floor lamp", "decorative_portable", "floor_standing", False),
    ("table lamp", "decorative_portable", "surface_mount", False),
    ("wall wash", "wall_wash", "recessed_ceiling", True),
    ("track", "accent", "track", True),
    ("downlight", "ambient", "recessed_ceiling", True),
    ("spot", "accent", "recessed_ceiling", True),
    ("pendant", "ambient", "pendant", True),
]


def _classify_fixture(fixture):
    """Classifies role/mounting from the fixture's Name (and ObjectType as a
    secondary signal, for files where it's actually filled in). Tested
    independently in this sandbox against real fixture names -- trustworthy.
    Add rules as you encounter new fixture naming patterns in your files."""
    text = f"{fixture.Name or ''} {fixture.ObjectType or ''}".lower()
    for keyword, role, mounting, include in FIXTURE_CLASSIFICATION_RULES:
        if keyword in text:
            return role, mounting, include
    return "ambient", "recessed_ceiling", True  # default fallback


if __name__ == "__main__":
    import sys
    from requirements_table import RESIDENTIAL_REQUIREMENTS, SKIP_ROOM_TYPES
    from position_matcher import save_rooms_and_positions

    if len(sys.argv) < 2:
        print("Usage: python3 ifc_extractor.py your_file.ifc")
        sys.exit(1)

    print("--- Inspecting file structure first ---")
    inspect_file(sys.argv[1])

    print("\n--- Extracting rooms and positions ---")
    rooms = extract_rooms(sys.argv[1], RESIDENTIAL_REQUIREMENTS, SKIP_ROOM_TYPES)
    positions = extract_positions(sys.argv[1], rooms)
    print(f"Extracted {len(rooms)} rooms and {len(positions)} fixture positions.")
    for r in rooms:
        print(r)
    for p in positions:
        print(p)

    save_rooms_and_positions(rooms, positions)
    print("\nSaved to rooms.json and positions.json -- run_project.py will use these "
          "directly without needing to re-parse the IFC file.")