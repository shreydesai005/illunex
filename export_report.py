"""
Produces usable output from whatever real data you currently have --
rooms.json, positions.json, catalog.json -- without hiding the fact that
some rooms don't yet meet their lighting target. A polished-looking
report that silently buries an under-lit room is worse than no report.

Usage: python3 export_report.py
Outputs: fixture_schedule.csv, project_summary.csv
"""

import csv
import json

from position_matcher import load_rooms, load_positions, match_positions_to_catalog


def main():
    try:
        rooms = load_rooms("rooms.json")
        positions = load_positions("positions.json")
    except FileNotFoundError as e:
        print(f"Missing {e.filename} -- run ifc_extractor.py first.")
        return

    try:
        with open("catalog.json") as f:
            catalog_full = json.load(f)
    except FileNotFoundError:
        print("Missing catalog.json -- finish build_catalog.py / fill_catalog_todos.py first.")
        return

    catalog = [c for c in catalog_full if c.get("include_in_automated_matching", True)]
    results = match_positions_to_catalog(rooms, positions, catalog)

    positions_by_id = {p.position_id: p for p in positions}
    rooms_by_id = {r.room_id: r for r in rooms}

    _write_fixture_schedule(results, positions_by_id, rooms_by_id)
    _write_project_summary(results, positions_by_id, rooms_by_id)

    print("Wrote fixture_schedule.csv and project_summary.csv")
    print("")
    print("IMPORTANT: open project_summary.csv and check the 'status' column before")
    print("sharing this anywhere. Rooms marked UNDER-LIT or INCOMPLETE do not currently")
    print("meet their target lux -- this is a working draft reflecting today's catalog")
    print("and CAD placement, not a validated design. Re-run this after any catalog or")
    print("placement change to get an updated (and hopefully cleaner) version.")


def _write_fixture_schedule(results, positions_by_id, rooms_by_id):
    with open("fixture_schedule.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["position_id", "room_id", "room_application", "product_id",
                          "manufacturer", "total_lumens", "input_watts", "price",
                          "mounting_type", "match_score", "status"])
        for pos_id, r in results.items():
            pos = positions_by_id[pos_id]
            room = rooms_by_id[pos.room_id]
            product = r["product"]
            if product:
                writer.writerow([
                    pos_id, pos.room_id, room.application, product["product_id"],
                    product.get("manufacturer", ""), product["total_lumens"],
                    product["input_watts"], product.get("price", ""),
                    product.get("mounting_type", ""), f"{r['score']:.3f}", "MATCHED",
                ])
            else:
                writer.writerow([
                    pos_id, pos.room_id, room.application, "NONE", "", "", "", "",
                    "", "", "NO MATCH -- needs catalog attention",
                ])


def _write_project_summary(results, positions_by_id, rooms_by_id):
    by_room = {}
    for pos_id, r in results.items():
        room_id = positions_by_id[pos_id].room_id
        by_room.setdefault(room_id, []).append(r)

    with open("project_summary.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["room_id", "application", "target_lux", "fixtures_matched",
                          "fixtures_total", "lumens_delivered", "lumens_required",
                          "pct_of_target", "total_cost", "total_watts", "status"])

        grand_cost, grand_watts = 0.0, 0.0
        for room_id, room_results in by_room.items():
            room = rooms_by_id[room_id]
            matched = [r for r in room_results if r["product"]]
            total_lumens = sum(r["product"]["total_lumens"] for r in matched)
            total_required = sum(r["required_lumens_per_fixture"] for r in room_results)
            pct = (total_lumens / total_required * 100) if total_required else 0
            total_cost = sum(float(r["product"].get("price", 0) or 0) for r in matched)
            total_watts = sum(r["product"]["input_watts"] for r in matched)
            grand_cost += total_cost
            grand_watts += total_watts

            if len(matched) < len(room_results):
                status = f"INCOMPLETE -- {len(room_results) - len(matched)} fixture(s) unmatched"
            elif pct < 85:
                status = f"UNDER-LIT -- {pct:.0f}% of target"
            else:
                status = "OK"

            writer.writerow([
                room_id, room.application, room.target_lux, len(matched), len(room_results),
                f"{total_lumens:.0f}", f"{total_required:.0f}", f"{pct:.0f}%",
                f"{total_cost:.2f}", f"{total_watts:.1f}", status,
            ])

        writer.writerow([])
        writer.writerow(["TOTAL", "", "", "", "", "", "", "", f"{grand_cost:.2f}",
                          f"{grand_watts:.1f}", ""])


if __name__ == "__main__":
    main()
