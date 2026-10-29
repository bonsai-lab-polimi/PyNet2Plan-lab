"""
pynet2plan.traffic
=================

The traffic matrix is a list of :class:`Demand` objects::

    for d in demands:
        d.id            # 0, 1, 2, ...
        d.origin        # node name, e.g. "Madrid"
        d.destination   # node name
        d.traffic       # number of wavelengths requested (integer >= 1)

Traffic files (CSV)
-------------------
Two layouts are accepted, and recognised automatically when loading
(the demands of a Net2Plan ``.n2p`` file can be loaded too):

1. **Demand list** -- one row per demand::

       # lines starting with '#' are comments
       id,origin,destination,traffic
       0,Madrid,Barcelona,3
       1,Barcelona,Madrid,2

   The ``id`` column is optional; ``traffic`` may also be called
   ``wavelengths``, ``offered_traffic`` or ``h``. Origin/destination
   columns may also be called ``source``/``target``, ``from``/``to``.

2. **N x N matrix** -- node names in the first row and first column, the
   cell (row i, column j) is the traffic from i to j (empty or 0 = no
   demand)::

       ,Madrid,Barcelona,Valencia
       Madrid,0,3,1
       Barcelona,2,0,4
       Valencia,1,1,0

The separator can be ``,`` ``;`` or a TAB (Excel with an Italian locale
saves CSV files with ``;``). Saved files always use the demand-list layout
unless the matrix layout is requested explicitly.

Random traffic
--------------
:func:`random_traffic` and :func:`full_mesh_traffic` always use an explicit
``seed``: the same seed on the same topology gives exactly the same demands
on every computer and Python version, so experiments are repeatable. Save
the generated matrix with :func:`save_traffic` (the generation parameters
are written in the file header) to share it.
"""

from __future__ import annotations

import csv
import difflib
import io
import math
import os
import random
from dataclasses import dataclass, field
from typing import Iterable

import networkx as nx

from .errors import TrafficError

_ORIGIN_COLS = ("origin", "source", "src", "from", "ingress", "o")
_DEST_COLS = ("destination", "dest", "target", "dst", "to", "egress", "d")
_TRAFFIC_COLS = ("traffic", "wavelengths", "offered_traffic", "offeredtraffic", "h_d", "h",
                 "value", "lambdas", "offered")
_ID_COLS = ("id", "demand_id", "demand")


@dataclass(frozen=True)
class Demand:
    """A unicast traffic demand: ``traffic`` wavelengths from ``origin`` to ``destination``."""
    id: int
    origin: str
    destination: str
    traffic: int

    def __str__(self) -> str:
        return f"d{self.id}: {self.origin}->{self.destination} ({self.traffic} λ)"


@dataclass
class TrafficFile:
    """What :func:`read_traffic_file` returns: the demands plus file details."""
    demands: list
    layout: str                     # "list" or "matrix"
    comments: list = field(default_factory=list)
    path: str = ""


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def _whole(value, where: str) -> int:
    text = str(value).strip()
    try:
        f = float(text.replace(",", ".")) if text else 0.0
    except ValueError:
        raise TrafficError(f"{where}: '{value}' is not a number.") from None
    if not math.isfinite(f) or abs(f) > 1e12:
        raise TrafficError(f"{where}: '{value}' is not a valid number of wavelengths.")
    if abs(f - round(f)) > 1e-9:
        raise TrafficError(f"{where}: traffic must be a whole number of wavelengths, got {value}.")
    if f < 0:
        raise TrafficError(f"{where}: traffic cannot be negative, got {value}.")
    return int(round(f))


def _unknown_node_msg(name: str, G: nx.DiGraph) -> str:
    close = difflib.get_close_matches(name, [str(n) for n in G.nodes], n=1)
    hint = f" (did you mean '{close[0]}'?)" if close else ""
    return f"unknown node '{name}'{hint}"


def validate_traffic(demands: Iterable[Demand], G: nx.DiGraph | None = None) -> list[str]:
    """Return a list of problems (empty list = the traffic matrix is valid)."""
    problems = []
    seen_ids = set()
    for d in demands:
        if d.id in seen_ids:
            problems.append(f"Demand id {d.id} is used twice.")
        seen_ids.add(d.id)
        if d.origin == d.destination:
            problems.append(f"Demand {d.id}: origin and destination are the same node ({d.origin}).")
        if not isinstance(d.traffic, int) or d.traffic < 0:
            problems.append(f"Demand {d.id}: traffic must be a non-negative integer, got {d.traffic!r}.")
        if G is not None:
            for n in (d.origin, d.destination):
                if n not in G:
                    problems.append(f"Demand {d.id}: {_unknown_node_msg(n, G)}.")
    return problems


def check_traffic(demands: list, G: nx.DiGraph | None = None) -> list:
    """Raise ``TrafficError`` listing every problem, or return ``demands``."""
    problems = validate_traffic(demands, G)
    if problems:
        more = f"\n... and {len(problems) - 10} more" if len(problems) > 10 else ""
        raise TrafficError("Invalid traffic matrix:\n" + "\n".join(problems[:10]) + more)
    return demands


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):          # "Unicode text" saved by Excel
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TrafficError(f"Cannot decode {os.path.basename(path)} (unknown text encoding).")


def _sniff_delimiter(line: str) -> str:
    counts = {sep: line.count(sep) for sep in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def parse_traffic_text(text: str, G: nx.DiGraph | None = None, source: str = "traffic") -> TrafficFile:
    """Parse the content of a traffic CSV file (see the module docstring)."""
    comments, rows_text = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
            continue
        rows_text.append((lineno, line))
    if not rows_text:
        raise TrafficError(f"{source}: the file contains no data.")
    delim = _sniff_delimiter(rows_text[0][1])
    rows = []
    for lineno, line in rows_text:
        cells = [c.strip() for c in next(csv.reader(io.StringIO(line), delimiter=delim), [])]
        while cells and cells[-1] == "":
            cells.pop()                     # trailing empty cells (e.g. saved by Excel)
        if any(cells):
            rows.append((lineno, cells))
    if not rows:
        raise TrafficError(f"{source}: the file contains no data.")

    header_lineno, header = rows[0]
    lower = [h.lower() for h in header]

    def find(cands):
        for c in cands:
            if c in lower:
                return lower.index(c)
        return None

    # an N x N matrix has an empty top-left cell, or node names in the header
    looks_matrix = len(header) > 1 and (header[0] == "" or (
        G is not None and all(c in G for c in header[1:])
        and all(cells[0] in G for _, cells in rows[1:])))
    i_o, i_d = find(_ORIGIN_COLS), find(_DEST_COLS)
    if not looks_matrix and i_o is not None and i_d is not None:
        layout = "list"
        i_t = find(_TRAFFIC_COLS)
        if i_t is None or i_t in (i_o, i_d):
            raise TrafficError(f"{source}, line {header_lineno}: a demand-list file needs a "
                               f"'traffic' (or 'wavelengths') column. Header found: {header}")
        i_id = None
        for c in _ID_COLS:
            if c in lower and lower.index(c) not in (i_o, i_d, i_t):
                i_id = lower.index(c)
                break
        demands = []
        for lineno, cells in rows[1:]:
            where = f"{source}, line {lineno}"
            if len(cells) <= max(i_o, i_d, i_t):
                raise TrafficError(f"{where}: expected at least {max(i_o, i_d, i_t) + 1} columns, "
                                   f"found {len(cells)}.")
            o, dst = cells[i_o], cells[i_d]
            t = _whole(cells[i_t], where)
            if not o or not dst:
                raise TrafficError(f"{where}: empty origin or destination.")
            if o == dst:
                raise TrafficError(f"{where}: origin and destination are both '{o}'.")
            if G is not None:
                for n in (o, dst):
                    if n not in G:
                        raise TrafficError(f"{where}: {_unknown_node_msg(n, G)}.")
            if i_id is not None and cells[i_id] != "":
                try:
                    did = int(float(cells[i_id]))
                except (ValueError, OverflowError):
                    raise TrafficError(f"{where}: demand id '{cells[i_id]}' is not an integer.") from None
            else:
                did = len(demands)
            if t == 0:
                continue  # a zero demand is no demand
            demands.append(Demand(did, o, dst, t))
        ids = [d.id for d in demands]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise TrafficError(f"{source}: demand ids must be unique, repeated ids: {dup[:10]}")
    else:
        layout = "matrix"
        col_names = header[1:]
        if not col_names or any(c == "" for c in col_names):
            raise TrafficError(
                f"{source}, line {header_lineno}: not a valid traffic file. Use either a header "
                f"'origin,destination,traffic' (demand list) or node names in the first row "
                f"and first column (N x N matrix).")
        if G is not None:
            for c in col_names:
                if c not in G:
                    raise TrafficError(f"{source}, line {header_lineno}: column '{c}': "
                                       f"{_unknown_node_msg(c, G)}.")
        demands = []
        seen_rows = set()
        for lineno, cells in rows[1:]:
            where = f"{source}, line {lineno}"
            o = cells[0]
            if not o:
                raise TrafficError(f"{where}: the first cell must be the origin node name.")
            if o in seen_rows:
                raise TrafficError(f"{where}: node '{o}' has two rows.")
            seen_rows.add(o)
            if G is not None and o not in G:
                raise TrafficError(f"{where}: {_unknown_node_msg(o, G)}.")
            if len(cells) - 1 > len(col_names):
                raise TrafficError(f"{where}: more values than columns in the header.")
            for j, cell in enumerate(cells[1:]):
                dst = col_names[j]
                t = _whole(cell, f"{where}, column '{dst}'") if cell != "" else 0
                if t == 0:
                    continue
                if dst == o:
                    raise TrafficError(f"{where}: the diagonal cell ({o},{o}) must be 0 or empty.")
                demands.append(Demand(len(demands), o, dst, t))
    if G is not None:
        check_traffic(demands, G)
    return TrafficFile(demands=demands, layout=layout, comments=comments, path=source)


def read_traffic_file(path: str, G: nx.DiGraph | None = None) -> TrafficFile:
    """Read a traffic CSV file (either layout); validate it against ``G`` if given."""
    if not os.path.isfile(path):
        raise TrafficError(f"File not found: {path}")
    if path.lower().endswith(".n2p"):
        return _read_n2p_traffic(path, G)
    tf = parse_traffic_text(_read_text(path), G, source=os.path.basename(path))
    tf.path = os.path.abspath(path)
    return tf


def _read_n2p_traffic(path: str, G: nx.DiGraph | None) -> TrafficFile:
    """The demands of a Net2Plan .n2p file (nodes are matched by name)."""
    from .errors import TopologyError
    from .network import read_n2p
    try:
        H = read_n2p(path)
    except TopologyError as e:
        raise TrafficError(str(e)) from None
    rows = H.graph.get("embedded_traffic", [])
    if not rows:
        raise TrafficError(f"{os.path.basename(path)} contains no demands.")
    demands = []
    for i, r in enumerate(rows):
        t = _whole(r["traffic"], f"{os.path.basename(path)}, demand {i}")
        if t > 0:
            demands.append(Demand(len(demands), r["origin"], r["destination"], t))
    if G is not None:
        check_traffic(demands, G)
    return TrafficFile(demands=demands, layout="n2p", comments=[], path=os.path.abspath(path))


def load_traffic(path: str, G: nx.DiGraph | None = None) -> list:
    """Load the demands of a traffic CSV file (layout detected automatically)."""
    return read_traffic_file(path, G).demands


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def save_traffic(demands: list, path: str, layout: str = "list", nodes: list | None = None,
                 comments: Iterable[str] = ()) -> None:
    """Save demands as CSV. ``layout`` is ``"list"`` (default) or ``"matrix"``.

    In the matrix layout, demands with the same origin and destination are
    added together, and ``nodes`` (if given) fixes the order of rows/columns.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        for c in comments:
            for line in str(c).splitlines():
                f.write(f"# {line}\n")
        w = csv.writer(f)
        if layout == "list":
            w.writerow(["id", "origin", "destination", "traffic"])
            for d in demands:
                w.writerow([d.id, d.origin, d.destination, d.traffic])
        elif layout == "matrix":
            if nodes is None:
                nodes = []
                for d in demands:
                    for n in (d.origin, d.destination):
                        if n not in nodes:
                            nodes.append(n)
            m = traffic_matrix(demands)
            w.writerow([""] + list(nodes))
            for o in nodes:
                w.writerow([o] + [m.get((o, t), 0) for t in nodes])
        else:
            raise ValueError("layout must be 'list' or 'matrix'")


# ----------------------------------------------------------------------
# Generation and utilities
# ----------------------------------------------------------------------
def _rng(seed):
    """A random generator. Only ``random()`` is used on it, whose sequence is
    identical on every platform/Python version for the same seed."""
    return random.Random(seed)


def _randint(rnd, lo: int, hi: int) -> int:
    return lo + int(rnd.random() * (hi - lo + 1))


def random_traffic(G: nx.DiGraph, num_demands: int, min_traffic: int = 1, max_traffic: int = 8,
                   seed: int = 0, allow_duplicate_pairs: bool = False) -> list:
    """``num_demands`` demands between random distinct node pairs, each with a
    random integer traffic in [min_traffic, max_traffic] wavelengths.

    Without duplicates, at most N*(N-1) demands can be created (one per
    ordered node pair); a larger ``num_demands`` is reduced to that.
    """
    nodes = list(G.nodes)
    if len(nodes) < 2:
        raise TrafficError("At least 2 nodes are needed to create demands.")
    min_traffic, max_traffic = int(min_traffic), int(max_traffic)
    if min_traffic < 1 or max_traffic < min_traffic:
        raise TrafficError("Traffic range must satisfy 1 <= min <= max.")
    if num_demands < 0:
        raise TrafficError("The number of demands cannot be negative.")
    rnd = _rng(seed)
    pairs = [(a, b) for a in nodes for b in nodes if a != b]
    demands = []
    if allow_duplicate_pairs:
        for i in range(num_demands):
            o, t = pairs[int(rnd.random() * len(pairs))]
            demands.append(Demand(i, o, t, _randint(rnd, min_traffic, max_traffic)))
    else:
        num_demands = min(num_demands, len(pairs))
        for i in range(num_demands):              # partial Fisher-Yates
            j = i + int(rnd.random() * (len(pairs) - i))
            pairs[i], pairs[j] = pairs[j], pairs[i]
            o, t = pairs[i]
            demands.append(Demand(i, o, t, _randint(rnd, min_traffic, max_traffic)))
    return demands


def full_mesh_traffic(G: nx.DiGraph, min_traffic: int = 1, max_traffic: int = 8,
                      seed: int = 0) -> list:
    """One demand for every ordered pair of nodes (N*(N-1) demands), with a
    random integer traffic in [min_traffic, max_traffic]."""
    nodes = list(G.nodes)
    if len(nodes) < 2:
        raise TrafficError("At least 2 nodes are needed to create demands.")
    if min_traffic < 1 or max_traffic < min_traffic:
        raise TrafficError("Traffic range must satisfy 1 <= min <= max.")
    rnd = _rng(seed)
    out = []
    for o in nodes:
        for t in nodes:
            if o != t:
                out.append(Demand(len(out), o, t, _randint(rnd, int(min_traffic), int(max_traffic))))
    return out


def generation_comment(kind: str, **params) -> str:
    """Header line describing how a random matrix was generated (for repeatability)."""
    args = ", ".join(f"{k}={v!r}" for k, v in params.items())
    return f"generated by pynet2plan.traffic.{kind}({args})"


def traffic_matrix(demands: Iterable[Demand]) -> dict:
    """``{(origin, destination): total traffic}`` (duplicate pairs added up)."""
    m = {}
    for d in demands:
        m[(d.origin, d.destination)] = m.get((d.origin, d.destination), 0) + d.traffic
    return m


def total_traffic(demands: Iterable[Demand]) -> int:
    return sum(d.traffic for d in demands)


def renumber(demands: Iterable[Demand]) -> list:
    """Same demands with ids 0, 1, 2, ... (in order)."""
    return [Demand(i, d.origin, d.destination, d.traffic) for i, d in enumerate(demands)]


def scale_traffic(demands: Iterable[Demand], factor: float) -> list:
    """Every demand multiplied by ``factor`` (rounded, at least 1 wavelength)."""
    return [Demand(d.id, d.origin, d.destination, max(1, int(round(d.traffic * factor))))
            for d in demands]


def demands_to_dicts(demands: Iterable[Demand]) -> list:
    return [dict(id=d.id, origin=d.origin, destination=d.destination, traffic=d.traffic)
            for d in demands]


def demands_from_dicts(rows: Iterable[dict]) -> list:
    out = []
    for i, r in enumerate(rows):
        out.append(Demand(int(r.get("id", i)), str(r["origin"]), str(r["destination"]),
                          _whole(r.get("traffic", r.get("offered_traffic", 0)), f"demand {i}")))
    return out
