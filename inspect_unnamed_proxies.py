"""
For files like FATHERBEDROOM_.ifc: no room data, and every element is an
unnamed IfcBuildingElementProxy -- nothing for a keyword search to match
against. This falls back to geometry instead of names: prints each
proxy's bounding box (size) and height off the floor, so you can manually
judge which ones are plausibly light fixtures (small, mounted near
ceiling height) versus furniture or something else (larger, floor-level).

This does NOT automatically classify anything -- it gives you the real
numbers to make that call yourself, since there's no reliable
programmatic signal (no names, no room context) to do it for you here.

Usage: python3 inspect_unnamed_proxies.py <ifc_file>
"""

import sys

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_unnamed_proxies.py <ifc_file>")
        sys.exit(1)

    model = ifcopenshell.open(sys.argv[1])
    settings = ifcopenshell.geom.settings()
    try:
        settings.set(settings.USE_WORLD_COORDS, True)
    except AttributeError:
        settings.set("use-world-coords", True)

    proxies = model.by_type("IfcBuildingElementProxy")
    print(f"Inspecting {len(proxies)} IfcBuildingElementProxy entities "
          f"(sorted by height off floor -- ceiling-mounted objects, the most "
          f"plausible light fixture candidates, will sort toward the top):\n")

    results = []
    for p in proxies:
        try:
            shape = ifcopenshell.geom.create_shape(settings, p)
        except RuntimeError as e:
            print(f"GlobalId={p.GlobalId}: couldn't extract geometry ({e})")
            continue

        verts = shape.geometry.verts
        xs = verts[0::3]
        ys = verts[1::3]
        zs = verts[2::3]
        width = max(xs) - min(xs)
        depth = max(ys) - min(ys)
        height_extent = max(zs) - min(zs)
        z_bottom = min(zs)

        results.append({
            "global_id": p.GlobalId,
            "width": width, "depth": depth, "height_extent": height_extent,
            "z_bottom": z_bottom,
            "position": (sum(xs) / len(xs), sum(ys) / len(ys), z_bottom),
        })

    results.sort(key=lambda r: r["z_bottom"], reverse=True)
    for r in results:
        print(f"GlobalId={r['global_id']}")
        print(f"  size: {r['width']:.3f} x {r['depth']:.3f} x {r['height_extent']:.3f} m")
        print(f"  bottom of object is {r['z_bottom']:.3f} m off the model origin's floor level")
        print(f"  approx center position: "
              f"({r['position'][0]:.3f}, {r['position'][1]:.3f}, {r['position'][2]:.3f})")
        print()

    print("Look for: small objects (under ~0.3m in each dimension) with a high "
          "z_bottom value close to your known ceiling height -- those are the "
          "plausible light fixture candidates. Large objects near z_bottom=0 are "
          "more likely furniture sitting on the floor.")


if __name__ == "__main__":
    main()
