"""
pynet2plan.results
=================

Every run is saved in its own folder, made only of CSV files plus a copy of
the inputs, so that it can be re-opened in the GUI, loaded in pandas/Excel,
or handed in::

    results/2026-10-02_14-30-05_unsplittable_flow_spain-7/
        summary.csv        one row: algorithm, parameters, status, objective, time, ...
        links.csv          link occupancy: fibers, wavelengths per fiber, capacity
                           (= fibers x wavelengths per fiber), used, free, utilization
        routes.csv         one row per route: demand, path, wavelengths carried
        demands.csv        per demand: offered, carried, blocked
        wavelengths.csv    (only with wavelength assignment) link, wavelength, demand
        validation.csv     problems found by the solution checker
        report.txt         a human-readable summary
        topology.json      the network used (exact copy, including failures)
        traffic.csv        the traffic matrix used
        formulation.py     the algorithm file used

A *sweep* folder contains ``sweep_summary.csv`` (one row per run, plus the
``capacity`` swept) and the run folders in ``runs/``.

Reading back::

    from pynet2plan.results import load_run
    run = load_run("results/2026-...")
    run.summary["objective"], run.links[0]["utilization"], run.G, run.demands
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
import re
import shutil
from dataclasses import dataclass, field

import networkx as nx

from . import network as netmod
from . import traffic as trafmod
from .errors import ResultsError
from .validation import Issue

SUMMARY_FIELDS = [
    "run_id", "date", "status", "message",
    "algorithm", "algorithm_file", "algorithm_origin", "parameters",
    "topology", "topology_file", "traffic_file", "capacity",
    "num_nodes", "num_links", "num_links_up", "num_demands",
    "objective", "wavelength_links", "time_s", "time_std_s", "time_runs",
    "solver", "solver_status", "num_variables", "num_constraints",
    "offered_traffic", "carried_traffic", "blocked_traffic",
    "blocked_demands", "unreachable_demands",
    "max_utilization", "avg_utilization", "saturated_links", "unused_links",
    "avg_hops", "max_hops", "avg_route_km", "split_demands", "wavelengths_needed",
    "errors", "warnings", "solution_info", "pynet2plan_version", "run_folder",
]
LINK_FIELDS = ["origin", "destination", "fibers", "wavelengths_per_fiber", "capacity", "used",
               "free", "utilization", "length", "up", "num_demands"]
ROUTE_FIELDS = ["demand_id", "origin", "destination", "route_id", "traffic", "hops",
                "length_km", "path", "wavelengths"]
DEMAND_FIELDS = ["demand_id", "origin", "destination", "offered", "carried", "blocked",
                 "num_routes", "state"]
WAVELENGTH_FIELDS = ["origin", "destination", "wavelength", "demand_id"]
VALIDATION_FIELDS = ["severity", "message"]

#: statuses for which a solution exists (and a run folder is written)
SOLUTION_STATUSES = ("OPTIMAL", "FEASIBLE", "BLOCKING", "INVALID")

STATUS_HELP = {
    "OPTIMAL": "The solver proved that the solution is optimal.",
    "FEASIBLE": "Valid solution, optimality not proven (heuristic, or time limit reached).",
    "BLOCKING": "Valid solution, but some traffic could not be routed (blocked).",
    "INVALID": "The algorithm returned a solution that violates the constraints.",
    "INFEASIBLE": "No routing satisfies the constraints (e.g. capacity too small).",
    "UNBOUNDED": "The ILP objective is unbounded: a constraint is missing.",
    "TIME_LIMIT": "No solution was found within the time limit.",
    "NOT_COMPLETED": "The formulation still contains a TODO placeholder.",
    "ERROR": "The algorithm crashed or could not be loaded.",
}


def _fmt(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.6g}" if abs(v) >= 1e-3 or v == 0 else f"{v:.3e}"
    if v is None:
        return ""
    return str(v)


def _slug(text: str, maxlen: int = 32) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return (s[:maxlen].strip("-")) or "network"


def format_params(params: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in params.items())


def parse_params(text: str) -> dict:
    """Inverse of format_params (values are returned as strings)."""
    out = {}
    for part in (text or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ----------------------------------------------------------------------
# Building the tables
# ----------------------------------------------------------------------
def build_tables(G: nx.DiGraph, demands: list, solution, unreachable: list = ()) -> dict:
    """Compute every result table + aggregate metrics from a solution.

    ``G`` is the full network (including failed elements), ``demands`` the
    full traffic matrix, ``unreachable`` the ids of demands that could not be
    routed at all because of failures.
    """
    occ = solution.link_occupancy() if solution is not None else {}
    users: dict = {}
    if solution is not None:
        for r in solution.routes:
            for e in r.links:
                users.setdefault(e, set()).add(r.demand_id)

    links = []
    utils = []
    for u, v, a in G.edges(data=True):
        fibers = a.get("fibers", 1)
        cap = fibers * a.get("capacity", 0)
        used = occ.get((u, v), 0)
        util = (used / cap) if cap > 0 else (0.0 if used == 0 else None)
        if a.get("up", True) and util is not None:
            utils.append(util)
        links.append(dict(origin=u, destination=v, fibers=fibers,
                          wavelengths_per_fiber=a.get("capacity", 0), capacity=cap,
                          used=used, free=cap - used,
                          utilization=util, length=a.get("length"), up=a.get("up", True),
                          num_demands=len(users.get((u, v), ()))))

    by_id = {d.id: d for d in demands}
    routes = []
    hops_w, km_w, carried_total = 0.0, 0.0, 0.0
    max_hops = 0
    max_wl = None
    if solution is not None:
        for k, r in enumerate(solution.routes):
            d = by_id.get(r.demand_id)
            km = 0.0
            for (i, j) in r.links:
                if G.has_edge(i, j):
                    km += float(G.edges[i, j].get("length") or 0)
            routes.append(dict(demand_id=r.demand_id,
                               origin=d.origin if d else "", destination=d.destination if d else "",
                               route_id=k, traffic=r.traffic, hops=r.hops, length_km=round(km, 3),
                               path=r.path_str(),
                               wavelengths=";".join(str(w) for w in r.wavelengths) if r.wavelengths else ""))
            hops_w += r.traffic * r.hops
            km_w += r.traffic * km
            carried_total += r.traffic
            max_hops = max(max_hops, r.hops)
            if r.wavelengths:
                max_wl = max([max_wl or 0] + [w + 1 for w in r.wavelengths])

    carried = solution.carried() if solution is not None else {}
    nroutes: dict = {}
    split = 0
    if solution is not None:
        paths: dict = {}
        for r in solution.routes:
            nroutes[r.demand_id] = nroutes.get(r.demand_id, 0) + 1
            paths.setdefault(r.demand_id, set()).add(tuple(r.path))
        split = sum(1 for p in paths.values() if len(p) > 1)
    unreachable = set(unreachable)
    dem_rows = []
    blocked_dem = 0
    blocked_total = 0
    for d in demands:
        c = carried.get(d.id, 0)
        if d.id in unreachable:
            state = "UNREACHABLE"
        elif c >= d.traffic - 1e-6:
            state = "ROUTED"
        elif c > 1e-6:
            state = "PARTIAL"
        else:
            state = "BLOCKED"
        if state != "ROUTED":
            blocked_dem += 1
        blocked_total += max(0, d.traffic - c)
        dem_rows.append(dict(demand_id=d.id, origin=d.origin, destination=d.destination,
                             offered=d.traffic, carried=c, blocked=max(0, d.traffic - c),
                             num_routes=nroutes.get(d.id, 0), state=state))

    wl_rows = []
    if solution is not None and solution.has_wavelengths():
        for (i, j, w), ids in sorted(solution.wavelength_usage().items(),
                                     key=lambda t: (str(t[0][0]), str(t[0][1]), t[0][2])):
            for did in ids:
                wl_rows.append(dict(origin=i, destination=j, wavelength=w, demand_id=did))

    offered = sum(d.traffic for d in demands)
    up_links = [l for l in links if l["up"]]
    metrics = dict(
        offered_traffic=offered,
        carried_traffic=carried_total,
        blocked_traffic=blocked_total,
        blocked_demands=blocked_dem,
        unreachable_demands=len(unreachable),
        wavelength_links=hops_w,
        max_utilization=max(utils) if utils else 0.0,
        avg_utilization=(sum(utils) / len(utils)) if utils else 0.0,
        saturated_links=sum(1 for l in up_links if l["capacity"] > 0 and l["used"] >= l["capacity"] - 1e-6),
        unused_links=sum(1 for l in up_links if l["used"] <= 1e-9),
        avg_hops=(hops_w / carried_total) if carried_total else 0.0,
        max_hops=max_hops,
        avg_route_km=(km_w / carried_total) if carried_total else 0.0,
        split_demands=split,
        wavelengths_needed=max_wl if max_wl is not None else "",
    )
    return dict(links=links, routes=routes, demands=dem_rows, wavelengths=wl_rows, metrics=metrics)


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def write_csv(path: str, fields: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in fields})


def new_run_folder(root: str, algorithm_stem: str, topology_name: str,
                   when: _dt.datetime | None = None) -> str:
    when = when or _dt.datetime.now()
    base = f"{when:%Y-%m-%d_%H-%M-%S}_{_slug(algorithm_stem, 28)}_{_slug(topology_name, 24)}"
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, base)
    k = 2
    while os.path.exists(path):
        path = os.path.join(root, f"{base}_{k}")
        k += 1
    os.makedirs(path)
    return path


def format_report(summary: dict, issues: list | None = None) -> str:
    """The human readable report shown in the GUI and saved as report.txt."""
    s = {k: ("" if v is None else v) for k, v in summary.items()}

    def num(key, fmt="{:g}"):
        v = s.get(key, "")
        try:
            return fmt.format(float(v))
        except (TypeError, ValueError):
            return str(v) if v != "" else "-"

    lines = [
        f"Status:      {s.get('status', '')}   ({STATUS_HELP.get(str(s.get('status')), '')})",
    ]
    if s.get("message"):
        lines.append(f"Message:     {s['message']}")
    lines += [
        "",
        f"Algorithm:   {s.get('algorithm', '')}   [{os.path.basename(str(s.get('algorithm_file', '')))}"
        f"{', ' + str(s['algorithm_origin']) if s.get('algorithm_origin') else ''}]",
        f"Parameters:  {s.get('parameters') or '-'}",
        f"Date:        {s.get('date', '')}",
        "",
        f"Topology:    {s.get('topology', '')}  ({s.get('num_nodes', '')} nodes, "
        f"{s.get('num_links', '')} links, {s.get('num_links_up', '')} up)"
        + (f"   uniform capacity {s['capacity']}" if s.get("capacity") not in ("", None) else ""),
        f"Traffic:     {s.get('num_demands', '')} demands, {num('offered_traffic')} wavelengths offered",
        "",
        f"Objective (reported by the algorithm):  {num('objective')}",
        f"Wavelengths used, summed over links:    {num('wavelength_links')}",
        f"Computation time:                       {num('time_s', '{:.4f}')} s",
        f"Solver:  {s.get('solver') or '-'}  status {s.get('solver_status') or '-'}  "
        f"({s.get('num_variables') or '-'} variables, {s.get('num_constraints') or '-'} constraints)",
        "",
        f"Carried traffic:   {num('carried_traffic')} of {num('offered_traffic')} wavelengths "
        f"(blocked {num('blocked_traffic')}; demands not fully routed: {s.get('blocked_demands', 0) or 0}, "
        f"of which unreachable because of failures: {s.get('unreachable_demands', 0) or 0})",
        f"Link utilization:  max {num('max_utilization', '{:.1%}')}, mean {num('avg_utilization', '{:.1%}')}, "
        f"{s.get('saturated_links', '-')} saturated, {s.get('unused_links', '-')} unused",
        f"Routes:            mean {num('avg_hops', '{:.2f}')} hops (max {s.get('max_hops', '-')}), "
        f"mean length {num('avg_route_km', '{:.1f}')} km, {s.get('split_demands', 0) or 0} demands split "
        f"over several paths",
    ]
    if s.get("wavelengths_needed") not in ("", None):
        lines.append(f"Wavelengths needed:  {s['wavelengths_needed']}  (indices 0..{int(s['wavelengths_needed']) - 1} used)")
    if issues:
        lines += ["", f"Validation ({len([i for i in issues if i.severity == 'error'])} errors, "
                      f"{len([i for i in issues if i.severity == 'warning'])} warnings):"]
        lines += [f"  {i}" for i in issues]
    elif s.get("status") in SOLUTION_STATUSES:
        lines += ["", "Validation: the solution satisfies all the constraints."]
    return "\n".join(lines)


def write_run(folder: str, summary: dict, tables: dict, issues: list, G: nx.DiGraph,
              demands: list, formulation_path: str | None = None) -> None:
    """Write all the files of a run folder."""
    os.makedirs(folder, exist_ok=True)
    write_csv(os.path.join(folder, "summary.csv"), SUMMARY_FIELDS, [summary])
    write_csv(os.path.join(folder, "links.csv"), LINK_FIELDS, tables["links"])
    write_csv(os.path.join(folder, "routes.csv"), ROUTE_FIELDS, tables["routes"])
    write_csv(os.path.join(folder, "demands.csv"), DEMAND_FIELDS, tables["demands"])
    if tables["wavelengths"]:
        write_csv(os.path.join(folder, "wavelengths.csv"), WAVELENGTH_FIELDS, tables["wavelengths"])
    write_csv(os.path.join(folder, "validation.csv"), VALIDATION_FIELDS,
              [dict(severity=i.severity, message=i.message) for i in issues])
    with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as f:
        f.write(format_report(summary, issues) + "\n")
    netmod.save_topology(G, os.path.join(folder, "topology.json"))
    trafmod.save_traffic(demands, os.path.join(folder, "traffic.csv"),
                         comments=[f"traffic used by run {summary.get('run_id', '')}",
                                   f"original file: {summary.get('traffic_file') or '-'}"])
    if formulation_path and os.path.isfile(formulation_path):
        shutil.copyfile(formulation_path, os.path.join(folder, "formulation.py"))


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
def read_csv(path: str) -> list:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [dict(r) for r in csv.DictReader(f)]
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        raise ResultsError(f"Cannot read {os.path.basename(path)}: {e}") from None


def _read_checked(folder: str, name: str, required: list) -> list:
    """Rows of a CSV of a run folder; ResultsError if required columns are missing."""
    path = os.path.join(folder, name)
    rows = read_csv(path)
    if os.path.isfile(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
        missing = [c for c in required if c not in header]
        if missing:
            raise ResultsError(f"{name} is not a valid PyNet2Plan file: missing column(s) "
                               f"{', '.join(missing)} (was it re-saved with another separator?).")
    return rows


def to_number(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f.is_integer() and "." not in str(v) and "e" not in str(v).lower() else f


def _num_row(row: dict, keys) -> dict:
    out = dict(row)
    for k in keys:
        if k in out:
            out[k] = to_number(out[k], out[k])
    return out


@dataclass
class RunResults:
    folder: str
    summary: dict
    links: list
    routes: list
    demands_table: list
    wavelengths: list
    issues: list
    G: nx.DiGraph | None = None
    demands: list = field(default_factory=list)
    report: str = ""

    @property
    def title(self) -> str:
        s = self.summary
        return f"{s.get('algorithm', '?')} on {s.get('topology', '?')} - {s.get('status', '?')}"

    def routes_of(self, demand_id) -> list:
        return [r for r in self.routes if str(r.get("demand_id")) == str(demand_id)]

    def routes_through(self, origin, destination) -> list:
        out = []
        for r in self.routes:
            p = parse_path(r.get("path", ""))
            if any(a == origin and b == destination for a, b in zip(p[:-1], p[1:])):
                out.append(r)
        return out


def parse_path(text: str) -> list:
    return [p.strip() for p in str(text).split(" > ")] if text else []


def is_run_folder(folder: str) -> bool:
    return os.path.isfile(os.path.join(folder, "summary.csv"))


def is_sweep_folder(folder: str) -> bool:
    return os.path.isfile(os.path.join(folder, "sweep_summary.csv"))


def load_run(folder: str) -> RunResults:
    """Read a run folder written by :func:`write_run`."""
    folder = os.path.abspath(folder)
    if not is_run_folder(folder):
        raise ResultsError(f"'{folder}' is not a PyNet2Plan run folder (summary.csv is missing).")
    rows = read_csv(os.path.join(folder, "summary.csv"))
    if not rows:
        raise ResultsError("summary.csv is empty.")
    summary = _num_row(rows[0], [k for k in SUMMARY_FIELDS if k not in (
        "run_id", "date", "status", "message", "algorithm", "algorithm_file", "algorithm_origin",
        "parameters", "topology", "topology_file", "traffic_file", "solver", "solver_status",
        "solution_info", "pynet2plan_version", "run_folder")])
    links = [_num_row(r, ["fibers", "wavelengths_per_fiber", "capacity", "used", "free",
                          "utilization", "length", "num_demands"])
             for r in _read_checked(folder, "links.csv", ["origin", "destination", "capacity", "used"])]
    for l in links:
        l["up"] = str(l.get("up", "TRUE")).upper() != "FALSE"
        if l.get("fibers") in (None, ""):                 # run folders of older versions
            l["fibers"], l["wavelengths_per_fiber"] = 1, l.get("capacity")
    routes = [_num_row(r, ["demand_id", "route_id", "traffic", "hops", "length_km"])
              for r in _read_checked(folder, "routes.csv", ["demand_id", "path", "traffic"])]
    dem = [_num_row(r, ["demand_id", "offered", "carried", "blocked", "num_routes"])
           for r in _read_checked(folder, "demands.csv", ["demand_id", "origin", "destination"])]
    wl = [_num_row(r, ["wavelength", "demand_id"])
          for r in _read_checked(folder, "wavelengths.csv", ["origin", "destination", "wavelength", "demand_id"])]
    issues = [Issue(r.get("severity", "warning"), r.get("message", ""))
              for r in read_csv(os.path.join(folder, "validation.csv"))]
    G = None
    demands = []
    topo = os.path.join(folder, "topology.json")
    if os.path.isfile(topo):
        try:
            G = netmod.load_topology(topo)
        except Exception as e:  # noqa: BLE001
            raise ResultsError(f"topology.json of the run cannot be read: {e}") from None
    else:
        # rebuild a minimal network from links.csv
        G = nx.DiGraph(name=str(summary.get("topology", "network")))
        for l in links:
            G.add_edge(l["origin"], l["destination"], capacity=l.get("wavelengths_per_fiber", 0) or 0,
                       fibers=l.get("fibers", 1) or 1, length=l.get("length", 1) or 1, up=l["up"])
        netmod.normalize(G)
    tfile = os.path.join(folder, "traffic.csv")
    if os.path.isfile(tfile):
        try:
            demands = trafmod.load_traffic(tfile)
        except Exception:  # noqa: BLE001
            demands = []
    report = format_report(summary, issues)
    return RunResults(folder, summary, links, routes, dem, wl, issues, G, demands, report)


@dataclass
class SweepResults:
    folder: str
    rows: list

    def run_folder(self, row: dict) -> str | None:
        rel = row.get("run_folder") or ""
        if not rel:
            return None
        p = os.path.join(self.folder, rel)
        return p if is_run_folder(p) else None


def load_sweep(folder: str) -> SweepResults:
    folder = os.path.abspath(folder)
    if not is_sweep_folder(folder):
        raise ResultsError(f"'{folder}' is not a sweep folder (sweep_summary.csv is missing).")
    rows = [_num_row(r, ["capacity", "objective", "wavelength_links", "time_s", "time_std_s",
                         "time_runs", "num_variables",
                         "num_constraints", "carried_traffic", "blocked_traffic", "max_utilization",
                         "avg_utilization"])
            for r in read_csv(os.path.join(folder, "sweep_summary.csv"))]
    return SweepResults(folder, rows)


def list_runs(root: str, limit: int | None = None) -> list:
    """Summaries of the runs and sweeps found in ``root`` (newest first).

    Each item is a dict with ``kind`` ('run' or 'sweep'), ``folder`` and the
    summary fields."""
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        try:
            if is_sweep_folder(p):
                rows = read_csv(os.path.join(p, "sweep_summary.csv"))
                ok = sum(1 for r in rows if r.get("status") in ("OPTIMAL", "FEASIBLE"))
                first = rows[0] if rows else {}
                algos = sorted({r.get("algorithm", "") for r in rows})
                out.append(dict(kind="sweep", folder=p, date=first.get("date", ""),
                                algorithm=", ".join(algos), topology=first.get("topology", ""),
                                status=f"{len(rows)} runs, {ok} feasible", objective="",
                                time_s=""))
            elif is_run_folder(p):
                rows = read_csv(os.path.join(p, "summary.csv"))
                r = rows[0] if rows else {}
                out.append(dict(kind="run", folder=p, date=r.get("date", ""),
                                algorithm=r.get("algorithm", ""), topology=r.get("topology", ""),
                                status=r.get("status", ""), objective=r.get("objective", ""),
                                time_s=r.get("time_s", "")))
        except ResultsError:
            continue
    out.sort(key=lambda it: (str(it.get("date") or ""), os.path.getmtime(it["folder"])), reverse=True)
    return out[:limit] if limit else out
