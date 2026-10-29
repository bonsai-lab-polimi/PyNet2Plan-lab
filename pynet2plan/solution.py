"""
pynet2plan.solution
==================

What an algorithm returns: a :class:`Solution`, i.e. a list of routes.

A **route** carries ``traffic`` wavelengths of one demand over a path, given
as the list of the nodes it visits::

    sol = Solution(objective=pulp.value(prob.objective))
    sol.add_route(d, ["Madrid", "Zaragoza", "Barcelona"], 3)

A demand whose traffic is *split* simply has several routes. With
wavelength continuity (no wavelength conversion) every route also says
*which* wavelengths it uses: the same indices on every link of the path::

    sol.add_route(d, ["Madrid", "Zaragoza", "Barcelona"], 2, wavelengths=[0, 5])

The solution does not need to be checked by the algorithm: PyNet2Plan
validates it independently afterwards (see :mod:`pynet2plan.validation`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

_EPS = 1e-6


@dataclass
class Route:
    """``traffic`` wavelengths of demand ``demand_id`` routed over ``path``."""
    demand_id: int
    path: list
    traffic: float
    wavelengths: list | None = None

    @property
    def links(self) -> list:
        """The links of the path, as ``(i, j)`` pairs."""
        return list(zip(self.path[:-1], self.path[1:]))

    @property
    def hops(self) -> int:
        return max(0, len(self.path) - 1)

    def path_str(self) -> str:
        return " > ".join(str(n) for n in self.path)


def _clean_number(x: float) -> float | int:
    """Round solver noise: 2.9999999 -> 3, 1e-12 -> 0."""
    x = float(x)
    if abs(x - round(x)) < _EPS:
        return int(round(x))
    return x


def path_from_links(links: Iterable, origin=None) -> list:
    """Convert a sequence of consecutive links [(a, b), (b, c)] into the node
    path [a, b, c]. Raises ValueError if the links are not consecutive."""
    links = [tuple(l) for l in links]
    if not links:
        return []
    path = [links[0][0], links[0][1]]
    for (u, v) in links[1:]:
        if u != path[-1]:
            raise ValueError(f"links {links} are not consecutive")
        path.append(v)
    if origin is not None and path[0] != origin:
        raise ValueError(f"path {path} does not start at {origin}")
    return path


class Solution:
    """The routes computed by an algorithm, plus an optional objective value.

    Attributes
    ----------
    routes     list of :class:`Route`
    objective  the objective value reported by the algorithm (or None)
    info       a dict for anything else worth saving with the results
               (e.g. ``sol.info["candidate_paths"] = 120``)
    """

    def __init__(self, objective: float | None = None):
        self.routes: list = []
        self.objective = objective
        self.info: dict = {}

    def __repr__(self) -> str:
        return f"<Solution: {len(self.routes)} routes, objective={self.objective}>"

    # ------------------------------------------------------------------
    def add_route(self, demand, path, traffic, wavelengths=None) -> Route | None:
        """Add a route.

        demand       a Demand (or its integer id)
        path         list of node names, from origin to destination
                     (a list of consecutive links [(a, b), (b, c)] is accepted too)
        traffic      wavelengths carried on this path (routes with ~0 traffic are ignored)
        wavelengths  optional list of wavelength indices (0, 1, ...) used on
                     *every* link of the path; ``len(wavelengths)`` must equal ``traffic``
        """
        demand_id = demand.id if hasattr(demand, "id") else demand
        try:
            demand_id = int(demand_id)
        except (TypeError, ValueError):
            raise TypeError(f"add_route(): 'demand' must be a Demand or an integer id, "
                            f"got {demand!r}") from None
        if traffic is None:
            raise TypeError("add_route(): 'traffic' is None (did the solver return a value?)")
        traffic = _clean_number(traffic)
        if traffic <= _EPS:
            return None
        path = list(path)
        if path and isinstance(path[0], (tuple, list)):
            path = path_from_links(path)
        if wavelengths is not None:
            wavelengths = [int(round(float(w))) for w in wavelengths]
        r = Route(demand_id, path, traffic, wavelengths)
        self.routes.append(r)
        return r

    # ------------------------------------------------------------------
    def routes_of(self, demand_id: int) -> list:
        return [r for r in self.routes if r.demand_id == demand_id]

    def carried(self) -> dict:
        """``{demand_id: total wavelengths carried}``"""
        out: dict = {}
        for r in self.routes:
            out[r.demand_id] = out.get(r.demand_id, 0) + r.traffic
        return out

    def link_occupancy(self) -> dict:
        """``{(i, j): wavelengths used on link (i, j)}`` (only used links)."""
        occ: dict = {}
        for r in self.routes:
            for e in r.links:
                occ[e] = occ.get(e, 0) + r.traffic
        return occ

    def wavelength_usage(self) -> dict:
        """``{(i, j, w): [demand ids using wavelength w on link (i, j)]}``
        (only for routes with explicit wavelengths)."""
        use: dict = {}
        for r in self.routes:
            if not r.wavelengths:
                continue
            for (i, j) in r.links:
                for w in r.wavelengths:
                    use.setdefault((i, j, w), []).append(r.demand_id)
        return use

    def has_wavelengths(self) -> bool:
        return any(r.wavelengths for r in self.routes)

    def wavelength_links(self) -> float:
        """Total wavelengths used, summed over all links (= sum of traffic x hops)."""
        return _clean_number(sum(r.traffic * r.hops for r in self.routes))

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return dict(objective=self.objective, info=dict(self.info),
                    routes=[dict(demand_id=r.demand_id, path=list(r.path), traffic=r.traffic,
                                 wavelengths=r.wavelengths) for r in self.routes])

    @classmethod
    def from_dict(cls, data: dict) -> "Solution":
        s = cls(objective=data.get("objective"))
        s.info = dict(data.get("info", {}))
        for r in data.get("routes", []):
            s.add_route(r["demand_id"], r["path"], r["traffic"], r.get("wavelengths"))
        return s
