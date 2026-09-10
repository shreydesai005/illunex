# Illunex — AI-Assisted Lighting Design Automation

Given a building's IFC file, this pipeline decides where light fixtures
should go using real photometric math (not guesswork), selects real
products from a manufacturer catalog to fill each position, and renders
the result from multiple angles — using actual IES photometric data to
drive the light, not a generic placeholder.

It's built from real, tested pieces, not theory: every script here has
been validated against real IFC files and real manufacturer `.ies` data,
and several real bugs (schema incompatibilities, tone-mapping exposure
errors, a fixture-vs-ceiling z-fighting bug) were found and fixed along
the way. Where something is a known approximation rather than an exact
solution, it's flagged as such in the code and below — this project
favors being honest about its limits over overstating what it does.

## Table of Contents

- [Architecture](#architecture)
- [Setup](#setup)
- [Quick Start](#quick-start)
- [Script Reference](#script-reference)
  - [Room Extraction](#room-extraction)
  - [Fixture Placement](#fixture-placement)
  - [Building a Product Catalog](#building-a-product-catalog)
  - [Matching, Reports & Alternatives](#matching-reports--alternatives)
  - [Rendering](#rendering)
  - [Sourcing Products from ieslibrary.com](#sourcing-products-from-ieslibrarycom)
- [Known Limitations](#known-limitations)
- [Mathematical Reference](#mathematical-reference)

## Architecture

The pipeline has two possible entry points depending on how complete
your IFC file is, which converge into the same downstream matching and
rendering steps:

```
IFC file
  |
  |-- has IfcSpace room data? -----------------> ifc_extractor.py
  |                                                     |
  '-- no room data (bare shell) --> extract_room_from_geometry.py
                                                          |
                                     (derives a room from floor-slab geometry)
                                                          |
                                                          v
                                          placement_generator.py
                              (lumen method + spacing/uniformity math
                               decides fixture count and position)
                                                          |
                                                          v
                                     catalog.json (built once, reused)
                                     [ build_catalog.py  OR
                                       select_and_add_from_ieslibrary.py ]
                                                          |
                                                          v
                                         position_matcher.py
                             (filters + scores real products per position)
                                                          |
                                                          v
                                          render_from_ifc.py /
                                      render_guaranteed_fixture.py
                              (multi-angle render, real IES-driven light)
```

`run_full_pipeline.py` runs the entire left-hand path (real `IfcSpace`
data) in one command. The bare-shell fallback path currently has to be
run step by step, since it needs a human judgment call partway through
(the room type — there's no name data to infer it from).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install ifcopenshell certifi
```

That's the only two external packages the whole project needs — every
other script is pure Python standard library (see each file's docstring
for exactly what it needs, if anything).

**macOS-specific note**: if you hit `CERTIFICATE_VERIFY_FAILED` errors,
that's a known Python-on-macOS SSL issue, not a bug here — `pip install
certifi` (already in the list above) is the actual fix; the scripts that
need network access already use it.

## Quick Start

**If your IFC file has real room data:**

```bash
python3 run_full_pipeline.py YourFile.ifc
```

One command: extraction, placement math, product matching, and a first
render.

**If it doesn't (a bare architectural shell, no `IfcSpace` entities):**

```bash
python3 ifc_extractor.py YourFile.ifc                 # confirms IfcSpace: 0 found
python3 inspect_unnamed_proxies.py YourFile.ifc        # see the raw geometry
python3 extract_room_from_geometry.py YourFile.ifc bedroom   # your room type
python3 select_and_add_from_ieslibrary.py <room_id>    # ensure catalog coverage
python3 continue_pipeline.py                           # generate fixture positions
python3 render_guaranteed_fixture.py <room_id> 4        # verified multi-angle render
```

Always run `ifc_extractor.py` first on any new file — it tells you which
path you're on before you commit to either.

## Script Reference

### Room Extraction

| Script | What it does |
|---|---|
| `ifc_extractor.py` | Reads real room boundaries (`IfcSpace`) and any pre-existing fixtures from a well-formed IFC file. Handles both IFC4 and IFC2X3 schemas — `IfcLightFixture` doesn't exist in IFC2X3, and this degrades gracefully instead of crashing. |
| `inspect_unnamed_proxies.py` | For bare-shell files: prints every unclassified object's real size and height off the floor, since there's no name data to search by. Small objects mounted high are fixture candidates; thin tall objects are walls; large thin objects near floor level are the floor slab. |
| `extract_room_from_geometry.py` | The fallback room extractor: identifies the floor slab by its geometric signature (thin, large footprint, near floor level) and uses its footprint as an approximate room polygon. Also estimates ceiling height from wall-like objects' height. Reports both the bounding-box footprint and the true polygon area — a meaningful gap between them means the room has real shape complexity (an L-shape, a notch) the convex hull is smoothing over. |
| `requirements_table.py` | Target lux/CCT/CRI per room type (bedroom, living_room, kitchen, bathroom, foyer, closet). Not a binding standard — reasonable defaults; extend as needed. |

### Fixture Placement

| Script | What it does |
|---|---|
| `placement_generator.py` | Computes fixture count and grid layout from scratch, given only room geometry and a target lux — no pre-existing positions needed. Uses whichever constraint (total lumens needed, or spacing for even coverage) demands more fixtures. |
| `continue_pipeline.py` | Runs `placement_generator.py` against a room saved by `extract_room_from_geometry.py` and saves the resulting positions. |

### Building a Product Catalog

| Script | What it does |
|---|---|
| `ies_parser.py` | Parses real `.ies` (IES LM-63) photometric files — lumens, watts, CCT/CRI (when stated in the description text), beam angle, full candela distribution. Prefers the manufacturer's own stated lumen value over geometric integration when both are available (integration has real, discovered failure modes on certain symmetry conventions). |
| `ldt_parser.py` | Same idea for `.ldt` (EULUMDAT) files — the European equivalent. |
| `gldf_extractor.py` | Unzips `.gldf` containers and extracts the embedded `.ies`/`.ldt` files directly, plus a best-effort scan of the XML metadata. |
| `build_catalog.py` | Builds draft `catalog.json` entries from a folder of `.ies` files, flagging fields that need human judgment (`TODO_...` placeholders) rather than guessing. |
| `fill_catalog_todos.py` | Fills in those `TODO_` fields from a plain Python dict you edit — safer than hand-editing JSON. |
| `patch_catalog_ies_files.py` | Directly patches a field into an existing `catalog.json` in place, when the source file and the live catalog have drifted out of sync. |

### Matching, Reports & Alternatives

| Script | What it does |
|---|---|
| `position_matcher.py` | The core engine: filters catalog products by hard constraints (application, mounting, CRI, CCT, lumen band), then scores survivors on a configurable weighted formula (lumen fit, efficacy, CRI margin, aesthetic tag match, cost). Products with unfilled `TODO_` specs are safely excluded from matching, not treated as a crash. |
| `run_project.py` | Runs the matcher against real `rooms.json`/`positions.json`/`catalog.json`, prints per-position and per-room results, and flags rooms that are under-lit even when every position "matched" something. |
| `export_report.py` | Writes `fixture_schedule.csv` and `project_summary.csv` with explicit `OK`/`UNDER-LIT`/`INCOMPLETE` status per room — a deliverable that can't accidentally hide a real problem. |
| `generate_combinations.py` | Runs the same real positions through four different scoring priorities (balanced, cost-optimized, premium/aesthetic, energy-efficient) to produce genuine design alternatives, not one fixed answer. |

### Rendering

| Script | What it does |
|---|---|
| `render_from_ifc.py` | The core renderer: ray-traced, driven by real `.ies` candela data (not a generic point light), with visible fixture geometry (an emissive disc, not just an invisible light source). Supports named camera presets (`corner`, `top`, `bottom`, `bottom_worms_eye`, `side`, `front`) computed from the room's actual dimensions. |
| `render_guaranteed_fixture.py` | The most reliable renderer to actually use: doesn't guess a camera angle, it renders, checks the real output pixels, and automatically retries different fixtures/angles until it finds ones that provably show a lit fixture — several verified images per run, not one hopeful attempt. |
| `run_full_pipeline.py` | End to end for well-formed IFC files: extraction through rendering in one command. |

### Sourcing Products from ieslibrary.com

A free, large (~90,000+ file) public library of real manufacturer `.ies`
files, used here as a bulk product source. See the scripts' own
docstrings for the respectful-scraping details (rate limiting, honest
User-Agent, resumable downloads) — bulk-downloading everything isn't
usually necessary; see [Known Limitations](#known-limitations).

| Script | What it does |
|---|---|
| `inspect_ieslibrary.py` | One-time diagnostic confirming the site's actual API structure before building anything around it. |
| `fetch_ieslibrary_index.py` | Fetches lightweight metadata (manufacturer, model, lumens/watts) for the whole library — resumable, retries transient failures automatically. |
| `select_and_add_from_ieslibrary.py` | The recommended way to actually use this data: computes real lumens-needed for a specific room, finds the closest real match in the index, fetches just that one file, and adds it to `catalog.json` — automatically, not by browsing 90,000 entries by hand. |
| `download_ies_files.py` / `fetch_specific_ies.py` | Bulk and single-file downloaders, for when you do want actual files on disk beyond what automatic selection pulls in. |

## Known Limitations

Being direct about these rather than letting them surface as surprises:

- **Room polygons from geometry are convex hulls**, which can't represent
  a genuinely concave room shape (an L-shape, a notch) — they fill it in.
  `extract_room_from_geometry.py` reports both the bounding-box footprint
  and the true hull area; a large gap between them (we've seen up to 22%
  on a real file) means real shape complexity is being approximated, not
  captured exactly.
- **Fixture placement uses the bounding box for grid layout**, not the
  true polygon — on a strongly non-rectangular room, some generated
  positions could land outside the room's real outline. Check a `top`
  view render before trusting the layout on such rooms.
- **The geometry fallback assumes one room per file** (one floor slab).
  A file with multiple genuinely separate rooms would currently only
  extract the largest one.
- **No global illumination in the renderer** — direct light only. Real
  rooms have soft ambient fill from light bouncing off walls/floors;
  this renderer's output is correspondingly higher-contrast than a real
  photo or a DIALux render. A single-bounce radiosity pass is the
  natural next addition.
- **The lumen-method placement math is a Python approximation**, not a
  replacement for real photometric validation (DIALux or equivalent).
  Treat its output as a strong first draft, not a final certified design.
- **Room type must be supplied manually** for the geometry-fallback path
  — there's no text data in a bare-shell file to infer it from.
- **`select_and_add_from_ieslibrary.py` picks the closest lumen match**,
  not a verified "best" product on every axis (CRI/CCT are only used
  when stated in the file's own text) — review its `TODO_` flags before
  treating a selection as final.

## Mathematical Reference

`math_reference.pdf` (source: `math_reference.tex`) documents every
formula this project actually uses — the lumen method, room index,
utilization factor, the rendering equation, Lambertian BRDF, radiosity,
Monte Carlo path tracing, tone mapping, and the CIE UGR glare formula —
each tied back to the specific file and function where it's implemented.
None of this is proprietary to any specific software; it's standard,
published lighting-engineering and computer-graphics science.
