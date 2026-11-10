"""
pynet2plan.analysis
===================

What a **fibre cut after planning** does to a solution.

The ordinary failure model (``network.working_graph``) removes a failed link
*before* the algorithms run, so they simply route around it. That cannot show
what 1+1 protection is for. Here the algorithms plan on the full network; then a
fibre is cut and we look at the finished plan:

* a served demand whose **working** path crosses the cut survives only if it has
  a **backup** path that crosses none of the cut fibres (1+1 protection);
* without protection there is no backup, so every hit demand goes **down**.

A **fibre** is both directions of a link (a digger cuts both): see
:func:`pynet2plan.network.fibre`. The fibres cut after planning are kept on the
graph as ``G.graph["cut_after_planning"]`` so every run carries them.
"""

from __future__ import annotations

from .network import fibre, path_fibres


def cut_fibres(G) -> list:
    """The fibres ``[(u, v), ...]`` cut after planning (``G.graph['cut_after_planning']``,
    one pair or a list of pairs); ``[]`` if none."""
    c = G.graph.get("cut_after_planning")
    if not c:
        return []
    if not isinstance(c[0], (list, tuple)):
        c = [c]
    return [(str(e[0]), str(e[1])) for e in c]


def set_cut_fibres(G, entries) -> None:
    """Cut these fibres after planning (an empty list repairs everything).
    Duplicates (same fibre, either direction) are dropped."""
    out, seen = [], set()
    for e in entries:
        f = fibre(e[0], e[1])
        if f in seen:
            continue
        seen.add(f)
        out.append((str(e[0]), str(e[1])))
    if out:
        G.graph["cut_after_planning"] = out
    else:
        G.graph.pop("cut_after_planning", None)


def toggle_cut_fibre(G, u, v) -> bool:
    """Cut the fibre (u, v) if it is up, repair it if it is already cut (the
    other cuts stay). Returns True if it is now cut."""
    f = fibre(u, v)
    now = [e for e in cut_fibres(G) if fibre(*e) != f]
    cut = len(now) == len(cut_fibres(G))     # it was not in the list: add it
    if cut:
        now.append((str(u), str(v)))
    set_cut_fibres(G, now)
    return cut


def cut_links(entries) -> set:
    """The directed links (u, v) carried by these fibres (both directions)."""
    out = set()
    for e in entries:
        out.add((str(e[0]), str(e[1])))
        out.add((str(e[1]), str(e[0])))
    return out


def cut_name(entry) -> str:
    return f"{entry[0]}-{entry[1]}"


def _working_backup(solution) -> tuple:
    """{demand_id: set of fibres} for the working routes and for the backup routes."""
    work, back = {}, {}
    for r in solution.routes:
        tgt = back if r.backup else work
        tgt.setdefault(r.demand_id, set()).update(path_fibres(r.path))
    return work, back


def cut_effect(G, demands, solution, entries) -> dict:
    """What happens when all these fibres are cut together: a served demand whose
    working path uses a cut fibre is **switched** to its backup if the backup
    uses none of the cut fibres, else it is **down**."""
    cut = {fibre(e[0], e[1]) for e in entries}
    rate = {d.id: d.traffic for d in demands}
    work, back = _working_backup(solution)
    hit = [i for i, fs in work.items() if fs & cut]
    down = [i for i in hit if i not in back or (back[i] & cut)]
    switched = [i for i in hit if i not in down]
    return dict(fibres=", ".join(cut_name(e) for e in entries),
                demands_hit=len(hit), demands_down=len(down),
                demands_switched=len(switched),
                wavelengths_down=sum(rate.get(i, 0) for i in down),
                hit_ids=sorted(hit), down_ids=sorted(down), switched_ids=sorted(switched))


def fibre_cuts(G, demands, solution) -> list:
    """One row per fibre of the network: what a single cut of it would do to the
    plan (all other fibres working). Worst fibre first."""
    work, back = _working_backup(solution)
    rate = {d.id: d.traffic for d in demands}
    seen, rows = set(), []
    for u, v in G.edges:
        f = fibre(u, v)
        if f in seen:
            continue
        seen.add(f)
        hit = [i for i, fs in work.items() if f in fs]
        down = [i for i in hit if i not in back or f in back[i]]
        rows.append(dict(fibre=cut_name(f), u=f[0], v=f[1],
                         length=G.edges[u, v].get("length"),
                         demands_hit=len(hit), demands_down=len(down),
                         demands_switched=len(hit) - len(down),
                         wavelengths_down=sum(rate.get(i, 0) for i in down),
                         down_ids=sorted(down)))
    rows.sort(key=lambda r: (-r["demands_down"], -r["wavelengths_down"], r["fibre"]))
    return rows


def cut_metrics(rows: list) -> dict:
    """Worst-case single fibre cut over the rows of :func:`fibre_cuts`."""
    if not rows:
        return dict(demands_down_worst_cut=0, wavelengths_down_worst_cut=0, worst_cut="")
    worst = max(rows, key=lambda r: (r["demands_down"], r["wavelengths_down"]))
    return dict(demands_down_worst_cut=worst["demands_down"],
                wavelengths_down_worst_cut=worst["wavelengths_down"],
                worst_cut=worst["fibre"] if worst["demands_down"] else "")


__all__ = ["cut_fibres", "set_cut_fibres", "toggle_cut_fibre", "cut_links", "cut_name",
           "cut_effect", "fibre_cuts", "cut_metrics"]
