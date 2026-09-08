"""
Extractor for .gldf files (Global Lighting Data Format).

Important honesty note: a .gldf file is a zip container, and its outer
structure (Header / GeneralDefinitions / ProductDefinitions) is public,
but the exact nested tag names differ across GLDF schema versions and
authoring tools, and I don't have a verified real sample to confirm the
precise paths for fields like CCT/CRI/wattage. Rather than guess exact
XML paths and risk silently pulling wrong data, this extractor takes a
more robust approach:

  1. It always finds and parses the embedded .ies / .ldt files directly
     (these formats ARE stable and this parser is trustworthy).
  2. For metadata (name, wattage, CCT, CRI, price, application), it does
     a best-effort generic scan of the XML for elements/attributes whose
     tag names contain recognizable keywords, and returns everything it
     finds under a "raw_metadata_candidates" key.

Before trusting this for real catalog ingestion: open one real .gldf file
from your own catalogs (`unzip -l file.gldf`, then inspect the .xml inside)
and confirm which keys in raw_metadata_candidates are the real ones --
then hardcode those exact paths for your specific manufacturers. Vendors
are not always schema-consistent with each other either.
"""

import zipfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ies_parser import parse_ies_file

try:
    from ldt_parser import parse_ldt_file
except ImportError:
    parse_ldt_file = None

METADATA_KEYWORDS = [
    "wattage", "watt", "power",
    "flux", "lumen",
    "cct", "colortemperature", "colourtemperature",
    "cri", "colorrenderingindex", "colourrenderingindex",
    "width", "length", "height", "diameter",
    "mounting", "application", "productname", "name",
    "gtin", "articlenumber", "price",
]


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _scan_xml_for_keywords(xml_bytes: bytes) -> dict:
    candidates = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return candidates

    for elem in root.iter():
        tag = _strip_ns(elem.tag).lower()
        for kw in METADATA_KEYWORDS:
            if kw in tag:
                text = (elem.text or "").strip()
                if text:
                    candidates.setdefault(_strip_ns(elem.tag), []).append(text)
        for attr_name, attr_val in elem.attrib.items():
            if any(kw in attr_name.lower() for kw in METADATA_KEYWORDS):
                candidates.setdefault(f"@{attr_name}", []).append(attr_val)
    return candidates


def extract_gldf(path: str, workdir: str = None) -> dict:
    """Returns a dict with:
       - photometries: list of parsed IES/LDT dicts (the trustworthy part)
       - raw_metadata_candidates: best-effort keyword hits from the XML
       - source_file: original path
    You still need to map raw_metadata_candidates into your normalized
    schema by hand for each manufacturer the first time you see their file.
    """
    result = {"source_file": path, "photometries": [], "raw_metadata_candidates": {}}
    workdir = Path(workdir) if workdir else Path(path).with_suffix("")

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        xml_names = [n for n in names if n.lower().endswith(".xml")]
        for xn in xml_names:
            merged = _scan_xml_for_keywords(zf.read(xn))
            for k, v in merged.items():
                result["raw_metadata_candidates"].setdefault(k, []).extend(v)

        photometric_names = [n for n in names if n.lower().endswith((".ies", ".ldt"))]
        workdir.mkdir(parents=True, exist_ok=True)
        for pn in photometric_names:
            extracted_path = workdir / Path(pn).name
            with open(extracted_path, "wb") as out:
                out.write(zf.read(pn))
            try:
                if pn.lower().endswith(".ies"):
                    parsed = parse_ies_file(str(extracted_path))
                elif parse_ldt_file is not None:
                    parsed = parse_ldt_file(str(extracted_path))
                else:
                    continue
                parsed["_source_archive_entry"] = pn
                result["photometries"].append(parsed)
            except Exception as e:
                result["photometries"].append({
                    "_source_archive_entry": pn,
                    "_parse_error": str(e),
                })

    return result


if __name__ == "__main__":
    import sys
    import json
    print(json.dumps(extract_gldf(sys.argv[1]), indent=2, default=str))
