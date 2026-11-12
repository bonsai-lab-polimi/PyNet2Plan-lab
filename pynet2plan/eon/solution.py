"""
pynet2plan.eon.solution
======================

What an EON algorithm returns: an :class:`EonSolution`, i.e. a list of
**lightpaths**. A lightpath is one optical channel: a transponder type, a
path, and the first slot it occupies::

    sol = EonSolution()
    sol.add_lightpath(d, ["A", "B", "C"], "500G PCS 16QAM", start=0)        # slots 0..7 on A->B and B->C

A demand may be carried by several lightpaths, all of the same transponder type
(e.g. 2 x 300G PCS 16QAM; the checker rejects a mix such as 500G + 100G). With 3R
regeneration the path is cut into *segments* at the regenerator nodes, and
every segment has its own first slot::

    sol.add_lightpath(d, ["A", "B", "C"], "200G 16QAM", start=[4, 12], regenerators=["B"])

With 1+1 protection the lightpaths of the backup path are added with
``backup=True``. A demand that cannot be served is simply left without
lightpaths; ``sol.block(d, "spectrum")`` records why (shown in the results).

The number of slots of a lightpath is NOT given: it comes from the
transponder table. PyNet2Plan checks the solution independently afterwards
(see :mod:`pynet2plan.eon.validation`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .helpers import path_links, segments_of


@dataclass
class Lightpath:
    demand_id: int
    transponder: str               # name of the transponder type, e.g. "400G PCS 16QAM"
    path: list
    starts: list                   # first slot of each segment
    regenerators: list = field(default_factory=list)
    backup: bool = False

    @property
    def segments(self) -> list:
        return segments_of(self.path, self.regenerators)

    @property
    def links(self) -> list:
        return path_links(self.path)

    @property
    def role(self) -> str:
        return "backup" if self.backup else "working"

    def path_str(self) -> str:
        return " > ".join(str(n) for n in self.path)


class EonSolution:
    """The lightpaths computed by an EON algorithm.

    Attributes
    ----------
    lightpaths  list of :class:`Lightpath`
    blocked     ``{demand_id: reason}`` for the demands the algorithm gave up on
    objective   optional number reported by the algorithm (e.g. an ILP)
    info        anything worth saving with the results
    """

    def __init__(self, objective: float | None = None):
        self.lightpaths: list = []
        self.blocked: dict = {}
        self.objective = objective
        self.info: dict = {}

    def __repr__(self) -> str:
        return (f"<EonSolution: {len(self.lightpaths)} lightpaths, "
                f"{len(self.blocked)} demands blocked>")

    @staticmethod
    def _id(demand) -> int:
        demand_id = demand.id if hasattr(demand, "id") else demand
        try:
            return int(demand_id)
        except (TypeError, ValueError):
            raise TypeError(f"'demand' must be a Demand or an integer id, got {demand!r}") from None

    def add_lightpath(self, demand, path, transponder, start, regenerators=(), backup=False) -> Lightpath:
        """Add a lightpath.

        demand        a Demand (or its integer id)
        path          list of node names, from the origin to the destination of the demand
        transponder   a Transponder or its name (e.g. "400G PCS 16QAM")
        start         first slot used (same on every link), or with 3R a list with
                      the first slot of every segment
        regenerators  nodes of the path where a 3R regenerates the signal
        backup        True for the lightpaths of the backup path (1+1 protection)
        """
        name = getattr(transponder, "name", transponder)
        if not isinstance(name, str):
            raise TypeError(f"add_lightpath(): 'transponder' must be a Transponder or its name, "
                            f"got {transponder!r}")
        if start is None:
            raise TypeError("add_lightpath(): 'start' is None (first_fit found no free slots?)")
        starts = list(start) if isinstance(start, (list, tuple)) else [start]
        try:
            starts = [int(s) for s in starts]
        except (TypeError, ValueError):
            raise TypeError(f"add_lightpath(): 'start' must be slot indices, got {start!r}") from None
        lp = Lightpath(self._id(demand), name, list(path), starts, list(regenerators or ()), bool(backup))
        self.lightpaths.append(lp)
        return lp

    def block(self, demand, reason: str = "") -> None:
        """Record that a demand was not served, and why ("spectrum", "reach", ...)."""
        self.blocked[self._id(demand)] = str(reason or "")

    # ------------------------------------------------------------------
    def of_demand(self, demand_id, backup=None) -> list:
        return [lp for lp in self.lightpaths if lp.demand_id == demand_id
                and (backup is None or lp.backup == backup)]

    def served_ids(self) -> set:
        return {lp.demand_id for lp in self.lightpaths if not lp.backup}

    def to_dict(self) -> dict:
        return dict(objective=self.objective, info=dict(self.info),
                    blocked={str(k): v for k, v in self.blocked.items()},
                    lightpaths=[dict(demand_id=lp.demand_id, transponder=lp.transponder,
                                     path=list(lp.path), starts=list(lp.starts),
                                     regenerators=list(lp.regenerators), backup=lp.backup)
                                for lp in self.lightpaths])

    @classmethod
    def from_dict(cls, data: dict) -> "EonSolution":
        s = cls(objective=data.get("objective"))
        s.info = dict(data.get("info", {}))
        s.blocked = {int(k): v for k, v in data.get("blocked", {}).items()}
        for r in data.get("lightpaths", []):
            s.add_lightpath(r["demand_id"], r["path"], r["transponder"], r["starts"],
                            r.get("regenerators", ()), r.get("backup", False))
        return s
