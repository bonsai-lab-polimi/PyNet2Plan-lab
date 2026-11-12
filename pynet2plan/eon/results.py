"""
pynet2plan.eon.results
=====================

Every EON run is saved in its own folder of ``results/eon/`` (CSV files plus
a copy of the inputs), like the runs of the main tool::

    results/eon/2026-10-12_23-10-05_rsa-greedy_eon-6/
        summary.csv        one row: algorithm, status, demands served, slots, 3R, cost, ...
        demands.csv        per demand: state, blocking reason, lightpaths, paths, km
        lightpaths.csv     per lightpath: transponder type, path, 3R, slots of every segment
        links.csv          per link: slots used, utilization, max_slot = highest slot in use + 1
        spectrum.csv       per link and lightpath segment: first slot and number of slots
        fibre_cuts.csv     per fibre: demands down / switched to backup when it is cut
        validation.csv, report.txt
        topology.json, traffic.csv, transponders.csv, formulation.py   (the inputs)

A sweep folder has ``sweep_summary.csv`` and the run folders in ``runs/``.
EON folders are recognised by ``kind = eon`` in their summary.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

import networkx as nx

from .. import network as netmod
from .. import traffic as trafmod
from ..errors import ResultsError
from ..results import (STATUS_HELP, SOLUTION_STATUSES, _num_row, format_params, new_run_folder,
                       read_csv, write_csv)
from ..validation import Issue
from . import analysis
from . import transponders as tpmod
from .helpers import combination_text, path_length

SUMMARY_FIELDS = [
    "kind", "run_id", "date", "status", "message",
    "algorithm", "algorithm_file", "algorithm_origin", "protection", "regeneration", "parameters",
    "topology", "topology_file", "traffic_file", "transponders_file",
    "num_slots", "slot_width", "sweep_axis", "sweep_value",
    "num_nodes", "num_links", "num_links_up", "num_demands",
    "offered_gbps", "carried_gbps", "blocked_gbps",
    "served_demands", "blocked_demands", "blocked_percent", "unreachable_demands",
    "blocked_spectrum", "blocked_reach", "blocked_disjoint", "blocked_other",
    "lightpaths", "backup_lightpaths", "transponders", "regenerators", "hardware_cost",
    "total_slots_used", "max_slot_index", "spectrum_utilization", "max_link_utilization",
    "avg_path_km", "avg_backup_km",
    "demands_down_avg_cut", "demands_down_worst_cut", "gbps_down_worst_cut", "worst_cut",
    "cut_fibre", "demands_down_cut", "demands_switched_cut", "gbps_down_cut", "served_after_cut",
    "cost_budget", "objective", "time_s", "errors", "warnings", "solution_info", "pynet2plan_version", "run_folder",
]
DEMAND_FIELDS = ["demand_id", "origin", "destination", "rate_gbps", "state", "reason",
                 "lightpaths", "carried_as", "path", "km", "backup_carried_as", "backup_path",
                 "backup_km", "regenerators", "slots_used"]
LIGHTPATH_FIELDS = ["lightpath_id", "demand_id", "origin", "destination", "role", "transponder",
                    "rate_gbps", "slots", "path", "length_km", "regenerators", "starts", "slot_ranges",
                    "max_segment_km", "reach_km"]
LINK_FIELDS = ["origin", "destination", "length", "up", "slots_used", "utilization", "max_slot",
               "lightpaths"]
SPECTRUM_FIELDS = ["origin", "destination", "start", "slots", "lightpath_id", "demand_id",
                   "rate_gbps", "role"]
CUT_FIELDS = ["fibre", "u", "v", "length", "demands_hit", "demands_down", "demands_switched",
              "gbps_down", "down_ids"]
VALIDATION_FIELDS = ["severity", "message"]

#: numeric columns of summary.csv
_SUMMARY_TEXT = {"kind", "run_id", "date", "status", "message", "algorithm", "algorithm_file",
                 "algorithm_origin", "protection", "regeneration", "parameters", "topology",
                 "topology_file", "traffic_file", "transponders_file", "sweep_axis", "worst_cut", "cut_fibre",
                 "solution_info", "pynet2plan_version", "run_folder"}


def _path_text(path) -> str:
    return " > ".join(str(n) for n in path)


def parse_path(text) -> list:
    return [p.strip() for p in str(text).split(" > ")] if text else []


# ----------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------
def build_tables(G, demands: list, solution, table: list, num_slots: int,
                 unreachable=(), blocked_reasons: dict | None = None) -> dict:
    """Every result table + aggregate metrics. ``G`` is the full network
    (failed elements included), ``demands`` the full traffic."""
    types = analysis.by_name(table)
    unreachable = set(unreachable)
    reasons = dict(blocked_reasons or {})
    reasons.update(getattr(solution, "blocked", {}) or {})

    lp_rows, sp_rows = [], []
    occupancy = {(u, v): set() for u, v in G.edges}
    lp_count = {(u, v): 0 for u, v in G.edges}
    for k, lp in enumerate(solution.lightpaths):
        tp = types.get(lp.transponder)
        n = tp.slots if tp else 0
        d_km = path_length(G, lp.path) if all(G.has_edge(*e) for e in lp.links) else None
        segs = lp.segments
        seg_km = [path_length(G, s) for s in segs] if d_km is not None else []
        lp_rows.append(dict(lightpath_id=k, demand_id=lp.demand_id, origin=lp.path[0] if lp.path else "",
                            destination=lp.path[-1] if lp.path else "", role=lp.role,
                            transponder=lp.transponder, rate_gbps=tp.rate if tp else "", slots=n,
                            path=_path_text(lp.path), length_km=round(d_km, 3) if d_km is not None else "",
                            regenerators=";".join(map(str, lp.regenerators)),
                            starts=";".join(map(str, lp.starts)),
                            slot_ranges=";".join(f"{s}-{s + n - 1}" for s in lp.starts),
                            max_segment_km=round(max(seg_km), 3) if seg_km else "",
                            reach_km=tp.reach if tp else ""))
        for seg, start in zip(segs, lp.starts):
            for e in zip(seg[:-1], seg[1:]):
                sp_rows.append(dict(origin=e[0], destination=e[1], start=start, slots=n, lightpath_id=k,
                                    demand_id=lp.demand_id, rate_gbps=tp.rate if tp else "",
                                    role=lp.role))
                if e in occupancy:
                    occupancy[e].update(range(max(0, start), min(num_slots, start + n)))
                    lp_count[e] += 1

    link_rows, utils = [], []
    for u, v, a in G.edges(data=True):
        used = len(occupancy[(u, v)])
        util = used / num_slots if num_slots else 0.0
        if a.get("up", True):
            utils.append(util)
        link_rows.append(dict(origin=u, destination=v, length=a.get("length"), up=a.get("up", True),
                              slots_used=used, utilization=util,
                              max_slot=(max(occupancy[(u, v)]) + 1) if used else 0,
                              lightpaths=lp_count[(u, v)]))

    failed = any(not a.get("up", True) for _, a in G.nodes(data=True)) or \
        any(not a.get("up", True) for _, _, a in G.edges(data=True))
    dem_rows = []
    served = blocked_gbps = carried_gbps = 0
    counts = dict(spectrum=0, reach=0, disjoint=0, other=0)
    km_w, km_b = [], []
    for d in demands:
        work = [lp for lp in solution.lightpaths if lp.demand_id == d.id and not lp.backup]
        back = [lp for lp in solution.lightpaths if lp.demand_id == d.id and lp.backup]
        row = {k: "" for k in DEMAND_FIELDS}
        row.update(demand_id=d.id, origin=d.origin, destination=d.destination, rate_gbps=d.traffic,
                   lightpaths=len(work) + len(back))
        if work:
            state, reason = "SERVED", ""
            served += 1
            carried_gbps += d.traffic
        else:
            state = "UNREACHABLE" if d.id in unreachable else "BLOCKED"
            reason = ("no path (failures)" if failed else "no path") if d.id in unreachable \
                else reasons.get(d.id, "")
            blocked_gbps += d.traffic
            if state == "BLOCKED":
                key = reason if reason in ("spectrum", "reach") else (
                    "disjoint" if "disjoint" in reason else "other")
                counts[key] += 1
        row.update(state=state, reason=reason)

        def describe(lps):
            paths = {tuple(lp.path) for lp in lps}
            p = _path_text(lps[0].path) if len(paths) == 1 else f"{len(paths)} paths"
            km = path_length(G, lps[0].path) if len(paths) == 1 and all(
                G.has_edge(*e) for e in lps[0].links) else None
            return combination_text([lp.transponder for lp in lps]), p, km
        if work:
            row["carried_as"], row["path"], km = describe(work)
            row["km"] = round(km, 3) if km is not None else ""
            if km is not None:
                km_w.append(km)
        if back:
            row["backup_carried_as"], row["backup_path"], km = describe(back)
            row["backup_km"] = round(km, 3) if km is not None else ""
            if km is not None:
                km_b.append(km)
        row["regenerators"] = sum(len(lp.regenerators) for lp in work + back)
        row["slots_used"] = sum(analysis.lightpath_slot_links(lp, table) for lp in work + back)
        dem_rows.append(row)

    cut_rows = analysis.fibre_cuts(G, demands, solution)
    hw = analysis.hardware(solution, table)
    total_slots = sum(len(s) for s in occupancy.values())
    n = len(demands)
    metrics = dict(
        offered_gbps=sum(d.traffic for d in demands), carried_gbps=carried_gbps,
        blocked_gbps=blocked_gbps, served_demands=served, blocked_demands=n - served,
        blocked_percent=round(100.0 * (n - served) / n, 2) if n else 0.0,
        unreachable_demands=len(unreachable),
        blocked_spectrum=counts["spectrum"], blocked_reach=counts["reach"],
        blocked_disjoint=counts["disjoint"], blocked_other=counts["other"],
        lightpaths=sum(1 for lp in solution.lightpaths if not lp.backup),
        backup_lightpaths=sum(1 for lp in solution.lightpaths if lp.backup),
        transponders=hw["transponders"], regenerators=hw["regenerators"],
        hardware_cost=hw["hardware_cost"], total_slots_used=total_slots,
        max_slot_index=max((r["max_slot"] for r in link_rows), default=0),
        spectrum_utilization=(sum(utils) / len(utils)) if utils else 0.0,
        max_link_utilization=max(utils) if utils else 0.0,
        avg_path_km=(sum(km_w) / len(km_w)) if km_w else 0.0,
        avg_backup_km=(sum(km_b) / len(km_b)) if km_b else "",
    )
    metrics.update(analysis.cut_metrics(cut_rows))
    cut = [f for f in analysis.cut_fibres(G) if f[0] in G and f[1] in G]   # cut after planning: what is left
    if cut:
        row = analysis.cut_effect(G, demands, solution, cut)
        metrics.update(cut_fibre=row["fibre"], demands_down_cut=row["demands_down"],
                       demands_switched_cut=row["demands_switched"], gbps_down_cut=row["gbps_down"],
                       served_after_cut=served - row["demands_down"])
    return dict(demands=dem_rows, lightpaths=lp_rows, links=link_rows, spectrum=sp_rows,
                cuts=cut_rows, metrics=metrics)


# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------
def _ghz(s, key):
    """A number of slots of summary ``s`` in GHz (slots × slot width)."""
    try:
        return f"{float(s.get(key)) * float(s.get('slot_width') or 12.5):g}"
    except (TypeError, ValueError):
        return "-"


def _top_slot(s, key="max_slot_index"):
    """``max_slot_index`` counts the slots up to the highest one in use: shown 0-based."""
    v = s.get(key)
    try:
        return int(v) - 1 if int(v) > 0 else "-"
    except (TypeError, ValueError):
        return "-"


def format_report(summary: dict, issues: list | None = None, ghz: bool = False) -> str:
    """The text report of a run; ``ghz``: the spectrum in GHz instead of slots."""
    s = {k: ("" if v is None else v) for k, v in summary.items()}

    def num(key, fmt="{:g}"):
        v = s.get(key, "")
        try:
            return fmt.format(float(v))
        except (TypeError, ValueError):
            return str(v) if v != "" else "-"

    flags = []
    if str(s.get("protection")).upper() in ("TRUE", "YES", "1"):
        flags.append("1+1 protection")
    if str(s.get("regeneration")).upper() in ("TRUE", "YES", "1"):
        flags.append("3R allowed")
    lines = [f"Status:      {s.get('status', '')}   ({STATUS_HELP.get(str(s.get('status')), '')})"]
    if s.get("message"):
        lines.append(f"Message:     {s['message']}")
    lines += [
        "",
        f"Algorithm:   {s.get('algorithm', '')}   [{os.path.basename(str(s.get('algorithm_file', '')))}"
        f"{', ' + str(s['algorithm_origin']) if s.get('algorithm_origin') else ''}]"
        + (f"   ({', '.join(flags)})" if flags else ""),
        f"Parameters:  {s.get('parameters') or '-'}",
        f"Date:        {s.get('date', '')}",
        "",
        f"Topology:    {s.get('topology', '')}  ({s.get('num_nodes', '')} nodes, {s.get('num_links', '')} "
        f"links, {s.get('num_links_up', '')} up)",
        (f"Spectrum:    {_ghz(s, 'num_slots')} GHz per link" if ghz else
         f"Spectrum:    {s.get('num_slots', '')} slots of {num('slot_width')} GHz per link"),
        f"Transponders: {os.path.basename(str(s.get('transponders_file') or '')) or 'table of the run'}",
        f"Traffic:     {s.get('num_demands', '')} demands, {num('offered_gbps')} Gb/s offered",
        "",
        f"Served:      {s.get('served_demands', '-')} demands ({num('carried_gbps')} Gb/s);  blocked "
        f"{s.get('blocked_demands', '-')} ({num('blocked_percent', '{:.1f}')} %, {num('blocked_gbps')} Gb/s)",
        f"             blocking reasons: spectrum {s.get('blocked_spectrum', 0) or 0}, reach "
        f"{s.get('blocked_reach', 0) or 0}, no disjoint path {s.get('blocked_disjoint', 0) or 0}, other "
        f"{s.get('blocked_other', 0) or 0}; unreachable (no path) "
        f"{s.get('unreachable_demands', 0) or 0}",
        f"Hardware:    {s.get('lightpaths', '-')} lightpaths + {s.get('backup_lightpaths', 0) or 0} backup "
        f"-> {s.get('transponders', '-')} transponders (3R included: 2 each), {s.get('regenerators', 0) or 0} × 3R;  "
        f"hardware cost {num('hardware_cost')}",
        (f"Spectrum:    total spectrum used {_ghz(s, 'total_slots_used')} GHz (GHz × links), highest "
         f"frequency in use {_ghz(s, 'max_slot_index')} of {_ghz(s, 'num_slots')} GHz, utilization mean "
         f"{num('spectrum_utilization', '{:.1%}')} / max {num('max_link_utilization', '{:.1%}')}" if ghz else
         f"Spectrum:    total slots used {s.get('total_slots_used', '-')} (slots × links), highest slot "
         f"in use {_top_slot(s)} (slots 0..{_top_slot(s, 'num_slots')}), utilization mean "
         f"{num('spectrum_utilization', '{:.1%}')} / max {num('max_link_utilization', '{:.1%}')}"),
        f"Paths:       mean working path {num('avg_path_km', '{:.0f}')} km"
        + (f", mean backup path {num('avg_backup_km', '{:.0f}')} km" if s.get("avg_backup_km") not in ("", None) else ""),
        *([f"CUT {s['cut_fibre']}:   cut after planning -> {s.get('demands_down_cut')} demands DOWN "
            f"({num('gbps_down_cut')} Gb/s), {s.get('demands_switched_cut')} switched to their backup path; "
            f"{s.get('served_after_cut')} of {s.get('num_demands')} demands still served"]
          if s.get("cut_fibre") else []),
        f"Fibre cuts:  demands down: mean {num('demands_down_avg_cut', '{:.1f}')} per cut, worst "
        f"{s.get('demands_down_worst_cut', '-')}"
        + (f" (cut {s['worst_cut']}, {num('gbps_down_worst_cut')} Gb/s)" if s.get("worst_cut") else ""),
        f"Time:        {num('time_s', '{:.4f}')} s",
    ]
    if issues:
        lines += ["", f"Validation ({len([i for i in issues if i.severity == 'error'])} errors, "
                      f"{len([i for i in issues if i.severity == 'warning'])} warnings):"]
        lines += [f"  {i}" for i in issues]
    elif s.get("status") in SOLUTION_STATUSES:
        lines += ["", "Validation: reach, contiguity, continuity, non-overlap"
                  + (", 1+1 disjointness" if "1+1 protection" in flags else "") + " all satisfied."]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Writing / reading
# ----------------------------------------------------------------------
def write_run(folder: str, summary: dict, tables: dict, issues: list, G, demands: list,
              table: list, formulation_path: str | None = None) -> None:
    os.makedirs(folder, exist_ok=True)
    write_csv(os.path.join(folder, "summary.csv"), SUMMARY_FIELDS, [summary])
    write_csv(os.path.join(folder, "demands.csv"), DEMAND_FIELDS, tables["demands"])
    write_csv(os.path.join(folder, "lightpaths.csv"), LIGHTPATH_FIELDS, tables["lightpaths"])
    write_csv(os.path.join(folder, "links.csv"), LINK_FIELDS, tables["links"])
    write_csv(os.path.join(folder, "spectrum.csv"), SPECTRUM_FIELDS, tables["spectrum"])
    write_csv(os.path.join(folder, "fibre_cuts.csv"), CUT_FIELDS, tables["cuts"])
    write_csv(os.path.join(folder, "validation.csv"), VALIDATION_FIELDS,
              [dict(severity=i.severity, message=i.message) for i in issues])
    with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as f:
        f.write(format_report(summary, issues) + "\n")
    H = G.copy()
    for k in list(H.graph):
        if k.startswith("eon_"):
            H.graph.pop(k)
    netmod.save_topology(H, os.path.join(folder, "topology.json"))
    trafmod.save_traffic(demands, os.path.join(folder, "traffic.csv"),
                         comments=[f"EON traffic (Gb/s) used by run {summary.get('run_id', '')}",
                                   f"original file: {summary.get('traffic_file') or '-'}"])
    tpmod.save_table(table, os.path.join(folder, "transponders.csv"),
                     comments=[f"transponder table used by run {summary.get('run_id', '')}"])
    if formulation_path and os.path.isfile(formulation_path):
        shutil.copyfile(formulation_path, os.path.join(folder, "formulation.py"))


def is_eon_run_folder(folder: str) -> bool:
    p = os.path.join(folder, "summary.csv")
    if not os.path.isfile(p):
        return False
    try:
        rows = read_csv(p)
    except ResultsError:
        return False
    return bool(rows) and rows[0].get("kind") == "eon"


def is_eon_sweep_folder(folder: str) -> bool:
    p = os.path.join(folder, "sweep_summary.csv")
    if not os.path.isfile(p):
        return False
    with open(p, encoding="utf-8-sig") as f:
        head = f.readline()
    return head.startswith("kind,")


@dataclass
class EonRun:
    folder: str
    summary: dict
    demands_table: list
    lightpaths: list
    links: list
    spectrum: list
    cuts: list
    issues: list
    G: nx.DiGraph | None = None
    demands: list = field(default_factory=list)
    table: list = field(default_factory=list)
    report: str = ""

    @property
    def title(self) -> str:
        s = self.summary
        return f"{s.get('algorithm', '?')} on {s.get('topology', '?')} - {s.get('status', '?')}"

    @property
    def num_slots(self) -> int:
        try:
            n = self.summary.get("num_slots")
            return 320 if n in (None, "") else int(n)       # 0 slots is a valid run
        except (TypeError, ValueError):
            return 320

    def lightpaths_of(self, demand_id) -> list:
        return [r for r in self.lightpaths if str(r.get("demand_id")) == str(demand_id)]


def load_run(folder: str) -> EonRun:
    folder = os.path.abspath(folder)
    if not is_eon_run_folder(folder):
        raise ResultsError(f"'{folder}' is not an EON run folder (summary.csv with kind=eon is missing).")
    summary = read_csv(os.path.join(folder, "summary.csv"))[0]
    summary = _num_row(summary, [k for k in SUMMARY_FIELDS if k not in _SUMMARY_TEXT])
    dem = [_num_row(r, ["demand_id", "rate_gbps", "lightpaths", "km", "backup_km", "regenerators",
                        "slots_used"]) for r in read_csv(os.path.join(folder, "demands.csv"))]
    lps = [_num_row(r, ["lightpath_id", "demand_id", "rate_gbps", "slots", "length_km",
                        "max_segment_km", "reach_km"]) for r in read_csv(os.path.join(folder, "lightpaths.csv"))]
    links = [_num_row(r, ["length", "slots_used", "utilization", "max_slot", "lightpaths"])
             for r in read_csv(os.path.join(folder, "links.csv"))]
    for l in links:
        l["up"] = str(l.get("up", "TRUE")).upper() != "FALSE"
    spec = [_num_row(r, ["start", "slots", "lightpath_id", "demand_id", "rate_gbps"])
            for r in read_csv(os.path.join(folder, "spectrum.csv"))]
    cuts = [_num_row(r, ["length", "demands_hit", "demands_down", "demands_switched", "gbps_down"])
            for r in read_csv(os.path.join(folder, "fibre_cuts.csv"))]
    issues = [Issue(r.get("severity", "warning"), r.get("message", ""))
              for r in read_csv(os.path.join(folder, "validation.csv"))]
    for name, rows, cols in (("demands.csv", dem, ("demand_id", "origin", "destination", "state")),
                             ("lightpaths.csv", lps, ("lightpath_id", "demand_id", "path", "transponder")),
                             ("links.csv", links, ("origin", "destination", "slots_used")),
                             ("spectrum.csv", spec, ("origin", "destination", "start", "slots")),
                             ("fibre_cuts.csv", cuts, ("fibre", "u", "v", "demands_down"))):
        missing = [c for c in cols if rows and c not in rows[0]]
        if missing:
            raise ResultsError(f"{name} of the run has no column {', '.join(missing)}: the file was changed "
                               f"(e.g. saved again by Excel with ';'). Run the algorithm again.")
    G = None
    topo = os.path.join(folder, "topology.json")
    if os.path.isfile(topo):
        try:
            G = netmod.load_topology(topo)
        except Exception as e:  # noqa: BLE001
            raise ResultsError(f"topology.json of the run cannot be read: {e}") from None
    demands = []
    if os.path.isfile(os.path.join(folder, "traffic.csv")):
        try:
            demands = trafmod.load_traffic(os.path.join(folder, "traffic.csv"))
        except Exception:  # noqa: BLE001
            demands = []
    table = []
    if os.path.isfile(os.path.join(folder, "transponders.csv")):
        try:
            sw = float(summary.get("slot_width") or tpmod.DEFAULT_SLOT_WIDTH)
            table = tpmod.load_table(os.path.join(folder, "transponders.csv"), slot_width=sw)
        except Exception:  # noqa: BLE001
            table = []
    return EonRun(folder, summary, dem, lps, links, spec, cuts, issues, G, demands, table,
                  format_report(summary, issues))


@dataclass
class EonSweep:
    folder: str
    rows: list

    def run_folder(self, row: dict) -> str | None:
        rel = row.get("run_folder") or ""
        p = os.path.join(self.folder, rel) if rel else ""
        return p if rel and is_eon_run_folder(p) else None


def load_sweep(folder: str) -> EonSweep:
    folder = os.path.abspath(folder)
    if not is_eon_sweep_folder(folder):
        raise ResultsError(f"'{folder}' is not an EON sweep folder.")
    rows = [_num_row(r, [k for k in SUMMARY_FIELDS if k not in _SUMMARY_TEXT])
            for r in read_csv(os.path.join(folder, "sweep_summary.csv"))]
    return EonSweep(folder, rows)


def list_runs(root: str, limit: int | None = None) -> list:
    """EON runs and sweeps found in ``root`` (newest first)."""
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        try:
            if is_eon_sweep_folder(p):
                rows = read_csv(os.path.join(p, "sweep_summary.csv"))
                first = rows[0] if rows else {}
                algos = sorted({r.get("algorithm", "") for r in rows})
                out.append(dict(kind="sweep", folder=p, date=first.get("date", ""),
                                algorithm=", ".join(algos), topology=first.get("topology", ""),
                                status=f"{len(rows)} runs", served=""))
            elif is_eon_run_folder(p):
                r = read_csv(os.path.join(p, "summary.csv"))[0]
                out.append(dict(kind="run", folder=p, date=r.get("date", ""),
                                algorithm=r.get("algorithm", ""), topology=r.get("topology", ""),
                                status=r.get("status", ""),
                                served=f"{r.get('served_demands', '')}/{r.get('num_demands', '')}"))
        except (ResultsError, OSError, IndexError):
            continue
    out.sort(key=lambda it: (str(it.get("date") or ""), os.path.getmtime(it["folder"])), reverse=True)
    return out[:limit] if limit else out


__all__ = ["build_tables", "format_report", "write_run", "load_run", "load_sweep", "list_runs",
           "is_eon_run_folder", "is_eon_sweep_folder", "EonRun", "EonSweep", "SUMMARY_FIELDS",
           "format_params", "parse_path"]
