"""
Builds draft catalog.json entries from a folder of .ies files.

Extracts what's reliably derivable from the photometric file itself
(lumens, watts, CCT, CRI when stated in text) and fills everything else
with an explicit "TODO_..." placeholder -- these are the fields that
genuinely need a human lighting professional's judgment, not something
worth guessing at automatically (see our earlier discussion on why
aesthetics/application/mounting get curated by hand at this catalog size).

Usage: python3 build_catalog.py path/to/folder/with/ies/files > catalog_draft.json
"""

import sys
import re
import json
from pathlib import Path

from ies_parser import parse_ies_file

CCT_PATTERN = re.compile(r"(\d{4})\s*K\b")
CRI_PATTERN = re.compile(r"CRI\s*[>]?\s*(\d{2})\b", re.IGNORECASE)

# Keyword -> (mounting_type, suitable_roles, include_in_automated_matching)
# Best-effort guesses from the description text. CONFIRM every one of these
# against the real product before trusting it -- text descriptions don't
# always state mounting clearly, and these are inferred, not measured.
MOUNTING_HINTS = [
    ("recessed", "recessed_ceiling", ["ambient"], True),
    ("ceiling-mounted", "surface_ceiling", ["ambient"], True),
    ("floor lamp", "floor_standing", ["decorative_portable"], False),
    ("bush lamp", "floor_standing", ["decorative_portable"], False),
    ("wall wash", "recessed_ceiling", ["wall_wash"], True),
    ("track", "track", ["accent"], True),
]


def _extract_cct(text: str):
    m = CCT_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_cri(text: str):
    m = CRI_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _guess_mounting(text: str):
    text_l = text.lower()
    for keyword, mounting, roles, include in MOUNTING_HINTS:
        if keyword in text_l:
            return mounting, roles, include
    return "TODO_confirm_mounting_type", ["TODO_confirm_role"], True


def build_entry(ies_path: Path) -> dict:
    d = parse_ies_file(str(ies_path))
    combined_text = f"{d['luminaire_description']} {d['lamp_description']}"
    mounting, roles, include = _guess_mounting(combined_text)

    return {
        "product_id": d["luminaire_catalog_number"],
        "manufacturer": d["manufacturer"],
        "description": d["luminaire_description"],
        "total_lumens": d["total_lumens"],
        "total_lumens_source": d["total_lumens_source"],
        "input_watts": d["input_watts"],
        "efficacy_lm_per_w": round(d["total_lumens"] / d["input_watts"], 1) if d["input_watts"] else None,
        "cct_k": _extract_cct(combined_text) or "TODO_confirm_cct",
        "cri": _extract_cri(combined_text) or "TODO_confirm_cri_check_datasheet",
        "beam_angle_deg": d["beam_angle_deg"],
        "mounting_type": mounting,
        "suitable_roles": roles,
        "include_in_automated_matching": include,
        "application": "TODO_assign_room_types",       # e.g. ["living_room", "bedroom"]
        "aesthetic_tags": ["TODO_assign_style_tags"],   # e.g. ["minimalist"]
        "price": "TODO_add_price",
        "source_ies_file": ies_path.name,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_catalog.py path/to/folder/with/ies/files", file=sys.stderr)
        sys.exit(1)

    folder = Path(sys.argv[1])
    ies_files = sorted(list(folder.glob("*.ies")) + list(folder.glob("*.IES")))
    entries = [build_entry(f) for f in ies_files]

    print(json.dumps(entries, indent=2), file=sys.stdout)

    todo_count = sum(1 for e in entries for v in e.values()
                      if isinstance(v, str) and v.startswith("TODO")
                      or isinstance(v, list) and any(str(x).startswith("TODO") for x in v))
    print(f"\n# {len(entries)} products processed, {todo_count} fields need your review "
          f"(search for TODO_ in the output)", file=sys.stderr)


if __name__ == "__main__":
    main()
