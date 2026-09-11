"""
Generates an illuminance (lux) heat map for a room -- a top-down colored
map showing exactly how bright each point on the work plane is, computed
from real matched fixture positions and real IES candela data. This is
the point-by-point photometric calculation (inverse-square law + cosine
law) from math_reference.pdf Section 1.1, applied across a grid instead
of a single point -- the "surrogate lux map" concept from earlier in
this project, now actually built.

Usage: python3 generate_lux_heatmap.py <room_id> [resolution_m]
Output: luxmap_<room_id>.png
"""

import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from render_from_ifc import build_scene_from_real_data, candela_at_direction


def compute_illuminance_grid(lights, width, depth, resolution=0.1, work_plane_height=0.8):
    """Illuminance at a grid of points on the work plane (desk/reading
    height, not the floor -- the standard reference plane for lux
    calculations). Sums direct contribution from every real light,
    exactly like the per-pixel calculation in render_from_ifc.py, just
    evaluated across a regular grid instead of camera rays."""
    xs = np.arange(resolution / 2, width, resolution)
    ys = np.arange(resolution / 2, depth, resolution)
    grid = np.zeros((len(ys), len(xs)))
    up_normal = np.array([0, 0, 1])  # work plane faces up

    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            point = np.array([x, y, work_plane_height])
            total = 0.0
            for light in lights:
                to_light = light["position"] - point
                dist = np.linalg.norm(to_light)
                if dist < 0.05:
                    continue
                to_light_unit = to_light / dist
                direction_from_light = -to_light_unit
                candela = candela_at_direction(light, direction_from_light)
                cos_incidence = max(0.0, np.dot(up_normal, to_light_unit))
                total += (candela * cos_incidence) / (dist ** 2)
            grid[iy, ix] = total

    return grid, xs, ys


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_lux_heatmap.py <room_id> [resolution_m]")
        sys.exit(1)
    room_id = sys.argv[1]
    resolution = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15

    width, depth, height, lights = build_scene_from_real_data(room_id)
    if not lights:
        print("No lights matched for this room -- can't compute a lux map "
              "without real fixtures. Check catalog.json coverage first.")
        sys.exit(1)

    print(f"Room: {width:.2f} x {depth:.2f}m, {len(lights)} real light(s), "
          f"grid resolution {resolution}m")
    grid, xs, ys = compute_illuminance_grid(lights, width, depth, resolution)

    avg_lux, min_lux, max_lux = grid.mean(), grid.min(), grid.max()
    uniformity = min_lux / avg_lux if avg_lux > 0 else 0
    print(f"Average: {avg_lux:.1f} lux | Min: {min_lux:.1f} lux | Max: {max_lux:.1f} lux")
    print(f"Uniformity (min/avg): {uniformity:.2f}  "
          f"(common design targets are >= 0.4-0.6 depending on application)")

    fig_width = 10
    fig, ax = plt.subplots(figsize=(fig_width, fig_width * depth / width))
    im = ax.imshow(grid, origin="lower", extent=[0, width, 0, depth],
                    cmap="inferno", aspect="equal")
    fig.colorbar(im, ax=ax, label="Illuminance (lux)")

    for light in lights:
        ax.plot(light["position"][0], light["position"][1], "w+",
                 markersize=12, markeredgewidth=2)

    ax.set_xlabel("Width (m)")
    ax.set_ylabel("Depth (m)")
    ax.set_title(f"Illuminance map -- avg {avg_lux:.0f} lux, "
                 f"min {min_lux:.0f}, max {max_lux:.0f}, "
                 f"uniformity {uniformity:.2f}")

    out_path = f"luxmap_{room_id[:8]}.png"
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
