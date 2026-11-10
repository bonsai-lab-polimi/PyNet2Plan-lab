"""
pynet2plan.validation
====================

An independent checker for the solutions returned by the algorithms.

The runner always validates a solution *before* saving it, so a formulation
that "solves" but is wrong (for example because a constraint is missing)
is reported as INVALID instead of silently producing nonsense. Typical
messages are::

    Link Madrid->Zaragoza carries 46 wavelengths but its capacity is 40.
    Demand 3 (Madrid->Sevilla) carries 2 of the 5 requested wavelengths.
    Demand 7 is split over 2 paths, but this formulation must not split traffic.
    Wavelength 4 is used by 2 routes on link Valencia->Murcia (demands 1, 9).
    Route #3 (demand 2): the path A > B > C is 1210 km long, but the optical reach is 1000 km.

A link may contain several fibers (attribute ``fibers``): its capacity is then
fibers x wavelengths per fiber, and with wavelength continuity a wavelength
may be used on the link once per fiber.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .network import link_label, optical_reach, path_fibres, path_length, total_capacity
from .solution import Solution

_EPS = 1e-6
MAX_MESSAGES = 60


@dataclass
class Issue:
    severity: str   # "error" or "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.message}"


def validate_solution(G: nx.DiGraph, demands: list, solution: Solution, *,
                      splittable: bool = True, allows_blocking: bool = False,
                      wavelength_continuity: bool = False, protection: bool = False) -> list:
    """Check ``solution`` against the network ``G`` (the up links only) and the
    ``demands`` that were given to the algorithm. Returns a list of
    :class:`Issue` (errors make the solution INVALID; warnings do not)."""
    errors: list = []
    warnings: list = []
    by_id = {d.id: d for d in demands}
    reach = optical_reach(G)
    fractional = []

    def err(msg):
        errors.append(msg)

    # ---------------- routes ----------------
    for k, r in enumerate(solution.routes):
        where = f"Route #{k + 1} (demand {r.demand_id})"
        d = by_id.get(r.demand_id)
        if d is None:
            err(f"{where}: there is no demand with id {r.demand_id}.")
            continue
        if len(r.path) < 2:
            err(f"{where}: the path {r.path} has less than 2 nodes.")
            continue
        if r.path[0] != d.origin or r.path[-1] != d.destination:
            err(f"{where}: the path {r.path_str()} should go from {d.origin} to {d.destination}.")
        for (i, j) in r.links:
            if not G.has_edge(i, j):
                err(f"{where}: the path uses the link {link_label(i, j)}, which does not "
                    f"exist (or is down).")
        regs = list(r.regenerators or [])
        bad = [n for n in regs if n not in r.path[1:-1]]
        if bad:
            err(f"{where}: a 3R regenerator in {bad[0]}, which is not an intermediate node of the "
                f"path {r.path_str()}.")
        elif reach is not None and all(G.has_edge(i, j) for (i, j) in r.links):
            cuts = sorted({r.path.index(n, 1) for n in regs})        # regenerated in these nodes
            for a, b in zip([0] + cuts, cuts + [len(r.path) - 1]):
                km = path_length(G, r.path[a:b + 1])
                if km > reach + 1e-9:
                    what = (f"path {r.path_str()}" if not regs else
                            f"stretch {r.path[a]} > ... > {r.path[b]} of the path {r.path_str()}")
                    err(f"{where}: the {'backup ' if r.backup else ''}{what} is {km:.0f} km long, "
                        f"but the optical reach is {reach:g} km: "
                        + ("use only paths within the reach (no 3R regenerators)." if not regs else
                           "a 3R regenerator is missing on the way."))
                    break
        if len(set(r.path)) != len(r.path):
            warnings.append(f"{where}: the path {r.path_str()} visits a node twice (loop).")
        if r.traffic < 0:
            err(f"{where}: negative traffic {r.traffic}.")
        if not float(r.traffic).is_integer():
            fractional.append(r)
        if r.wavelengths is not None:
            if not float(r.traffic).is_integer() or len(r.wavelengths) != int(r.traffic):
                err(f"{where}: carries {r.traffic} wavelengths but lists "
                    f"{len(r.wavelengths)} wavelength indices {r.wavelengths}.")
            if len(set(r.wavelengths)) != len(r.wavelengths):
                err(f"{where}: the same wavelength index is listed twice in {r.wavelengths}.")
            for w in r.wavelengths:
                if w < 0:
                    err(f"{where}: invalid wavelength index {w} (indices start at 0).")
                    continue
                for (i, j) in r.links:
                    if G.has_edge(i, j) and w >= G.edges[i, j]["capacity"]:
                        err(f"{where}: wavelength {w} does not exist on link {link_label(i, j)} "
                            f"({G.edges[i, j]['capacity']} wavelengths per fiber: indices 0.."
                            f"{G.edges[i, j]['capacity'] - 1}).")
        elif wavelength_continuity:
            err(f"{where}: no wavelengths assigned, but this formulation must assign them "
                f"(use sol.add_route(..., wavelengths=[...])).")
    if fractional:
        warnings.append(f"{len(fractional)} route(s) carry a fractional number of wavelengths "
                        f"(e.g. {fractional[0].traffic:g}): is the model continuous (LP relaxation)?")

    # ---------------- demands ----------------
    # working and backup routes are counted separately: a 1+1-protected demand
    # carries its wavelengths once on the working path and once on the backup.
    work_c: dict = {}
    back_c: dict = {}
    work_paths: dict = {}
    back_paths: dict = {}
    work_fib: dict = {}
    back_fib: dict = {}
    for r in solution.routes:
        c, paths, fib = (back_c, back_paths, back_fib) if r.backup else (work_c, work_paths, work_fib)
        c[r.demand_id] = c.get(r.demand_id, 0) + r.traffic
        paths.setdefault(r.demand_id, set()).add(tuple(r.path))
        fib.setdefault(r.demand_id, set()).update(path_fibres(r.path))
    for d in demands:
        name = f"Demand {d.id} ({d.origin}->{d.destination})"
        cw = work_c.get(d.id, 0)
        if cw > d.traffic + _EPS:
            err(f"{name} carries {cw:g} wavelengths but requested only {d.traffic}: it was routed "
                f"more than once (in a heuristic: stop after the first path that fits).")
        elif cw < d.traffic - _EPS and not allows_blocking:
            err(f"{name} carries {cw:g} of the {d.traffic} requested wavelengths.")
        if not splittable and len(work_paths.get(d.id, ())) > 1:
            err(f"{name} is split over {len(work_paths[d.id])} paths, but this formulation "
                f"must not split traffic.")
        if protection and cw > _EPS:        # served: it needs a full, fibre-disjoint backup
            cb = back_c.get(d.id, 0)
            if cb < d.traffic - _EPS:
                err(f"{name} is served but its backup path carries {cb:g} of the {d.traffic} "
                    f"wavelengths: 1+1 protection needs a full backup.")
            shared = work_fib.get(d.id, set()) & back_fib.get(d.id, set())
            if shared:
                u, v = sorted(shared)[0]
                err(f"{name}: the working and backup paths share the fibre {u}-{v}; a single cut "
                    f"would take both down (the backup must be fibre-disjoint).")
            if not splittable and len(back_paths.get(d.id, ())) > 1:
                err(f"{name}: the backup is split over {len(back_paths[d.id])} paths.")
        elif not protection and back_c.get(d.id):
            err(f"{name} has a backup route, but this formulation is not declared as 1+1 "
                f"(set PROTECTION = True to use backup routes).")

    # ---------------- links ----------------
    for (i, j), used in solution.link_occupancy().items():
        if G.has_edge(i, j):
            cap = total_capacity(G, i, j)
            if used > cap + _EPS:
                fibers = G.edges[i, j].get("fibers", 1)
                detail = "" if fibers == 1 else f" ({fibers} fibers x {G.edges[i, j]['capacity']})"
                err(f"Link {link_label(i, j)} carries {used:g} wavelengths but its capacity "
                    f"is {cap}{detail}.")

    # ---------------- wavelength clashes ----------------
    for (i, j, w), users in sorted(solution.wavelength_usage().items(), key=lambda t: str(t[0])):
        fibers = G.edges[i, j].get("fibers", 1) if G.has_edge(i, j) else 1
        if len(users) > fibers:
            where = "" if fibers == 1 else f" (which has only {fibers} fibers)"
            err(f"Wavelength {w} is used by {len(users)} routes on link {link_label(i, j)}{where} "
                f"(demands {', '.join(str(u) for u in users)}).")

    # ---------------- objective ----------------
    if solution.objective is not None:
        try:
            obj = float(solution.objective)
            wl = float(solution.wavelength_links())
            if abs(obj - wl) > 1e-4 * (1 + abs(wl)):
                warnings.append(
                    f"The objective reported by the formulation ({obj:g}) differs from the "
                    f"total wavelengths used, recomputed from the routes ({wl:g}). That is fine "
                    f"if your objective measures something else; otherwise check it.")
        except (TypeError, ValueError):
            warnings.append(f"The objective value {solution.objective!r} is not a number.")

    issues = [Issue("error", m) for m in errors] + [Issue("warning", m) for m in warnings]
    if len(issues) > MAX_MESSAGES:
        extra = len(issues) - MAX_MESSAGES
        issues = issues[:MAX_MESSAGES] + [Issue("error" if errors else "warning",
                                                f"... and {extra} more issue(s).")]
    return issues


def has_errors(issues: list) -> bool:
    return any(i.severity == "error" for i in issues)
