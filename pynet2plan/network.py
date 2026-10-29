"""
pynet2plan.network
=================

In PyNet2Plan **a network is a plain** ``networkx.DiGraph``: nodes are
identified by their name (a string) and every *directed* edge is a
unidirectional link. There is no special class to learn -- everything you
know about NetworkX works here::

    import networkx as nx

    G = nx.DiGraph(name="My network")
    G.add_node("Milan", lat=45.46, lon=9.19)
    G.add_edge("Milan", "Rome", capacity=40, fibers=1, length=477.0)

    for (i, j) in G.edges:                      # every link (i, j)
        print(i, "->", j, G.edges[i, j]["fibers"], "x", G.edges[i, j]["capacity"])
    G.out_edges("Milan")                         # links leaving Milan
    G.in_edges("Milan")                          # links entering Milan

Attributes used by PyNet2Plan
----------------------------
graph   ``G.graph["name"]``            name of the network
node    ``x``, ``y``                   drawing position (Web-Mercator metres
                                       for geographic nodes)
        ``lat``, ``lon``  (optional)   geographic position, in degrees
        ``up``                         False if the node has failed
link    ``capacity``                   wavelengths of each fiber (integer, default 40)
        ``fibers``                     number of fibers in this direction
                                       (integer >= 1, default 1)
        ``length``                     length in km (geographic nodes) or in
                                       drawing units (manually placed nodes)
        ``up``                         False if the link has failed

A link (i, j) is one direction between two nodes. It may contain several
fibers, each with ``capacity`` wavelengths, so it offers
``fibers * capacity`` wavelengths in total (``total_capacity(G, i, j)``).
With wavelength continuity, a wavelength w can be used on the link once per
fiber.

The helper functions below (``add_node``, ``add_link``, ``load_topology``,
...) only make sure these attributes are always present and valid, so that
algorithms, the GUI and the result files can rely on them.

Topology files
--------------
* ``.json``   PyNet2Plan topology format (see ``topology_to_dict``). The JSON
  format of the first PyNet2Plan version (integer ids, embedded demands) is
  still accepted when loading.
* ``.graphml`` GraphML, written/read with NetworkX's own functions.
* ``.n2p``    Net2Plan designs (read only): nodes, links and, if present,
  the demands (``G.graph["embedded_traffic"]``).
"""

from __future__ import annotations

import json
import math
import os
import random
from typing import Any, Iterable

import networkx as nx

from . import geo
from .errors import TopologyError

#: Default number of wavelengths of a fiber (course convention).
DEFAULT_CAPACITY = 40
#: Default number of fibers of a link (one direction between two nodes).
DEFAULT_FIBERS = 1

TOPOLOGY_FORMAT = "pynet2plan-topology"
TOPOLOGY_VERSION = 2


# ----------------------------------------------------------------------
# Small validation helpers
# ----------------------------------------------------------------------
def _whole_number(value: Any, what: str) -> int:
    """Return ``value`` as a non-negative ``int`` (wavelengths are discrete)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise TopologyError(f"{what} must be a whole number, got {value!r}") from None
    if math.isnan(f) or math.isinf(f) or abs(f - round(f)) > 1e-9:
        raise TopologyError(f"{what} must be a whole number, got {value!r}")
    if f < 0:
        raise TopologyError(f"{what} cannot be negative, got {value!r}")
    return int(round(f))


def _clean_name(name: Any) -> str:
    if name is None:
        raise TopologyError("A node name cannot be empty.")
    name = str(name).strip()
    if not name:
        raise TopologyError("A node name cannot be empty.")
    return name


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "down", "")
    return bool(value)


def _fiber_count(value: Any, what: str) -> int:
    n = _whole_number(value, what)
    if n < 1:
        raise TopologyError(f"{what} must be at least 1, got {value!r}")
    return n


def total_capacity(G: nx.DiGraph, u: str, v: str) -> int:
    """Wavelengths offered by the link (u, v): fibers x wavelengths per fiber."""
    a = G.edges[u, v]
    return int(a.get("fibers", DEFAULT_FIBERS)) * int(a.get("capacity", DEFAULT_CAPACITY))


def link_label(u: str, v: str) -> str:
    """Human readable label of the link (u, v), e.g. ``"Milan->Rome"``."""
    return f"{u}->{v}"


def unique_name(G: nx.DiGraph, base: str) -> str:
    """``base`` if it is not used yet in ``G``, otherwise ``base (2)``, ``base (3)``..."""
    base = _clean_name(base)
    if base not in G:
        return base
    i = 2
    while f"{base} ({i})" in G:
        i += 1
    return f"{base} ({i})"


# ----------------------------------------------------------------------
# Building a network
# ----------------------------------------------------------------------
def new_network(name: str = "Untitled network") -> nx.DiGraph:
    """An empty network (a ``networkx.DiGraph``) with the given name."""
    G = nx.DiGraph()
    G.graph["name"] = name
    return G


def add_node(G: nx.DiGraph, name: str, x: float | None = None, y: float | None = None,
             lat: float | None = None, lon: float | None = None, up: bool = True) -> str:
    """Add a node called ``name``. Returns the name.

    If ``lat``/``lon`` are given and ``x``/``y`` are not, the drawing position
    is the Web-Mercator projection of (lat, lon), so the node lines up with
    the optional map background.
    """
    name = _clean_name(name)
    if name in G:
        raise TopologyError(f"A node called '{name}' already exists.")
    if (lat is None) != (lon is None):
        raise TopologyError(f"Node '{name}': give both lat and lon, or neither.")
    if lat is not None and (x is None or y is None):
        x, y = geo.lonlat_to_webmercator(float(lon), float(lat))
    attrs = {"up": bool(up)}
    for key, val in (("x", x), ("y", y), ("lat", lat), ("lon", lon)):
        if val is not None:
            attrs[key] = float(val)
    G.add_node(name, **attrs)
    return name


def add_city(G: nx.DiGraph, city: str, name: str | None = None,
             allow_online: bool = True) -> str:
    """Add a node at the real location of ``city`` (e.g. ``"Milan"``,
    ``"Paris, France"``), looked up in the bundled offline city list and,
    optionally, online (needs the ``geopy`` package and internet)."""
    coords = geo.geocode(city, allow_online=allow_online)
    if coords is None:
        raise TopologyError(
            f"Could not find the coordinates of '{city}'. Try another spelling, "
            f"add the country (e.g. '{city}, France'), or install 'geopy' for "
            f"online geocoding.")
    lat, lon = coords
    node_name = name or city.split(",")[0].strip().title()
    return add_node(G, unique_name(G, node_name), lat=lat, lon=lon)


def link_length(G: nx.DiGraph, u: str, v: str) -> float:
    """Length of a (possible) link between u and v: great-circle km if both
    nodes have lat/lon, otherwise the Euclidean distance between their
    drawing positions."""
    a, b = G.nodes[u], G.nodes[v]
    if a.get("lat") is not None and b.get("lat") is not None:
        km = geo.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        return round(km, 2) or 1.0
    if None in (a.get("x"), a.get("y"), b.get("x"), b.get("y")):
        return 1.0
    d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    return round(d, 3) or 1.0


def add_link(G: nx.DiGraph, origin: str, destination: str,
             capacity: int = DEFAULT_CAPACITY, length: float | None = None,
             bidirectional: bool = False, up: bool = True,
             fibers: int = DEFAULT_FIBERS) -> None:
    """Add the unidirectional link origin -> destination (and the opposite
    one too if ``bidirectional=True``).

    ``capacity`` is the number of wavelengths of each fiber and ``fibers`` the
    number of fibers (whole numbers); ``length`` is computed from the node
    positions when not given.
    """
    for n in (origin, destination):
        if n not in G:
            raise TopologyError(f"Node '{n}' does not exist.")
    if origin == destination:
        raise TopologyError("A link cannot start and end at the same node.")
    capacity = _whole_number(capacity, "Link capacity (wavelengths)")
    fibers = _fiber_count(fibers, "Number of fibers")
    pairs = [(origin, destination)] + ([(destination, origin)] if bidirectional else [])
    for (u, v) in pairs:
        if G.has_edge(u, v):
            raise TopologyError(
                f"The link {link_label(u, v)} already exists (PyNet2Plan allows at "
                f"most one link per direction: change its number of fibers or its "
                f"capacity instead).")
    for (u, v) in pairs:
        ln = link_length(G, u, v) if length is None else float(length)
        if ln <= 0:
            raise TopologyError(f"Link {link_label(u, v)}: length must be positive.")
        G.add_edge(u, v, capacity=capacity, fibers=fibers, length=ln, up=bool(up))


def remove_node(G: nx.DiGraph, name: str) -> None:
    """Remove a node and all the links attached to it."""
    if name not in G:
        raise TopologyError(f"Node '{name}' does not exist.")
    G.remove_node(name)


def remove_link(G: nx.DiGraph, origin: str, destination: str) -> None:
    if not G.has_edge(origin, destination):
        raise TopologyError(f"The link {link_label(origin, destination)} does not exist.")
    G.remove_edge(origin, destination)


def rename_node(G: nx.DiGraph, old: str, new: str) -> str:
    """Rename a node, keeping its attributes and links. Returns the new name."""
    new = _clean_name(new)
    if old not in G:
        raise TopologyError(f"Node '{old}' does not exist.")
    if new == old:
        return new
    if new in G:
        raise TopologyError(f"A node called '{new}' already exists.")
    nx.relabel_nodes(G, {old: new}, copy=False)
    return new


def set_link_capacity(G: nx.DiGraph, origin: str, destination: str, capacity: int) -> None:
    if not G.has_edge(origin, destination):
        raise TopologyError(f"The link {link_label(origin, destination)} does not exist.")
    G.edges[origin, destination]["capacity"] = _whole_number(capacity, "Link capacity (wavelengths)")


def set_uniform_capacity(G: nx.DiGraph, capacity: int) -> None:
    """Give every fiber the same capacity (used by the capacity sweeps)."""
    capacity = _whole_number(capacity, "Link capacity (wavelengths)")
    for (u, v) in G.edges:
        G.edges[u, v]["capacity"] = capacity


def set_link_fibers(G: nx.DiGraph, origin: str, destination: str, fibers: int) -> None:
    if not G.has_edge(origin, destination):
        raise TopologyError(f"The link {link_label(origin, destination)} does not exist.")
    G.edges[origin, destination]["fibers"] = _fiber_count(fibers, "Number of fibers")


def set_uniform_fibers(G: nx.DiGraph, fibers: int) -> None:
    """Give every link the same number of fibers."""
    fibers = _fiber_count(fibers, "Number of fibers")
    for (u, v) in G.edges:
        G.edges[u, v]["fibers"] = fibers


def _add_parallel(G: nx.DiGraph, u: str, v: str, capacity: int) -> str:
    """A second link u -> v found in a file: it becomes one more fiber when it
    has the same capacity, otherwise its wavelengths are added to every fiber
    of the existing link. Returns the warning to show."""
    a = G.edges[u, v]
    old = _whole_number(a.get("capacity", DEFAULT_CAPACITY), "capacity")
    fibers = _whole_number(a.get("fibers", DEFAULT_FIBERS), "fibers") or 1
    capacity = _whole_number(capacity, "capacity")
    if capacity == old:
        a["fibers"] = fibers + 1
        return (f"Parallel links {link_label(u, v)} merged into one link with "
                f"{a['fibers']} fibers of {old} wavelengths.")
    if fibers == 1:
        a["capacity"] = old + capacity
        return (f"Parallel links {link_label(u, v)} with different capacities merged into one "
                f"fiber of {a['capacity']} wavelengths.")
    a["fibers"], a["capacity"] = fibers + 1, max(old, capacity)
    return (f"Parallel links {link_label(u, v)} with different capacities merged into one "
            f"link with {a['fibers']} fibers of {a['capacity']} wavelengths.")


def set_node_up(G: nx.DiGraph, name: str, up: bool) -> None:
    if name not in G:
        raise TopologyError(f"Node '{name}' does not exist.")
    G.nodes[name]["up"] = bool(up)


def set_link_up(G: nx.DiGraph, origin: str, destination: str, up: bool) -> None:
    if not G.has_edge(origin, destination):
        raise TopologyError(f"The link {link_label(origin, destination)} does not exist.")
    G.edges[origin, destination]["up"] = bool(up)


# ----------------------------------------------------------------------
# Failures: the topology seen by the algorithms
# ----------------------------------------------------------------------
def working_graph(G: nx.DiGraph) -> nx.DiGraph:
    """A copy of ``G`` with only the nodes and links that are *up*.

    This is the graph handed to every algorithm, so algorithms never have to
    care about failures: a failed node/link simply does not exist for them
    (Net2Plan's default failure model).
    """
    H = nx.DiGraph()
    H.graph.update(G.graph)
    for n, attrs in G.nodes(data=True):
        if attrs.get("up", True):
            H.add_node(n, **attrs)
    for u, v, attrs in G.edges(data=True):
        if attrs.get("up", True) and u in H and v in H:
            H.add_edge(u, v, **attrs)
    return H


# ----------------------------------------------------------------------
# Normalization (make every attribute present and valid)
# ----------------------------------------------------------------------
def ensure_positions(G: nx.DiGraph, seed: int = 0) -> None:
    """Give a drawing position (x, y) to every node that does not have one:
    the Web-Mercator projection of lat/lon when known, otherwise a
    (deterministic) spring layout."""
    missing = []
    for n, a in G.nodes(data=True):
        if a.get("x") is None or a.get("y") is None:
            if a.get("lat") is not None and a.get("lon") is not None:
                a["x"], a["y"] = geo.lonlat_to_webmercator(a["lon"], a["lat"])
            else:
                missing.append(n)
    if not missing:
        return
    placed = [n for n in G.nodes if n not in missing]
    if placed:
        xs = [G.nodes[n]["x"] for n in placed]
        ys = [G.nodes[n]["y"] for n in placed]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    else:
        cx, cy, span = 500.0, 500.0, 800.0
    pos = nx.spring_layout(G.to_undirected(as_view=True), seed=seed) if len(G) > 1 else {missing[0]: (0.0, 0.0)}
    for n in missing:
        px, py = pos[n]
        G.nodes[n]["x"] = cx + float(px) * span / 2
        G.nodes[n]["y"] = cy + float(py) * span / 2


def normalize(G: nx.DiGraph) -> nx.DiGraph:
    """Fill in default attributes and validate them, in place (returns G).

    Raises ``TopologyError`` for invalid data (self-loops, fractional or
    negative capacities, ...).
    """
    G.graph.setdefault("name", "Untitled network")
    for n in list(G.nodes):
        if not isinstance(n, str):
            raise TopologyError(f"Node names must be strings, got {n!r}. "
                                f"Use nx.relabel_nodes(G, str) to convert them.")
    for n, a in G.nodes(data=True):
        a["up"] = _as_bool(a.get("up"), True)
        for k in ("lat", "lon", "x", "y"):
            if a.get(k) is not None:
                try:
                    a[k] = float(a[k])
                except (TypeError, ValueError):
                    raise TopologyError(f"Node '{n}': attribute '{k}' must be a number.") from None
            else:
                a.pop(k, None)          # missing attributes are simply absent
    ensure_positions(G)
    for u, v, a in G.edges(data=True):
        if u == v:
            raise TopologyError(f"Self-loop on node '{u}' is not allowed.")
        a["capacity"] = _whole_number(a.get("capacity", DEFAULT_CAPACITY),
                                      f"Capacity of link {link_label(u, v)}")
        a["fibers"] = _fiber_count(a.get("fibers", DEFAULT_FIBERS),
                                   f"Number of fibers of link {link_label(u, v)}")
        if a.get("length") is None:
            a["length"] = link_length(G, u, v)
        try:
            a["length"] = float(a["length"])
        except (TypeError, ValueError):
            raise TopologyError(f"Link {link_label(u, v)}: length must be a number.") from None
        if a["length"] <= 0:
            a["length"] = link_length(G, u, v)
        a["up"] = _as_bool(a.get("up"), True)
    return G


# ----------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------
def topology_to_dict(G: nx.DiGraph) -> dict:
    """The PyNet2Plan JSON representation of ``G`` (see ``save_topology``)."""
    nodes = []
    for n, a in G.nodes(data=True):
        item = {"name": n}
        for k in ("lat", "lon", "x", "y"):
            if a.get(k) is not None:
                item[k] = a[k]
        item["up"] = bool(a.get("up", True))
        nodes.append(item)
    links = []
    for u, v, a in G.edges(data=True):
        item = {"origin": u, "destination": v,
                "capacity": int(a.get("capacity", DEFAULT_CAPACITY))}
        if int(a.get("fibers", DEFAULT_FIBERS)) != 1:          # written only when not 1
            item["fibers"] = int(a["fibers"])
        item["length"] = a.get("length")
        item["up"] = bool(a.get("up", True))
        links.append(item)
    data = {"format": TOPOLOGY_FORMAT, "version": TOPOLOGY_VERSION,
            "name": G.graph.get("name", "Untitled network")}
    if G.graph.get("description"):
        data["description"] = G.graph["description"]
    data["nodes"] = nodes
    data["links"] = links
    return data


def _from_legacy_dict(data: dict) -> nx.DiGraph:
    """Read the JSON format of PyNet2Plan v1 (integer ids, embedded demands).

    Parallel links between the same pair of nodes become fibers of one link,
    since a DiGraph has at most one link per direction.
    """
    G = new_network(str(data.get("name", "Untitled network")))
    warnings = []
    id_to_name = {}
    for key, n in data.get("nodes", {}).items():
        nid = int(n.get("id", key))
        raw = str(n.get("name") or f"N{nid}").strip() or f"N{nid}"
        name = unique_name(G, raw)
        if name != raw:
            warnings.append(f"Duplicate node name '{raw}' renamed to '{name}'.")
        id_to_name[nid] = name
        G.add_node(name, x=n.get("x"), y=n.get("y"), lat=n.get("lat"), lon=n.get("lon"),
                   up=n.get("up", True))
    for key, l in data.get("links", {}).items():
        try:
            u, v = id_to_name[int(l["origin"])], id_to_name[int(l["destination"])]
        except (KeyError, ValueError):
            raise TopologyError(f"Link {key} refers to an unknown node.") from None
        if u == v:
            warnings.append(f"Self-loop on '{u}' ignored.")
            continue
        cap = l.get("capacity", DEFAULT_CAPACITY)
        if G.has_edge(u, v):
            a = G.edges[u, v]
            warnings.append(_add_parallel(G, u, v, int(round(float(cap)))))
            if l.get("length") is not None and (a["length"] is None or l["length"] < a["length"]):
                a["length"] = l["length"]
        else:
            G.add_edge(u, v, capacity=int(round(float(cap))), length=l.get("length"),
                       up=l.get("up", True))
    demands = []
    for key, d in data.get("demands", {}).items():
        try:
            demands.append({"origin": id_to_name[int(d["origin"])],
                            "destination": id_to_name[int(d["destination"])],
                            "traffic": d.get("offered_traffic", d.get("traffic", 0))})
        except (KeyError, ValueError):
            warnings.append(f"Demand {key} refers to an unknown node: ignored.")
    if demands:
        G.graph["embedded_traffic"] = demands
    if warnings:
        G.graph["load_warnings"] = warnings
    return G


def topology_from_dict(data: dict) -> nx.DiGraph:
    """Build a network from its JSON representation (current or v1 format)."""
    if not isinstance(data, dict) or "nodes" not in data:
        raise TopologyError("Not a PyNet2Plan topology: the 'nodes' section is missing.")
    if isinstance(data["nodes"], dict):
        G = _from_legacy_dict(data)
    else:
        G = new_network(str(data.get("name", "Untitled network")))
        if data.get("description"):
            G.graph["description"] = data["description"]
        for i, n in enumerate(data["nodes"]):
            if not isinstance(n, dict) or "name" not in n:
                raise TopologyError(f"Node #{i + 1} has no 'name'.")
            name = _clean_name(n["name"])
            if name in G:
                raise TopologyError(f"Duplicate node name '{name}'.")
            G.add_node(name, x=n.get("x"), y=n.get("y"), lat=n.get("lat"), lon=n.get("lon"),
                       up=n.get("up", True))
        for i, l in enumerate(data.get("links", [])):
            try:
                u, v = str(l["origin"]).strip(), str(l["destination"]).strip()
            except (KeyError, TypeError):
                raise TopologyError(f"Link #{i + 1} needs an 'origin' and a 'destination'.") from None
            for n in (u, v):
                if n not in G:
                    raise TopologyError(f"Link #{i + 1} ({link_label(u, v)}) refers to the "
                                        f"unknown node '{n}'.")
            if G.has_edge(u, v):
                raise TopologyError(f"Link {link_label(u, v)} is listed twice.")
            G.add_edge(u, v, capacity=l.get("capacity", DEFAULT_CAPACITY),
                       fibers=l.get("fibers", DEFAULT_FIBERS),
                       length=l.get("length"), up=l.get("up", True))
    return normalize(G)


def _n2p_attr(el, *names, default=None):
    low = {k.lower(): v for k, v in el.attrib.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return default


def read_n2p(path: str) -> nx.DiGraph:
    """Read a Net2Plan ``.n2p`` file (XML): nodes, links and demands.

    Supports the common layouts (links/demands directly under ``<network>``
    or inside a ``<layer>``; with several layers the default layer -- or the
    first one with links -- is used). Node coordinates become the drawing
    position; link ``capacity`` and demand ``offeredTraffic`` must be whole
    numbers (wavelengths). The demands are stored in
    ``G.graph["embedded_traffic"]``.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise TopologyError(f"{os.path.basename(path)} is not a valid .n2p (XML) file: {e}") from None

    def tag(el):
        return el.tag.split("}")[-1].lower()

    G = new_network(_n2p_attr(root, "name") or os.path.splitext(os.path.basename(path))[0])
    if _n2p_attr(root, "description"):
        G.graph["description"] = _n2p_attr(root, "description")
    warnings = []
    id_to_name = {}
    for el in root.iter():
        if tag(el) != "node":
            continue
        nid = _n2p_attr(el, "id")
        raw = (_n2p_attr(el, "name") or f"N{nid}").strip() or f"N{nid}"
        name = unique_name(G, raw)
        if name != raw:
            warnings.append(f"Duplicate node name '{raw}' renamed to '{name}'.")
        id_to_name[nid] = name
        x = _n2p_attr(el, "xCoord", "x")
        y = _n2p_attr(el, "yCoord", "y")
        try:
            x = float(x) if x not in (None, "") else None
            y = float(y) if y not in (None, "") else None
        except ValueError:
            raise TopologyError(f"Node '{raw}': invalid coordinates ({x}, {y}).") from None
        G.add_node(name, x=x, y=y, up=_as_bool(_n2p_attr(el, "isUp", "up"), True))
    if not id_to_name:
        raise TopologyError(f"{os.path.basename(path)}: no <node> elements found.")

    layers = [el for el in root.iter() if tag(el) == "layer"]
    container = root
    if layers:
        default = [l for l in layers if _as_bool(_n2p_attr(l, "isDefaultLayer"), False)]
        with_links = [l for l in layers if any(tag(c) == "link" for c in l)]
        container = (default or with_links or layers)[0]
        if len(layers) > 1:
            warnings.append(f"The file has {len(layers)} layers: only layer "
                            f"'{_n2p_attr(container, 'name', default='?')}' was imported.")
    links = [el for el in container if tag(el) == "link"] or \
            [el for el in root.iter() if tag(el) == "link"]
    for el in links:
        o, d = _n2p_attr(el, "originNodeId"), _n2p_attr(el, "destinationNodeId")
        if o not in id_to_name or d not in id_to_name:
            warnings.append(f"Link {_n2p_attr(el, 'id')} refers to an unknown node: ignored.")
            continue
        u, v = id_to_name[o], id_to_name[d]
        if u == v:
            continue
        cap = _whole_number(_n2p_attr(el, "capacity", default=DEFAULT_CAPACITY),
                            f"Capacity of link {link_label(u, v)}")
        length = _n2p_attr(el, "lengthInKm", "length")
        try:
            length = float(length) if length not in (None, "") else None
        except ValueError:
            raise TopologyError(f"Link {link_label(u, v)}: invalid length '{length}'.") from None
        if G.has_edge(u, v):
            warnings.append(_add_parallel(G, u, v, cap))
        else:
            G.add_edge(u, v, capacity=cap, length=length if length and length > 0 else None,
                       up=_as_bool(_n2p_attr(el, "isUp", "up"), True))
    demands = []
    for el in [c for c in container if tag(c) == "demand"] or \
            [c for c in root.iter() if tag(c) == "demand"]:
        o, d = _n2p_attr(el, "ingressNodeId"), _n2p_attr(el, "egressNodeId")
        if o not in id_to_name or d not in id_to_name:
            continue
        demands.append({"origin": id_to_name[o], "destination": id_to_name[d],
                        "traffic": _n2p_attr(el, "offeredTraffic", default="0")})
    if demands:
        G.graph["embedded_traffic"] = demands
    if warnings:
        G.graph["load_warnings"] = warnings
    return normalize(G)


def _from_graphml(path: str) -> nx.DiGraph:
    """Read GraphML (PyNet2Plan's own files, or e.g. Topology Zoo files with
    'label' / 'Latitude' / 'Longitude'). Undirected edges become two links;
    parallel edges become fibers of one link."""
    raw = nx.read_graphml(path)
    G = new_network(raw.graph.get("name") or raw.graph.get("label")
                    or os.path.splitext(os.path.basename(path))[0])
    warnings = []

    def get(a, *keys):
        low = {str(k).lower(): v for k, v in a.items()}
        for k in keys:
            if k.lower() in low and low[k.lower()] not in (None, ""):
                return low[k.lower()]
        return None

    labels = [get(a, "name", "label") for _, a in raw.nodes(data=True)]
    use_labels = all(labels) and len(set(map(str, labels))) == len(labels)
    names = {}
    for (n, a), lab in zip(raw.nodes(data=True), labels):
        name = str(lab).strip() if use_labels else str(n)
        names[n] = name
        G.add_node(name, x=get(a, "x"), y=get(a, "y"), lat=get(a, "lat", "latitude"),
                   lon=get(a, "lon", "longitude"), up=get(a, "up"))
    pairs = []
    for u, v, a in raw.edges(data=True):
        pairs.append((names[u], names[v], a))
        if not raw.is_directed():
            pairs.append((names[v], names[u], a))
    for u, v, a in pairs:
        if u == v:
            continue
        cap = get(a, "capacity")
        if G.has_edge(u, v):
            warnings.append(_add_parallel(G, u, v, cap if cap is not None else DEFAULT_CAPACITY))
        else:
            fib = get(a, "fibers")
            G.add_edge(u, v, capacity=cap if cap is not None else DEFAULT_CAPACITY,
                       fibers=fib if fib is not None else DEFAULT_FIBERS,
                       length=get(a, "length", "length_km", "LinkLength"), up=get(a, "up"))
    if warnings:
        G.graph["load_warnings"] = warnings
    return normalize(G)


def load_topology(path: str) -> nx.DiGraph:
    """Load a network from a ``.json`` (PyNet2Plan), ``.graphml`` or ``.n2p``
    (Net2Plan) file.

    The returned graph remembers the file it came from in
    ``G.graph["source_file"]``.
    """
    if not os.path.isfile(path):
        raise TopologyError(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".n2p":
            G = read_n2p(path)
        elif ext in (".graphml", ".xml"):
            G = _from_graphml(path)
        else:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            G = topology_from_dict(data)
    except TopologyError as e:
        raise TopologyError(f"{os.path.basename(path)}: {e}") from None
    except json.JSONDecodeError as e:
        raise TopologyError(f"{os.path.basename(path)} is not valid JSON "
                            f"(line {e.lineno}, column {e.colno}: {e.msg}).") from None
    except Exception as e:  # noqa: BLE001 - any parser error becomes a TopologyError
        raise TopologyError(f"Cannot read {os.path.basename(path)}: {e}") from None
    G.graph["source_file"] = os.path.abspath(path)
    return G


def save_topology(G: nx.DiGraph, path: str) -> None:
    """Save the network to ``.json`` (PyNet2Plan format) or ``.graphml``."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".graphml", ".xml"):
        H = nx.DiGraph()
        H.graph["name"] = G.graph.get("name", "Untitled network")
        for n, a in G.nodes(data=True):
            H.add_node(n, **{k: a[k] for k in ("x", "y", "lat", "lon", "up") if a.get(k) is not None})
        for u, v, a in G.edges(data=True):
            H.add_edge(u, v, capacity=int(a["capacity"]), fibers=int(a.get("fibers", DEFAULT_FIBERS)),
                       length=float(a["length"]), up=bool(a.get("up", True)))
        nx.write_graphml(H, path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topology_to_dict(G), f, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------
# Generators and summaries
# ----------------------------------------------------------------------
def random_topology(num_nodes: int = 8, extra_links: int = 4, seed: int | None = None,
                    capacity: int = DEFAULT_CAPACITY, name: str | None = None) -> nx.DiGraph:
    """A random connected network with bidirectional links (demo helper).

    Nodes are placed at random in a 1000 x 1000 square (so link lengths look
    like km); a random spanning tree guarantees connectivity, then
    ``extra_links`` more node pairs are connected. Same ``seed`` -> same network.
    """
    if num_nodes < 2:
        raise TopologyError("A random topology needs at least 2 nodes.")
    rnd = random.Random(seed)
    G = new_network(name or f"Random topology ({num_nodes} nodes, seed={seed})")
    names = [f"N{i}" for i in range(num_nodes)]
    for n in names:
        add_node(G, n, x=round(rnd.random() * 1000, 1), y=round(rnd.random() * 1000, 1))
    order = names[:]
    for i in range(len(order) - 1, 0, -1):          # Fisher-Yates shuffle
        j = int(rnd.random() * (i + 1))
        order[i], order[j] = order[j], order[i]
    connected = [order[0]]
    for n in order[1:]:
        other = connected[int(rnd.random() * len(connected))]
        add_link(G, other, n, capacity=capacity, bidirectional=True)
        connected.append(n)
    candidates = [(a, b) for k, a in enumerate(names) for b in names[k + 1:]
                  if not G.has_edge(a, b)]
    for _ in range(min(extra_links, len(candidates))):
        a, b = candidates.pop(int(rnd.random() * len(candidates)))
        add_link(G, a, b, capacity=capacity, bidirectional=True)
    return G


def _node_name(n: Any) -> str:
    if isinstance(n, tuple):                 # e.g. grid graphs: (row, column)
        return "-".join(str(p) for p in n)
    return str(n)


def from_networkx(H: nx.Graph, capacity: int = DEFAULT_CAPACITY, name: str | None = None,
                  pos: dict | None = None, size: float = 1000.0, seed: int = 0) -> nx.DiGraph:
    """Turn any NetworkX graph -- e.g. one made by a NetworkX generator such as
    ``nx.waxman_graph`` or ``nx.cycle_graph`` -- into a PyNet2Plan network.

    * every undirected edge becomes two unidirectional links (a directed edge one link);
    * node names become strings (a tuple such as (0, 1) becomes "0-1");
    * node positions come from ``pos``, or from the node attribute ``"pos"``
      (set by the geometric generators), or from a seeded spring layout; they are
      scaled to a ``size`` x ``size`` square, so lengths look like km;
    * every link gets ``capacity`` wavelengths and its length from the positions.

    Example::

        H = nx.waxman_graph(10, beta=0.6, alpha=0.3, seed=1)
        G = network.from_networkx(H, capacity=40, name="Waxman 10")
        network.save_topology(G, "data/topologies/my_waxman.json")   # open it in the GUI
    """
    if H.number_of_nodes() == 0:
        raise TopologyError("The graph has no nodes.")
    if pos is None:
        attr = nx.get_node_attributes(H, "pos")
        pos = attr if len(attr) == H.number_of_nodes() else nx.spring_layout(H, seed=seed)
    xs = [float(pos[n][0]) for n in H]
    ys = [float(pos[n][1]) for n in H]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    G = new_network(name or H.graph.get("name") or
                    f"{type(H).__name__} ({H.number_of_nodes()} nodes)")
    names = {}
    for n, x, y in zip(H, xs, ys):
        names[n] = add_node(G, unique_name(G, _node_name(n)),
                            x=round((x - min(xs)) / span * size, 1),
                            y=round((y - min(ys)) / span * size, 1))
    for u, v in H.edges():
        if u == v:
            continue                          # self-loops are not links
        a, b = names[u], names[v]
        both = not H.is_directed()
        if G.has_edge(a, b) or (both and G.has_edge(b, a)):
            continue                          # parallel edges (MultiGraph): keep one
        add_link(G, a, b, capacity=capacity, bidirectional=both)
    return G


def summary(G: nx.DiGraph) -> dict:
    """A few numbers describing the network (shown in the GUI "Info" tab)."""
    n, m = G.number_of_nodes(), G.number_of_edges()
    up_nodes = sum(1 for _, a in G.nodes(data=True) if a.get("up", True))
    up_links = sum(1 for _, _, a in G.edges(data=True) if a.get("up", True))
    caps = [a.get("capacity", 0) for _, _, a in G.edges(data=True)]
    fibers = [a.get("fibers", DEFAULT_FIBERS) for _, _, a in G.edges(data=True)]
    out_deg = [d for _, d in G.out_degree()]
    H = working_graph(G)
    return dict(
        name=G.graph.get("name", ""),
        num_nodes=n, num_nodes_up=up_nodes,
        num_links=m, num_links_up=up_links,
        total_capacity=sum(f * c for f, c in zip(fibers, caps)),
        min_capacity=min(caps) if caps else 0,
        max_capacity=max(caps) if caps else 0,
        total_fibers=sum(fibers),
        min_fibers=min(fibers) if fibers else 0,
        max_fibers=max(fibers) if fibers else 0,
        avg_out_degree=(sum(out_deg) / n) if n else 0.0,
        strongly_connected=(nx.is_strongly_connected(H) if len(H) > 0 else False),
        geographic=all(a.get("lat") is not None for _, a in G.nodes(data=True)) if n else False,
    )


def describe(G: nx.DiGraph) -> str:
    s = summary(G)
    cap = (f"{s['min_capacity']}" if s['min_capacity'] == s['max_capacity']
           else f"{s['min_capacity']}-{s['max_capacity']}")
    fib = "" if s["max_fibers"] <= 1 else (
        f", {s['min_fibers']}" + (f"-{s['max_fibers']}" if s["min_fibers"] != s["max_fibers"] else "")
        + " fibers per link")
    return (f"{s['name']}: {s['num_nodes']} nodes, {s['num_links']} links "
            f"({s['num_links_up']} up), capacity {cap} λ{' per fiber' if fib else ''}{fib}")


def iter_links(G: nx.DiGraph) -> Iterable[tuple]:
    """``(origin, destination, attributes)`` for every link, in insertion order."""
    return G.edges(data=True)
