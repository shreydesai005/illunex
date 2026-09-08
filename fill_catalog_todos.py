"""
Fills in the TODO_ placeholder fields in catalog_proposed.json by code,
instead of hand-editing JSON (no risk of breaking commas/syntax that way).

Edit the OVERRIDES dict below with your real values, then run:
    python3 fill_catalog_todos.py
Reads catalog_proposed.json, writes catalog.json.

You only need to list the fields you're actually overriding -- anything
you leave out keeps whatever value is already in catalog_proposed.json.
Re-run this any time you get better numbers; it always starts fresh from
catalog_proposed.json, so it won't compound on top of previous edits.
"""

import json

# ---- EDIT THIS with your real values ----
# The prices below are PLACEHOLDER EXAMPLES, not real iGuzzini pricing --
# replace every one with what your actual supplier/distributor quotes you.
OVERRIDES = {
    "MJ50_A19A":  {"price": 120, "cri": 80},
    "MJ61_D76L":  {"price": 145},
    "MV80_LD22":  {"price": 65},
    "R522_D85P":  {"price": 78},
    "RN74_E55Z":  {"price": 95},
    "SL25_L396":  {"price": 310, "cri": 80},
    "SU33_L394":  {"price": 260, "cri": 80},
}
# ------------------------------------------


def main():
    with open("catalog_proposed.json") as f:
        catalog = json.load(f)

    for product in catalog:
        pid = product["product_id"]
        if pid in OVERRIDES:
            product.update(OVERRIDES[pid])

    remaining = [
        f"{p['product_id']}.{k}"
        for p in catalog
        for k, v in p.items()
        if isinstance(v, str) and v.startswith("TODO_")
    ]

    with open("catalog.json", "w") as f:
        json.dump(catalog, f, indent=2)

    print(f"Wrote catalog.json with {len(catalog)} products.")
    if remaining:
        print(f"STILL UNFILLED -- add these to OVERRIDES and re-run: {remaining}")
    else:
        print("All TODO_ fields filled in -- ready for run_project.py.")


if __name__ == "__main__":
    main()
