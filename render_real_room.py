"""
Renders your REAL TV Room from Unit-02: real room dimensions (from the
IFC extraction), real fixture positions (4 downlights, as actually
modeled), and the real product that was actually matched to them by
run_project.py (R522_D85P / r522-d8_d85p.ies). Every input here traces
back to something we validated earlier in the pipeline -- nothing is a
placeholder.

Generalizes minimal_raytracer.py in two ways:
  1. Arbitrary room dimensions (not a hardcoded 4x4x3 box)
  2. Multiple lights, each with its own real IES data and position --
     direct illumination from each light is summed at every surface point

Still direct-illumination only (no bounce/global illumination yet --
that's still the next real step after this).

Usage: python3 render_real_room.py
Outputs: render_real_room.png
"""

import math
import numpy as np
from PIL import Image

from ies_parser import parse_ies_file

# ---------- Real room geometry, from the actual Unit-02 IFC extraction ----------
# Original polygon: [(0.115, -6.435), (3.34, -6.435), (3.34, -1.6), (0.115, -1.6)]
# Translated to a local 0,0-origin frame for the renderer.
ROOM_WIDTH = 3.34 - 0.115    # 3.225 m
ROOM_DEPTH = -1.6 - (-6.435)  # 4.835 m
ROOM_HEIGHT = 2.9             # measured ceiling height, validated earlier

WALL_ALBEDO = 0.5
FLOOR_ALBEDO = 0.3
CEILING_ALBEDO = 0.7

# The lights have been pure math (a position + a candela function) with no
# physical geometry -- no ray could ever hit "the fixture," only compute its
# effect on other surfaces. This gives each light a small emissive disc (its
# lens/aperture) so it's actually visible, using the rendering equation's
# emitted-radiance term (L_e) from math_reference.pdf Section 2.1 -- every
# surface so far has had L_e = 0; fixtures are the first surface that doesn't.
FIXTURE_DISC_RADIUS = 0.045   # metres, a plausible small downlight aperture
FIXTURE_EMITTED_RADIANCE = 500.0  # must be well above any diffuse surface's
# radiance to actually read as "the light source" rather than blend in --
# 8.0 (first attempt) was dimmer than some directly-lit wall points (~14-90
# in this scene), which is why it never visibly stood out despite the
# ray-hit detection working correctly the whole time.


def ray_disc_intersect(origin, direction, disc_center, disc_normal, radius):
    """Ray-disc intersection: first solve ray-plane, then check the hit
    point falls within `radius` of the disc center."""
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


def load_ies_light(path, position):
    data = parse_ies_file(path)
    return {
        "position": np.array(position),
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


def ray_box_intersect(origin, direction, width, depth, height):
    best_t = None
    best_normal = None
    best_surface = None

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
    """Handles the degenerate case where forward is parallel to the
    preferred up vector (straight-down or straight-up views) -- naive
    cross(forward, up) would be a zero vector there, so swap to a
    different reference axis when that happens."""
    forward = forward / np.linalg.norm(forward)
    preferred_up = np.array(preferred_up, dtype=float)
    if abs(np.dot(forward, preferred_up)) > 0.999:
        preferred_up = np.array([0, 1, 0]) if abs(preferred_up[2]) > 0.9 else np.array([0, 0, 1])
    right = np.cross(forward, preferred_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return right, up


VIEWS = {
    "corner": {
        "cam_pos": (ROOM_WIDTH * 0.1, ROOM_DEPTH * 0.1, 1.5),
        "look_at": (ROOM_WIDTH * 0.6, ROOM_DEPTH * 0.85, 1.0),
        "fov_deg": 75,
    },
    "top": {
        "cam_pos": (ROOM_WIDTH / 2, ROOM_DEPTH / 2, ROOM_HEIGHT - 0.05),
        "look_at": (ROOM_WIDTH / 2, ROOM_DEPTH / 2, 0.0),
        "fov_deg": 100,
    },
    "bottom": {
        "cam_pos": (ROOM_WIDTH / 2, ROOM_DEPTH / 2, 0.1),
        "look_at": (ROOM_WIDTH / 2, ROOM_DEPTH / 2, ROOM_HEIGHT),
        "fov_deg": 55,
    },
    "bottom_worms_eye": {
        # Straight-up is honestly correct but pure black (see the writeup --
        # recessed downlights emit ~0 upward). This low-angle "worm's eye"
        # shot is the more genuinely useful low-camera view.
        "cam_pos": (ROOM_WIDTH * 0.15, ROOM_DEPTH * 0.15, 0.15),
        "look_at": (ROOM_WIDTH * 0.7, ROOM_DEPTH * 0.7, ROOM_HEIGHT),
        "fov_deg": 85,
    },
    "side": {
        "cam_pos": (0.1, ROOM_DEPTH / 2, ROOM_HEIGHT / 2),
        "look_at": (ROOM_WIDTH, ROOM_DEPTH / 2, ROOM_HEIGHT / 2),
        "fov_deg": 80,
    },
    "front": {
        "cam_pos": (ROOM_WIDTH / 2, 0.1, ROOM_HEIGHT / 2),
        "look_at": (ROOM_WIDTH / 2, ROOM_DEPTH, ROOM_HEIGHT / 2),
        "fov_deg": 80,
    },
}


def _trace_ray(cam_pos, ray_dir, lights, albedo_by_surface):
    """Traces one ray, returns its radiance. Extracted so render() can call
    this multiple times per pixel with jittered sub-pixel directions
    (supersampling) -- needed because the fixture discs are only ~4 pixels
    across; a single sample per pixel unreliably missed them entirely in
    testing, a classic small-feature aliasing problem in ray tracing."""
    hit = ray_box_intersect(cam_pos, ray_dir, ROOM_WIDTH, ROOM_DEPTH, ROOM_HEIGHT)
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


def render(lights, cam_pos, look_at, fov_deg=75, width_px=320, height_px=240,
           out_path="render.png", supersample=2):
    cam_pos = np.array(cam_pos, dtype=float)
    look_at = np.array(look_at, dtype=float)
    forward = look_at - cam_pos
    right, up = _compute_camera_basis(forward)
    forward = forward / np.linalg.norm(forward)

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
                    radiance_sum += _trace_ray(cam_pos, ray_dir, lights, albedo_by_surface)

            avg_radiance = radiance_sum / (supersample * supersample)
            image[py, px] = [avg_radiance, avg_radiance, avg_radiance]

    mapped = _reinhard_photographic_tone_map(image, key=0.18)
    gamma_corrected = np.power(np.clip(mapped, 0, 1), 1 / 2.2)
    out_img = (gamma_corrected * 255).astype(np.uint8)

    Image.fromarray(out_img, mode="RGB").save(out_path)
    print(f"Rendered {width_px}x{height_px} ({supersample}x{supersample} supersampled) -> {out_path}")


def _reinhard_photographic_tone_map(image, key=0.18):
    """Naive L/(L+1) Reinhard has no exposure calibration -- any radiance
    above ~5-10 already saturates near white. The fix: compute the scene's
    log-average luminance, scale so it maps to a target "key" value (0.18,
    the standard photographic middle-gray convention), THEN apply the
    local L/(L+1) operator (Reinhard et al. 2002).

    One further refinement, found by testing the worm's-eye view: a scene
    that's ~50% genuinely, correctly black (the recessed downlights emit
    ~0 upward, so a ceiling-heavy frame is legitimately near-total black)
    skews the log-average down and over-brightens the rest of the frame --
    the same failure mode a real camera's auto-exposure has pointed at a
    mostly-dark scene with one bright area. Excluding near-zero pixels from
    the key calculation (computing exposure for the visible/lit content,
    not diluted by legitimately-black regions) fixes this."""
    luminance = image.mean(axis=2)
    epsilon = 1e-6
    visible = luminance[luminance > 0.01]
    if visible.size == 0:
        return image / (image + 1.0)
    log_avg = np.exp(np.mean(np.log(visible + epsilon)))
    scaled = image * (key / log_avg)
    return scaled / (scaled + 1.0)


if __name__ == "__main__":
    # Real fixture positions from the Unit-02 IFC extraction, translated
    # into this renderer's local room frame (origin subtracted):
    #   real (1.005, -2.495) -> local (0.89, 3.94)
    #   real (2.655, -2.495) -> local (2.54, 3.94)
    #   real (1.005, -5.345) -> local (0.89, 1.09)
    #   real (2.655, -5.345) -> local (2.54, 1.09)
    # z=2.888 in both frames (height isn't translated)
    real_positions = [
        (0.89, 3.94, 2.888),
        (2.54, 3.94, 2.888),
        (0.89, 1.09, 2.888),
        (2.54, 1.09, 2.888),
    ]

    lights = [load_ies_light("r522-d8_d85p.ies", pos) for pos in real_positions]
    print(f"{len(lights)} real light sources loaded:")
    for light in lights:
        print(f"  {light['source_file']}: {light['total_lumens']:.0f} lm at {tuple(light['position'])}")
    print()

    for view_name, view in VIEWS.items():
        render(lights, view["cam_pos"], view["look_at"], view["fov_deg"],
               out_path=f"render_real_room_{view_name}.png")