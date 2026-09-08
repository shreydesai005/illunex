"""
Renders a room using REAL data from your actual pipeline output, not
hardcoded/manually-transcribed values:
  - rooms.json / positions.json  -- from ifc_extractor.py against a real IFC
  - catalog.json                 -- your completed catalog (real products)
  - the actual product each position was matched to, via
    position_matcher.match_positions_to_catalog() -- the SAME matching
    logic run_project.py uses, so the render reflects real selections,
    not a hardcoded assumption that every fixture is the same product

This replaces render_real_room.py's hardcoded ROOM_WIDTH/DEPTH/HEIGHT
globals with per-room values computed from the room's actual polygon and
ceiling height -- works for any room in any IFC file, not just one.

Requires each catalog product to have a real .ies file on disk, named
exactly as recorded in that product's "source_ies_file" field (as
build_catalog.py produces).

Usage: python3 render_from_ifc.py <room_id> [--views corner,front,top,...]
"""

import sys
import math
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ies_parser import parse_ies_file
from position_matcher import load_rooms, load_positions, match_positions_to_catalog


def load_ies_light(path, position):
    data = parse_ies_file(path)
    return {
        "position": np.array(position, dtype=float),
        "vertical_angles": np.array(data["vertical_angles"]),
        "horizontal_angles": np.array(data["horizontal_angles"]),
        "candela_values": np.array(data["candela_values"]),
        "total_lumens": data["total_lumens"],
        "source_file": path,
    }


def candela_at_direction(light, direction_from_light):
    down = np.array([0, 0, -1])
    cos_angle = np.clip(np.dot(direction_from_light, down), -1, 1)
    vertical_angle_deg = math.degrees(math.acos(cos_angle))
    v_angles = light["vertical_angles"]
    plane = light["candela_values"][0]
    if vertical_angle_deg >= v_angles[-1]:
        return 0.0
    return float(np.interp(vertical_angle_deg, v_angles, plane))


def ray_disc_intersect(origin, direction, disc_center, disc_normal, radius):
    denom = np.dot(direction, disc_normal)
    if abs(denom) < 1e-9:
        return None
    t = np.dot(disc_center - origin, disc_normal) / denom
    if t <= 1e-6:
        return None
    point = origin + t * direction
    if np.linalg.norm(point - disc_center) > radius:
        return None
    return t


def ray_box_intersect(origin, direction, width, depth, height):
    best_t, best_normal, best_surface = None, None, None
    planes = [
        (0.0, np.array([1, 0, 0]), "wall", lambda p: 0 <= p[1] <= depth and 0 <= p[2] <= height),
        (width, np.array([-1, 0, 0]), "wall", lambda p: 0 <= p[1] <= depth and 0 <= p[2] <= height),
        (0.0, np.array([0, 1, 0]), "wall", lambda p: 0 <= p[0] <= width and 0 <= p[2] <= height),
        (depth, np.array([0, -1, 0]), "wall", lambda p: 0 <= p[0] <= width and 0 <= p[2] <= height),
        (0.0, np.array([0, 0, 1]), "floor", lambda p: 0 <= p[0] <= width and 0 <= p[1] <= depth),
        (height, np.array([0, 0, -1]), "ceiling", lambda p: 0 <= p[0] <= width and 0 <= p[1] <= depth),
    ]
    axis_map = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2}
    for i, (coord, normal, surf_type, in_bounds) in enumerate(planes):
        axis = axis_map[i]
        if abs(direction[axis]) < 1e-9:
            continue
        t = (coord - origin[axis]) / direction[axis]
        if t <= 1e-6:
            continue
        point = origin + t * direction
        if not in_bounds(point):
            continue
        if best_t is None or t < best_t:
            best_t, best_normal, best_surface = t, normal, surf_type
    if best_t is None:
        return None
    return best_t, origin + best_t * direction, best_normal, best_surface


def _compute_camera_basis(forward, preferred_up=(0, 0, 1)):
    forward = forward / np.linalg.norm(forward)
    preferred_up = np.array(preferred_up, dtype=float)
    if abs(np.dot(forward, preferred_up)) > 0.999:
        preferred_up = np.array([0, 1, 0]) if abs(preferred_up[2]) > 0.9 else np.array([0, 0, 1])
    right = np.cross(forward, preferred_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return right, up


def _reinhard_photographic_tone_map(image, key=0.18):
    luminance = image.mean(axis=2)
    epsilon = 1e-6
    visible = luminance[luminance > 0.01]
    if visible.size == 0:
        return image / (image + 1.0)
    log_avg = np.exp(np.mean(np.log(visible + epsilon)))
    scaled = image * (key / log_avg)
    return scaled / (scaled + 1.0)


FIXTURE_DISC_RADIUS = 0.045
FIXTURE_EMITTED_RADIANCE = 500.0
WALL_ALBEDO, FLOOR_ALBEDO, CEILING_ALBEDO = 0.5, 0.3, 0.7


def _trace_ray(cam_pos, ray_dir, lights, albedo_by_surface, width, depth, height):
    hit = ray_box_intersect(cam_pos, ray_dir, width, depth, height)
    if hit is None:
        return 0.0
    t, point, normal, surf_type = hit

    closest_fixture_t = None
    for light in lights:
        disc_normal = np.array([0, 0, -1])
        ft = ray_disc_intersect(cam_pos, ray_dir, light["position"], disc_normal, FIXTURE_DISC_RADIUS)
        if ft is not None and ft < t and (closest_fixture_t is None or ft < closest_fixture_t):
            closest_fixture_t = ft
    if closest_fixture_t is not None:
        return FIXTURE_EMITTED_RADIANCE

    albedo = albedo_by_surface[surf_type]
    total_radiance = 0.0
    for light in lights:
        to_light = light["position"] - point
        dist = np.linalg.norm(to_light)
        to_light_unit = to_light / dist
        direction_from_light = -to_light_unit
        candela = candela_at_direction(light, direction_from_light)
        cos_incidence = max(0.0, np.dot(normal, to_light_unit))
        illuminance = (candela * cos_incidence) / (dist ** 2)
        total_radiance += illuminance * (albedo / math.pi)
    return total_radiance


def render(lights, cam_pos, look_at, width, depth, height, fov_deg=75,
           width_px=320, height_px=240, out_path="render.png", supersample=2):
    cam_pos = np.array(cam_pos, dtype=float)
    look_at = np.array(look_at, dtype=float)
    forward_raw = look_at - cam_pos
    right, up = _compute_camera_basis(forward_raw)
    forward = forward_raw / np.linalg.norm(forward_raw)

    fov = math.radians(fov_deg)
    aspect = width_px / height_px
    image = np.zeros((height_px, width_px, 3), dtype=np.float32)
    albedo_by_surface = {"wall": WALL_ALBEDO, "floor": FLOOR_ALBEDO, "ceiling": CEILING_ALBEDO}
    offsets = [(i + 0.5) / supersample for i in range(supersample)]

    for py in range(height_px):
        for px in range(width_px):
            radiance_sum = 0.0
            for oy in offsets:
                ndc_y = (0.5 - (py + oy) / height_px) * math.tan(fov / 2)
                for ox in offsets:
                    ndc_x = ((px + ox) / width_px - 0.5) * math.tan(fov / 2) * aspect
                    ray_dir = forward + ndc_x * right + ndc_y * up
                    ray_dir /= np.linalg.norm(ray_dir)
                    radiance_sum += _trace_ray(cam_pos, ray_dir, lights, albedo_by_surface,
                                                width, depth, height)
            avg = radiance_sum / (supersample * supersample)
            image[py, px] = [avg, avg, avg]

    mapped = _reinhard_photographic_tone_map(image, key=0.18)
    gamma_corrected = np.power(np.clip(mapped, 0, 1), 1 / 2.2)
    out_img = (gamma_corrected * 255).astype(np.uint8)
    Image.fromarray(out_img, mode="RGB").save(out_path)
    print(f"Rendered -> {out_path}")


def build_scene_from_real_data(room_id, rooms_path="rooms.json", positions_path="positions.json",
                                 catalog_path="catalog.json"):
    """Returns (width, depth, height, lights) for the given room, using the
    ACTUAL fixture selection from match_positions_to_catalog() -- not a
    hardcoded assumption about which product is where."""
    rooms = load_rooms(rooms_path)
    positions = load_positions(positions_path)
    with open(catalog_path) as f:
        catalog_full = json.load(f)
    catalog = [c for c in catalog_full if c.get("include_in_automated_matching", True)]

    room = next((r for r in rooms if r.room_id == room_id), None)
    if room is None:
        raise ValueError(f"Room '{room_id}' not found in {rooms_path}")

    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    min_x, min_y = min(xs), min(ys)
    width = max(xs) - min_x
    depth = max(ys) - min_y
    height = room.ceiling_height_m

    room_positions = [p for p in positions if p.room_id == room_id]
    results = match_positions_to_catalog(rooms, positions, catalog)

    lights = []
    skipped = []
    for pos in room_positions:
        match = results.get(pos.position_id)
        product = match["product"] if match else None
        if product is None:
            skipped.append(pos.position_id)
            continue
        ies_file = product.get("source_ies_file")
        if not ies_file or not Path(ies_file).exists():
            skipped.append(f"{pos.position_id} (product {product.get('product_id')}: "
                            f"no .ies file found at '{ies_file}')")
            continue
        local_pos = (pos.x - min_x, pos.y - min_y, pos.z)
        lights.append(load_ies_light(ies_file, local_pos))

    if skipped:
        print(f"WARNING: {len(skipped)} position(s) not rendered (no match or missing "
              f"IES file): {skipped}")

    return width, depth, height, lights


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 render_from_ifc.py <room_id> [view1,view2,...]")
        print("Available views: corner, top, bottom, bottom_worms_eye, side, front")
        sys.exit(1)

    room_id = sys.argv[1]
    requested_views = sys.argv[2].split(",") if len(sys.argv) > 2 else \
        ["corner", "front", "top", "bottom_worms_eye"]

    try:
        width, depth, height, lights = build_scene_from_real_data(room_id)
    except ValueError as e:
        print(f"ERROR: {e}")
        print("Tip: check the room_id values printed by ifc_extractor.py, or open "
              "rooms.json and look at each room's \"room_id\" field.")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: missing {e.filename} -- run ifc_extractor.py first, and make "
              f"sure catalog.json exists (see build_catalog.py / fill_catalog_todos.py).")
        sys.exit(1)
    print(f"Room '{room_id}': {width:.2f}m x {depth:.2f}m x {height:.2f}m, "
          f"{len(lights)} real light(s) with real matched products")
    for light in lights:
        print(f"  {light['source_file']}: {light['total_lumens']:.0f} lm")

    if not lights:
        print("No lights to render -- check the warnings above.")
        return

    views = {
        "corner": {"cam_pos": (width * 0.1, depth * 0.1, 1.5),
                   "look_at": (width * 0.6, depth * 0.85, 1.0), "fov_deg": 75},
        "top": {"cam_pos": (width / 2, depth / 2, height - 0.05),
                "look_at": (width / 2, depth / 2, 0.0), "fov_deg": 100},
        "bottom": {"cam_pos": (width / 2, depth / 2, 0.1),
                   "look_at": (width / 2, depth / 2, height), "fov_deg": 55},
        "bottom_worms_eye": {"cam_pos": (width * 0.15, depth * 0.15, 0.15),
                              "look_at": (width * 0.7, depth * 0.7, height), "fov_deg": 85},
        "side": {"cam_pos": (0.1, depth / 2, height / 2),
                 "look_at": (width, depth / 2, height / 2), "fov_deg": 80},
        "front": {"cam_pos": (width / 2, 0.1, height / 2),
                  "look_at": (width / 2, depth, height / 2), "fov_deg": 80},
    }

    for view_name in requested_views:
        if view_name not in views:
            print(f"Unknown view '{view_name}', skipping.")
            continue
        v = views[view_name]
        render(lights, v["cam_pos"], v["look_at"], width, depth, height,
               fov_deg=v["fov_deg"], out_path=f"render_{room_id[:8]}_{view_name}.png")


if __name__ == "__main__":
    main()
