"""
A 3D false-color illuminance map -- what DIALux calls "false color
rendering": the room's actual 3D surfaces (walls, floor, ceiling) colored
by real computed lux value, viewed from a real camera angle, not a flat
2D plan like generate_lux_heatmap.py produces.

Key difference from the normal photorealistic renderer: that one computes
radiance = illuminance * (albedo / pi) -- how bright a surface LOOKS,
factoring in its own reflectance. This computes raw illuminance only --
how much light ARRIVES at each point, independent of surface color --
then maps that value through a false-color scale, exactly matching what
a lux meter would read at each point, not what a camera would see.

Usage: python3 render_lux_map_3d.py <room_id> [view]
Default view is full_room. Output: luxmap3d_<room_id>_<view>.png
"""

import sys
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.pyplot as plt

from render_from_ifc import (
    build_scene_from_real_data, ray_box_intersect, ray_disc_intersect,
    candela_at_direction, _compute_camera_basis, get_full_room_view, get_views,
    FIXTURE_DISC_RADIUS,
)


def compute_illuminance_frame(lights, cam_pos, look_at, width, depth, height,
                                fov_deg=100, width_px=320, height_px=240):
    """Same ray-tracing walk as render(), but returns raw illuminance per
    pixel (a 2D array of lux values) instead of a tone-mapped image --
    the false-color mapping happens afterward, separately, so the actual
    lux scale stays interpretable rather than baked into brightness."""
    cam_pos = np.array(cam_pos, dtype=float)
    look_at = np.array(look_at, dtype=float)
    forward_raw = look_at - cam_pos
    right, up = _compute_camera_basis(forward_raw)
    forward = forward_raw / np.linalg.norm(forward_raw)

    fov = math.radians(fov_deg)
    aspect = width_px / height_px
    illuminance_grid = np.zeros((height_px, width_px))
    is_fixture = np.zeros((height_px, width_px), dtype=bool)

    for py in range(height_px):
        ndc_y = (0.5 - (py + 0.5) / height_px) * math.tan(fov / 2)
        for px in range(width_px):
            ndc_x = ((px + 0.5) / width_px - 0.5) * math.tan(fov / 2) * aspect
            ray_dir = forward + ndc_x * right + ndc_y * up
            ray_dir /= np.linalg.norm(ray_dir)

            hit = ray_box_intersect(cam_pos, ray_dir, width, depth, height)
            if hit is None:
                continue
            t, point, normal, surf_type = hit

            closest_fixture_t = None
            for light in lights:
                disc_normal = np.array([0, 0, -1])
                ft = ray_disc_intersect(cam_pos, ray_dir, light["position"], disc_normal, FIXTURE_DISC_RADIUS)
                if ft is not None and ft < t and (closest_fixture_t is None or ft < closest_fixture_t):
                    closest_fixture_t = ft
            if closest_fixture_t is not None:
                is_fixture[py, px] = True
                continue

            total_illuminance = 0.0
            for light in lights:
                to_light = light["position"] - point
                dist = np.linalg.norm(to_light)
                to_light_unit = to_light / dist
                direction_from_light = -to_light_unit
                candela = candela_at_direction(light, direction_from_light)
                cos_incidence = max(0.0, np.dot(normal, to_light_unit))
                total_illuminance += (candela * cos_incidence) / (dist ** 2)
            illuminance_grid[py, px] = total_illuminance

    return illuminance_grid, is_fixture


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 render_lux_map_3d.py <room_id> [view]")
        sys.exit(1)
    room_id = sys.argv[1]
    view_name = sys.argv[2] if len(sys.argv) > 2 else "full_room"

    width, depth, height, lights = build_scene_from_real_data(room_id)
    if not lights:
        print("No lights matched for this room -- check catalog.json coverage.")
        sys.exit(1)

    print(f"Room: {width:.2f} x {depth:.2f} x {height:.2f}m, {len(lights)} real light(s)")

    if view_name == "full_room":
        v = get_full_room_view(width, depth, height)
    else:
        views = get_views(width, depth, height)
        v = views.get(view_name, get_full_room_view(width, depth, height))

    # Many-light scenes are slow at high resolution (tested: 72 lights at
    # full res + supersample took 5+ minutes) -- this computes illuminance
    # once per pixel with no supersampling, same lesson applied here.
    width_px, height_px = (320, 240) if len(lights) < 30 else (200, 150)
    print(f"Computing illuminance per pixel ({width_px}x{height_px}, "
          f"no supersampling -- {len(lights)} lights makes this the right tradeoff)...")

    illuminance_grid, is_fixture = compute_illuminance_frame(
        lights, v["cam_pos"], v["look_at"], width, depth, height,
        fov_deg=v["fov_deg"], width_px=width_px, height_px=height_px)

    valid = illuminance_grid[~is_fixture]
    valid = valid[valid > 0]
    vmax = np.percentile(valid, 98) if valid.size else 1.0  # robust to a few
    # extremely bright near-fixture pixels dominating the color scale

    cmap = matplotlib.colormaps["jet"]  # blue (low) -> red (high), the classic
    # false-color convention DIALux and most lighting software use
    normalized = np.clip(illuminance_grid / vmax, 0, 1)
    rgb = (cmap(normalized)[:, :, :3] * 255).astype(np.uint8)
    rgb[is_fixture] = [255, 255, 255]  # fixtures themselves shown as white

    fig, ax = plt.subplots(figsize=(10, 10 * height_px / width_px))
    ax.imshow(rgb)
    ax.axis("off")

    sm = cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=vmax))
    cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Illuminance (lux)")

    avg_lux = valid.mean() if valid.size else 0
    ax.set_title(f"False-color illuminance -- {view_name} view -- avg {avg_lux:.0f} lux "
                 f"(scale capped at {vmax:.0f} lux, 98th percentile)")

    out_path = f"luxmap3d_{room_id[:8]}_{view_name}.png"
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
