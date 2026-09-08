"""
Reference lighting-requirement defaults, by room type, for residential
projects.

IMPORTANT CAVEAT: unlike EN 12464-1 for workplaces, there isn't one
universal binding standard for residential lux levels -- these are
commonly-used general design targets from typical residential lighting
guides, not ground truth. Confirm against whatever design brief or local
building code applies to this project before finalizing a real design.
Treat these as a reasonable starting point to get the pipeline running
end to end, not as values to ship a client report with unchecked.

Keys match what ifc_extractor._infer_room_type() produces after
normalization (lowercased, spaces -> underscores, trailing room NUMBER
stripped -- so "Bedroom 2" and "Bedroom 1" both map to "bedroom").
"""

RESIDENTIAL_REQUIREMENTS = {
    "tv_room": {
        "application": "living_room", "target_lux": 200,
        "cct_k": 2700, "min_cri": 80, "ceiling_height_m": 2.7,
    },
    "living_room": {
        "application": "living_room", "target_lux": 200,
        "cct_k": 2700, "min_cri": 80, "ceiling_height_m": 2.7,
    },
    "bedroom": {
        "application": "bedroom", "target_lux": 150,
        "cct_k": 2700, "min_cri": 80, "ceiling_height_m": 2.7,
    },
    "toilet": {
        "application": "bathroom", "target_lux": 200,
        "cct_k": 3500, "min_cri": 80, "ceiling_height_m": 2.6,
    },
    "foyer": {
        "application": "entry_hall", "target_lux": 150,
        "cct_k": 3000, "min_cri": 80, "ceiling_height_m": 2.7,
    },
    "wardrobe": {
        "application": "closet", "target_lux": 150,
        "cct_k": 3500, "min_cri": 80, "ceiling_height_m": 2.4,
    },
}

# Room types deliberately excluded from this indoor general-lighting pass --
# either non-occupied utility spaces, or spaces that need a different design
# track entirely. Add to this as you find more in your real files.
SKIP_ROOM_TYPES = {
    "shaft": "mechanical/utility space -- not a general-lighting space.",
    "court": "possibly an outdoor courtyard/light well -- needs outdoor "
             "lighting rules, not this indoor pipeline. Confirm with the "
             "model/architect before excluding permanently.",
}
