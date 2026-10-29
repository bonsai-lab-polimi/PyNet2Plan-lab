#!/usr/bin/env python3
"""
Convert the 105 real-world topologies of data/real_topologies_xlsx/ (Topology
Bench schema: sheets "Nodes_<NAME>" with Node_ID / Latitude / Longitude /
Location Name / Country, and "Edges_<NAME>" with Source / Destination /
Computed Length (km)) into PyNet2Plan files:

    data/topologies/real/top<N>_<name>.json      the network (NetworkX DiGraph saved as JSON)
    data/traffic/real/top<N>_<name>_traffic.csv  a synthetic, seeded traffic matrix
    data/topologies/real/INDEX.md                the list of all converted networks

Every edge becomes two unidirectional links with one fiber of 40 wavelengths;
parallel edges become additional fibers of the same link. The source data has no traffic,
so a synthetic matrix is generated (10-60 demands depending on the size,
1-8 wavelengths each), seeded by the topology name: the same as the first
PyNet2Plan version.

Needs pandas + openpyxl (only for this tool):  pip install pandas openpyxl
Run from the project root:  python tools/convert_real_topologies.py
"""

from __future__ import annotations

import glob
import hashlib
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pynet2plan import network, traffic  # noqa: E402

SRC_DIR = os.path.join(ROOT, "data", "real_topologies_xlsx")
TOPO_DIR = os.path.join(ROOT, "data", "topologies", "real")
TRAFFIC_DIR = os.path.join(ROOT, "data", "traffic", "real")
CAPACITY = 40


def seed_for(name: str) -> int:
    return int(hashlib.sha1(name.encode()).hexdigest()[:8], 16)


def synthetic_demands(node_names, topo_name):
    """Same generation as PyNet2Plan v1 (kept for continuity of old results)."""
    n = len(node_names)
    n_demands = max(10, min(2 * n, 60))
    n_demands = min(n_demands, n * (n - 1)) if n > 1 else 0
    rnd = random.Random(seed_for(topo_name))
    idx = list(range(n))
    used, out = set(), []
    attempts, max_attempts = 0, max(200, n_demands * 30)
    while len(out) < n_demands and attempts < max_attempts and n > 1:
        attempts += 1
        i, j = rnd.sample(idx, 2)
        if (i, j) in used:
            continue
        used.add((i, j))
        out.append(traffic.Demand(len(out), node_names[i], node_names[j], rnd.randint(1, 8)))
    return out


def convert_one(xlsx_path):
    import pandas as pd
    base = os.path.splitext(os.path.basename(xlsx_path))[0]          # TOP_38_ITALY
    parts = base.split("_", 2)
    num = parts[1] if len(parts) == 3 else "0"
    topo_name = parts[2] if len(parts) == 3 else base
    xls = pd.ExcelFile(xlsx_path)
    nsheet = next(s for s in xls.sheet_names if s.lower().startswith("nodes"))
    esheet = next(s for s in xls.sheet_names if s.lower().startswith("edges"))
    nodes_df, edges_df = xls.parse(nsheet), xls.parse(esheet)

    G = network.new_network(f"{topo_name} (real topology #{num})")
    G.graph["description"] = (f"Real-world topology {topo_name} (Topology Bench dataset), "
                              f"{CAPACITY} wavelengths per fiber.")
    id_to_name, names = {}, []
    for _, row in nodes_df.iterrows():
        loc = row.get("Location Name")
        raw = str(loc).strip() if pd.notna(loc) and str(loc).strip() else f"N{len(names)}"
        name = network.unique_name(G, raw)
        network.add_node(G, name, lat=float(row["Latitude"]), lon=float(row["Longitude"]))
        id_to_name[row["Node_ID"]] = name
        names.append(name)
    merged = 0
    for _, row in edges_df.iterrows():
        if row["Source"] not in id_to_name or row["Destination"] not in id_to_name:
            continue
        u, v = id_to_name[row["Source"]], id_to_name[row["Destination"]]
        if u == v:
            continue
        km = row.get("Computed Length (km)")
        km = float(km) if pd.notna(km) and km > 0 else None
        for a, b in ((u, v), (v, u)):
            if G.has_edge(a, b):
                G.edges[a, b]["fibers"] = G.edges[a, b].get("fibers", 1) + 1
                merged += 1
            else:
                G.add_edge(a, b, capacity=CAPACITY, length=round(km, 2) if km else None, up=True)
    network.normalize(G)
    stem = f"top{num}_{topo_name.lower()}"
    return stem, topo_name, G, synthetic_demands(names, topo_name), merged


def main():
    os.makedirs(TOPO_DIR, exist_ok=True)
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.xlsx")))
    index, problems = [], []
    for fp in files:
        try:
            stem, topo_name, G, demands, merged = convert_one(fp)
        except Exception as e:  # noqa: BLE001
            problems.append((os.path.basename(fp), str(e)))
            continue
        network.save_topology(G, os.path.join(TOPO_DIR, f"{stem}.json"))
        traffic.save_traffic(demands, os.path.join(TRAFFIC_DIR, f"{stem}_traffic.csv"), comments=[
            f"topology: {G.graph['name']} (data/topologies/real/{stem}.json)",
            "synthetic traffic matrix (seeded by the topology name), wavelengths per demand"])
        index.append((topo_name, stem, G.number_of_nodes(), G.number_of_edges(), len(demands),
                      traffic.total_traffic(demands), merged))
    index.sort(key=lambda r: (r[0].lower(), r[1]))
    with open(os.path.join(TOPO_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Real-world reference topologies\n\n"
                "Converted from `data/real_topologies_xlsx/` (Topology Bench dataset: node "
                "lat/lon and edge lengths of real optical/core networks) by "
                "`tools/convert_real_topologies.py`. Every link has one fiber of 40 wavelengths "
                "(two fibers where the dataset lists two parallel edges); "
                "its synthetic traffic matrix (seeded, 1-8 wavelengths per demand) is in "
                "`data/traffic/real/<file>_traffic.csv`.\n\n"
                "| Topology | File | Nodes | Links | Demands | Traffic (λ) |\n"
                "|---|---|---:|---:|---:|---:|\n")
        for name, stem, nn, nl, nd, tt, _ in index:
            f.write(f"| {name} | `{stem}.json` | {nn} | {nl} | {nd} | {tt} |\n")
        if problems:
            f.write("\n## Conversion problems\n\n")
            for fn, err in problems:
                f.write(f"- `{fn}`: {err}\n")
    print(f"Converted {len(index)} / {len(files)} topologies into {TOPO_DIR}")
    for p in problems:
        print("  problem:", p)


if __name__ == "__main__":
    main()
