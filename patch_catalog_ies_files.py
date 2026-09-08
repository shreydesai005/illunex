"""
Directly patches source_ies_file into your EXISTING catalog.json, in
place. Doesn't touch catalog_proposed.json or fill_catalog_todos.py --
just fixes the actual file render_from_ifc.py reads.

Usage: python3 patch_catalog_ies_files.py
"""

import json

IES_FILES = {
    "MJ50_A19A": "mj50_a19a.ies",
    "MJ61_D76L": "MJ61_1_D76L.IES",
    "MV80_LD22": "mv80_ld22.ies",
    "R522_D85P": "r522-d8_d85p.ies",
    "RN74_E55Z": "RN74-G0_E55Z.IES",
    "SL25_L396": "sl25-01_l396.ies",
    "SU33_L394": "su33-01_l394.ies",
}


def main():
    with open("catalog.json") as f:
        catalog = json.load(f)

    patched = 0
    for product in catalog:
        pid = product.get("product_id")
        if pid in IES_FILES:
            product["source_ies_file"] = IES_FILES[pid]
            patched += 1

    with open("catalog.json", "w") as f:
        json.dump(catalog, f, indent=2)

    print(f"Patched {patched} product(s) in catalog.json:")
    for p in catalog:
        print(f"  {p['product_id']} -> {p.get('source_ies_file')}")


if __name__ == "__main__":
    main()
