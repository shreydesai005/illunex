"""
Given:
  - rooms (from your geometry-extraction stage): polygon, ceiling height,
    and lighting requirements per room
  - positions (from your placement algorithm / CAD file): already-fixed
    x, y, z for every luminaire, grouped by room and role
  - a normalized product catalog (built from ies_parser / ldt_parser /
    gldf_extractor output, plus your own manual tags for application,
    mounting type, and aesthetics)

...this picks which real product goes at each position.

Because the CAD file already fixed the number and location of fixtures
per room, you do NOT need to solve for fixture count here -- only for
which SKU delivers the right lumens-per-fixture, form factor, CCT/CRI,
and aesthetic fit at the lowest cost. That's a filter-then-score problem,
not a search problem, which is why this file has no optimizer in it.
"""

import math
import json
from dataclasses import dataclass, field, asdict


def polygon_area(points):
    """Shoelace formula. points: [(x, y), ...] in meters."""
    n = len(points)
    area = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def save_rooms_and_positions(rooms, positions, rooms_path="rooms.json", positions_path="positions.json"):
    """Persist extracted rooms/positions so you don't need to re-run
    ifcopenshell (or ezdxf) every time you want to test the matcher."""
    with open(rooms_path, "w") as f:
        json.dump([asdict(r) for r in rooms], f, indent=2)
    with open(positions_path, "w") as f:
        json.dump([asdict(p) for p in positions], f, indent=2)


def load_rooms(path="rooms.json"):
    with open(path) as f:
        return [RoomRequirement(**d) for d in json.load(f)]


def load_positions(path="positions.json"):
    with open(path) as f:
        data = json.load(f)
    # IFC coordinates come back as numpy float64 via ifcopenshell -- JSON
    # round-trips them as plain floats, which is what we want anyway.
    return [LightingPosition(**d) for d in data]


def _bbox_length_width(polygon):
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return (max(xs) - min(xs)), (max(ys) - min(ys))


def room_index(length, width, mounting_height_above_task):
    return (length * width) / (mounting_height_above_task * (length + width))


def estimate_utilization_factor(room_idx, ceiling_reflectance=0.7,
                                 wall_reflectance=0.5, floor_reflectance=0.2):
    """
    Rough UF approximation from room index. NOT a substitute for a real
    utilance table or DIALux -- it exists to give the lumen method a
    defensible number to iterate against before final DIALux validation.
    """
    base = 0.35 + 0.35 * min(room_idx / 3.0, 1.0)
    reflectance_factor = (ceiling_reflectance + wall_reflectance + floor_reflectance) / (0.7 + 0.5 + 0.2)
    return round(base * reflectance_factor, 3)


@dataclass
class RoomRequirement:
    room_id: str
    application: str                 # must match catalog "application" tag
    polygon: list                    # [(x, y), ...] meters
    ceiling_height_m: float
    task_height_m: float = 0.8
    target_lux: float = 500
    cct_k: int = 4000
    min_cri: int = 80
    maintenance_factor: float = 0.8
    cct_tolerance_k: int = 500


@dataclass
class LightingPosition:
    position_id: str
    room_id: str
    x: float
    y: float
    z: float
    mounting_type: str = "recessed_ceiling"
    role: str = "ambient"             # e.g. "ambient", "wall_wash", "accent" -- from CAD layer


DEFAULT_WEIGHTS = {"lumen_fit": 0.4, "efficacy": 0.2, "cri_margin": 0.1, "aesthetic": 0.2, "cost": 0.1}


def match_positions_to_catalog(rooms, positions, catalog, style_profile=None, weights=None):
    """Returns {position_id: {product, score, required_lumens_per_fixture,
    room_index, utilization_factor, candidates_considered}}
    weights: optional dict overriding DEFAULT_WEIGHTS -- lets you bias
    matching toward cost, aesthetics, efficacy, etc. Missing keys fall
    back to the default for that criterion."""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    rooms_by_id = {r.room_id: r for r in rooms}
    positions_by_group = {}
    for p in positions:
        positions_by_group.setdefault((p.room_id, p.role), []).append(p)

    results = {}
    for (room_id, role), group_positions in positions_by_group.items():
        room = rooms_by_id[room_id]
        area = polygon_area(room.polygon)
        n_fixtures = len(group_positions)

        mount_h = max(room.ceiling_height_m - room.task_height_m, 0.5)
        length, width = _bbox_length_width(room.polygon)
        k = room_index(length, width, mount_h)
        uf = estimate_utilization_factor(k)

        required_lumens = (room.target_lux * area) / max(n_fixtures * uf * room.maintenance_factor, 1e-6)

        # The lumen-method target above assumes this role is responsible for
        # the room's general illuminance. That's true for "ambient" fixtures,
        # but not for accent/wall-wash roles, which serve a separate design
        # goal (e.g. vertical wall illuminance) and shouldn't be hard-filtered
        # against a general-lux number computed for the whole room. A real
        # system would carry a separate target per role; this demo only
        # applies the strict lumen band to the ambient role and scores other
        # roles more loosely.
        strict_band = (role == "ambient")
        candidates = _filter_catalog(catalog, room, group_positions[0], required_lumens, strict_band)
        scored = sorted(
            ((_score_candidate(c, required_lumens, room, style_profile, weights), c) for c in candidates),
            key=lambda t: t[0], reverse=True,
        )
        best_score, best = (scored[0] if scored else (None, None))

        for p in group_positions:
            results[p.position_id] = {
                "product": best,
                "score": best_score,
                "required_lumens_per_fixture": round(required_lumens, 1),
                "room_index": round(k, 2),
                "utilization_factor": uf,
                "candidates_considered": len(candidates),
            }
    return results


def _filter_catalog(catalog, room, sample_position, required_lumens, strict_band=True):
    out = []
    lo, hi = (0.5, 2.0) if strict_band else (0.05, 20.0)
    warned = set()
    for c in catalog:
        applications = c.get("application")
        if applications:
            # Accept either a single string or a list of applicable room
            # types -- a product might legitimately suit several room types.
            if isinstance(applications, str):
                applications = [applications]
            if room.application not in applications:
                continue
        if c.get("mounting_type") and c["mounting_type"] != sample_position.mounting_type:
            continue

        # Products can carry an unfilled "TODO_..." placeholder (e.g. from
        # select_and_add_from_ieslibrary.py, when CRI/CCT wasn't stated in
        # the source file's text) instead of a real number. Comparing a
        # string to an int crashes outright -- exclude the product instead,
        # since matching against an unverified spec would be worse than not
        # matching at all. Warn once per product so this isn't silent.
        cri = c.get("cri", 0)
        cct = c.get("cct_k")
        lumens = c.get("total_lumens", 0)
        if not all(isinstance(v, (int, float)) for v in (cri, lumens) if v is not None) or \
           (cct is not None and not isinstance(cct, (int, float))):
            pid = c.get("product_id", "?")
            if pid not in warned:
                print(f"NOTE: excluding '{pid}' from matching -- it has an unfilled "
                      f"TODO_ placeholder instead of a real number (cri={cri!r}, "
                      f"cct_k={cct!r}, total_lumens={lumens!r}). Fix it in catalog.json "
                      f"to have this product considered.")
                warned.add(pid)
            continue

        if cri < room.min_cri:
            continue
        if cct is not None and abs(cct - room.cct_k) > room.cct_tolerance_k:
            continue
        if lumens < required_lumens * lo or lumens > required_lumens * hi:
            continue
        out.append(c)
    return out


def _score_candidate(c, required_lumens, room, style_profile=None, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    lumens = c.get("total_lumens", 1)
    watts = c.get("input_watts", 1) or 1
    efficacy = lumens / watts

    lumen_fit = 1 - min(abs(lumens - required_lumens) / required_lumens, 1.0)
    efficacy_norm = min(efficacy / 150.0, 1.0)
    cri_margin = min(max(c.get("cri", 0) - room.min_cri, 0) / 20.0, 1.0)
    aesthetic = _aesthetic_fit(c.get("aesthetic_tags", []), style_profile)
    cost_norm = 1 - min((c.get("price", 0) or 0) / 500.0, 1.0)

    return (weights["lumen_fit"] * lumen_fit + weights["efficacy"] * efficacy_norm +
            weights["cri_margin"] * cri_margin + weights["aesthetic"] * aesthetic +
            weights["cost"] * cost_norm)


def _aesthetic_fit(product_tags, style_profile):
    if not product_tags or not style_profile:
        return 0.5
    overlap = len(set(product_tags) & set(style_profile))
    return min(overlap / max(len(style_profile), 1), 1.0)