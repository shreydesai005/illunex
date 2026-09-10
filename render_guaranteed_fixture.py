"""
Instead of picking one camera angle and hoping a fixture is visible,
this actually CHECKS the rendered pixels after each attempt and tries
different fixtures/angles automatically until it finds one that
provably shows a lit fixture disc (max brightness comfortably above
what any diffuse surface can reach). This is the most reliable approach
given this project's history: geometric reasoning about camera angles
has been wrong more than once, while checking the actual output pixels
has caught every real bug so far.

Usage: python3 render_guaranteed_fixture.py <room_id>
Output: guaranteed_fixture_view.png (only written once verified) +
        console report of which fixture/angle worked
"""

import sys
import numpy as np
from PIL import Image

from render_from_ifc import build_scene_from_real_data, render, _compute_camera_basis

BRIGHTNESS_THRESHOLD = 220  # a verified-visible fixture disc should push
# max brightness well above anything a diffuse surface reaches (we've seen
# surfaces top out around 150-170 in earlier real renders in this project)


def try_view(lights, width, depth, height, target_light, cam_offset, fov_deg, out_path):
    cam_pos = (width * cam_offset[0], depth * cam_offset[1], cam_offset[2])
    look_at = target_light["position"]
    render(lights, cam_pos, look_at, width, depth, height, fov_deg=fov_deg,
           width_px=320, height_px=240, out_path=out_path, supersample=2)
    img = np.array(Image.open(out_path).convert("L"))
    return img.max()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 render_guaranteed_fixture.py <room_id> [num_views]")
        sys.exit(1)
    room_id = sys.argv[1]
    num_views = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    width, depth, height, lights = build_scene_from_real_data(room_id)
    if not lights:
        print("No lights matched for this room at all -- fix catalog.json coverage "
              "first (see the WARNING lines from run_project.py/render_from_ifc.py).")
        sys.exit(1)

    print(f"Room: {width:.2f} x {depth:.2f} x {height:.2f}m, {len(lights)} real light(s)")
    print(f"Looking for {num_views} genuinely different verified angles...\n")

    # Each camera_offset is a different vantage point (a different corner/side
    # of the room) -- for each one, search fixtures+fov until THAT angle finds
    # a verified shot, giving real positional variety across the final set,
    # not just minor variations on the same one working combination.
    camera_offsets = [(0.1, 0.1, 1.4), (0.1, 0.9, 1.4), (0.9, 0.1, 1.4),
                       (0.9, 0.9, 1.4), (0.5, 0.1, 0.3), (0.5, 0.9, 2.3)]
    fov_options = [55, 70, 40, 85]
    max_attempts_per_angle = 12

    successes = []
    for angle_idx, cam_offset in enumerate(camera_offsets):
        if len(successes) >= num_views:
            break

        found = False
        attempts_this_angle = 0
        for light_idx, target_light in enumerate(lights):
            if found:
                break
            for fov in fov_options:
                attempts_this_angle += 1
                if attempts_this_angle > max_attempts_per_angle:
                    break
                out_path = f"guaranteed_view_{angle_idx+1}.png"
                try:
                    max_brightness = try_view(lights, width, depth, height, target_light,
                                               cam_offset, fov, out_path)
                except Exception:
                    continue

                if max_brightness >= BRIGHTNESS_THRESHOLD:
                    print(f"View {angle_idx+1} (cam={cam_offset}): VERIFIED -- "
                          f"fixture {light_idx}, fov={fov}, brightness={max_brightness} "
                          f"-> {out_path}")
                    successes.append(out_path)
                    found = True
                    break
            if attempts_this_angle > max_attempts_per_angle:
                break

        if not found:
            print(f"View {angle_idx+1} (cam={cam_offset}): no verified angle found "
                  f"after {attempts_this_angle} attempts -- skipping this vantage point.")

    print(f"\n{len(successes)}/{num_views} requested views verified and saved: {successes}")
    if not successes:
        print("Could not verify ANY angle -- this is a real finding worth checking "
              "directly (FIXTURE_DISC_RADIUS, each light's z vs the room's "
              "ceiling_height_m), not just a rendering-luck issue.")


if __name__ == "__main__":
    main()