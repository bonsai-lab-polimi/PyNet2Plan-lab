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

A link may contain several fibers (attribute ``fibers``): its capacity is then
fibers x wavelengths per fiber, and with wavelength continuity a wavelength
may be used on the link once per fiber.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .network import link_label, total_capacity
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
                      wavelength_continuity: bool = False) -> list:
    """Check ``solution`` against the network ``G`` (the up links only) and the
    ``demands`` that were given to the algorithm. Returns a list of
    :class:`Issue` (errors make the solution INVALID; warnings do not)."""
    errors: list = []
    warnings: list = []
    by_id = {d.id: d for d in demands}
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
    carried = solution.carried()
    paths_of: dict = {}
    for r in solution.routes:
        paths_of.setdefault(r.demand_id, set()).add(tuple(r.path))
    for d in demands:
        c = carried.get(d.id, 0)
        name = f"Demand {d.id} ({d.origin}->{d.destination})"
        if c > d.traffic + _EPS:
            err(f"{name} carries {c:g} wavelengths but requested only {d.traffic}: it was routed "
                f"more than once (in a heuristic: stop after the first path that fits).")
        elif c < d.traffic - _EPS and not allows_blocking:
            err(f"{name} carries {c:g} of the {d.traffic} requested wavelengths.")
        if not splittable and len(paths_of.get(d.id, ())) > 1:
            err(f"{name} is split over {len(paths_of[d.id])} paths, but this formulation "
                f"must not split traffic.")

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
