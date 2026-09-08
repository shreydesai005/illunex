"""
Parser for EULUMDAT (.ldt) photometric files -- the European counterpart
to IES, and the other format you'll commonly find bundled inside .gldf
containers or shipped standalone by European manufacturers.

CONFIDENCE NOTE: EULUMDAT's line-by-line layout is public and stable, but
it's a plain fixed-order text file with no field labels, so a single
off-by-one in the header line count silently misreads every field after
it. Validate this against one real .ldt file from your own catalogs
(open it in a text editor -- it's plain text -- and check that line 9 is
really the luminaire name, etc.) before trusting it on your full catalog.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LDTData:
    company: Optional[str] = None
    luminaire_type: int = 1        # Ityp: 1=point (vert. symmetry), 2=linear, 3=point (other symmetry)
    symmetry: int = 0              # Isym
    num_c_planes: int = 0          # Mc
    dist_between_c_planes: float = 0.0
    num_intensities_per_plane: int = 0   # Ng
    dist_between_intensities: float = 0.0
    report_number: Optional[str] = None
    luminaire_name: Optional[str] = None
    luminaire_number: Optional[str] = None

    length_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0

    downward_flux_fraction_pct: float = 0.0
    light_output_ratio_pct: float = 0.0
    conversion_factor: float = 1.0

    num_lamp_sets: int = 0
    lamp_sets: list = field(default_factory=list)  # each: dict(num_lamps, type, flux, cct, cri, watts)

    c_angles: list = field(default_factory=list)
    g_angles: list = field(default_factory=list)
    candela_values: list = field(default_factory=list)  # [c_plane_idx][g_angle_idx]

    total_lumens: float = 0.0
    total_watts: float = 0.0


def parse_ldt_file(path: str) -> dict:
    with open(path, "r", errors="ignore") as f:
        lines = [ln.strip() for ln in f.readlines()]

    def num(i):
        return float(lines[i]) if lines[i] else 0.0

    d = LDTData(
        company=lines[0] or None,
        luminaire_type=int(num(1)),
        symmetry=int(num(2)),
        num_c_planes=int(num(3)),
        dist_between_c_planes=num(4),
        num_intensities_per_plane=int(num(5)),
        dist_between_intensities=num(6),
        report_number=lines[7] or None,
        luminaire_name=lines[8] or None,
        luminaire_number=lines[9] or None,
    )
    # lines[10]=file name, lines[11]=date/user -- skipped
    d.length_mm = num(12)
    d.width_mm = num(13)
    d.height_mm = num(14)
    # lines 15-17: luminous area length/width, lines 18-21: luminous area heights C0/90/180/270 -- skipped here
    d.downward_flux_fraction_pct = num(21)
    d.light_output_ratio_pct = num(22)
    d.conversion_factor = num(23) or 1.0
    # line 24: tilt angle -- skipped

    idx = 25
    d.num_lamp_sets = int(num(idx)); idx += 1

    total_lumens = 0.0
    total_watts = 0.0
    for _ in range(d.num_lamp_sets):
        n_lamps = num(idx); idx += 1
        lamp_type = lines[idx]; idx += 1
        flux = num(idx); idx += 1
        cct = lines[idx]; idx += 1
        cri = lines[idx]; idx += 1
        watts = num(idx); idx += 1
        d.lamp_sets.append({
            "num_lamps": n_lamps, "type": lamp_type, "total_flux": flux,
            "cct": cct, "cri": cri, "watts": watts,
        })
        total_lumens += n_lamps * flux
        total_watts += watts
    d.total_lumens = total_lumens
    d.total_watts = total_watts

    # Direct ratios for 10 room indices -- skip (10 lines)
    idx += 10

    d.c_angles = [num(idx + i) for i in range(d.num_c_planes)]
    idx += d.num_c_planes
    d.g_angles = [num(idx + i) for i in range(d.num_intensities_per_plane)]
    idx += d.num_intensities_per_plane

    n_planes_with_data = d.num_c_planes if d.symmetry in (0, 1) else max(1, d.num_c_planes // 2 + 1)
    for _ in range(n_planes_with_data):
        plane_vals = [num(idx + i) for i in range(d.num_intensities_per_plane)]
        idx += d.num_intensities_per_plane
        d.candela_values.append(plane_vals)

    return d.__dict__


if __name__ == "__main__":
    import sys, json
    print(json.dumps(parse_ldt_file(sys.argv[1]), indent=2, default=str))
