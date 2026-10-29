import json
import os

import networkx as nx
import pytest

from pynet2plan import network
from pynet2plan.errors import TopologyError

from conftest import DATA, ROOT, small_network


def test_network_is_a_plain_digraph():
    G = small_network()
    assert isinstance(G, nx.DiGraph)
    assert G.number_of_nodes() == 5 and G.number_of_edges() == 14
    assert G.edges["A", "B"]["capacity"] == 4
    assert set(G.out_edges("A")) == {("A", "B"), ("A", "D")}
    assert all(a["up"] for _, a in G.nodes(data=True))
    assert G.edges["A", "B"]["length"] == pytest.approx(((100) ** 2 + 80 ** 2) ** 0.5, rel=1e-3)


def test_add_link_validation():
    G = small_network()
    with pytest.raises(TopologyError):
        network.add_link(G, "A", "A")
    with pytest.raises(TopologyError):
        network.add_link(G, "A", "Z")
    with pytest.raises(TopologyError):
        network.add_link(G, "A", "B")              # already exists
    with pytest.raises(TopologyError):
        network.add_link(G, "A", "C", capacity=2.5)
    with pytest.raises(TopologyError):
        network.add_link(G, "A", "C", capacity=-1)
    network.add_link(G, "A", "C", capacity=7.0)    # 7.0 is a whole number
    assert G.edges["A", "C"]["capacity"] == 7 and isinstance(G.edges["A", "C"]["capacity"], int)
    with pytest.raises(TopologyError):
        network.add_node(G, "A")


def test_cities_and_lengths():
    G = network.new_network()
    m = network.add_city(G, "Milan")
    r = network.add_city(G, "Roma")
    network.add_link(G, m, r, bidirectional=True)
    assert 450 < G.edges[m, r]["length"] < 500       # great-circle km
    assert G.nodes[m]["lat"] == pytest.approx(45.46, abs=0.01)
    with pytest.raises(TopologyError):
        network.add_city(G, "Nowhereville-xyz", allow_online=False)
    assert network.add_city(G, "Milan") == "Milan (2)"   # unique names


def test_working_graph_removes_failures():
    G = small_network()
    network.set_link_up(G, "A", "B", False)
    network.set_node_up(G, "D", False)
    H = network.working_graph(G)
    assert not H.has_edge("A", "B") and H.has_edge("B", "A")
    assert "D" not in H and not H.has_edge("A", "D")
    assert G.has_edge("A", "B")                      # original unchanged


@pytest.mark.parametrize("ext", [".json", ".graphml"])
def test_save_load_roundtrip(tmp_path, ext):
    G = small_network()
    network.set_link_up(G, "B", "C", False)
    network.set_link_capacity(G, "A", "B", 12)
    G.graph["name"] = "round trip"
    p = str(tmp_path / f"net{ext}")
    network.save_topology(G, p)
    H = network.load_topology(p)
    assert H.graph["name"] == "round trip"
    assert set(H.edges) == set(G.edges)
    assert H.edges["A", "B"]["capacity"] == 12
    assert H.edges["B", "C"]["up"] is False
    for n in G:
        assert H.nodes[n]["x"] == pytest.approx(G.nodes[n]["x"])
    # networkx itself can read the GraphML file
    if ext == ".graphml":
        raw = nx.read_graphml(p)
        assert raw.number_of_edges() == G.number_of_edges()


def test_json_format_is_readable(tmp_path):
    G = small_network()
    p = tmp_path / "n.json"
    network.save_topology(G, str(p))
    data = json.loads(p.read_text())
    assert data["format"] == "pynet2plan-topology"
    assert data["nodes"][0]["name"] == "A"
    assert {"origin", "destination", "capacity", "length", "up"} <= set(data["links"][0])


def test_load_errors(tmp_path):
    with pytest.raises(TopologyError, match="not found"):
        network.load_topology(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    with pytest.raises(TopologyError, match="not valid JSON"):
        network.load_topology(str(bad))
    bad.write_text(json.dumps({"nodes": [{"name": "A"}], "links": [{"origin": "A", "destination": "B"}]}))
    with pytest.raises(TopologyError, match="unknown node 'B'"):
        network.load_topology(str(bad))
    bad.write_text(json.dumps({"nodes": [{"name": "A"}, {"name": "B"}],
                               "links": [{"origin": "A", "destination": "B", "capacity": 3.5}]}))
    with pytest.raises(TopologyError, match="whole number"):
        network.load_topology(str(bad))


def test_legacy_v1_format():
    G = network.load_topology(os.path.join(ROOT, "tests", "data", "legacy_v1_topology.json"))
    assert G.number_of_nodes() == 7 and "Milan" in G
    assert G.graph["embedded_traffic"]          # demands of the old file are kept
    G = network.load_topology(os.path.join(ROOT, "tests", "data", "legacy_v1_cernet_parallel_links.json"))
    assert any("merged" in w for w in G.graph["load_warnings"])
    assert max(a["fibers"] for _, _, a in G.edges(data=True)) == 2          # parallel links -> 2 fibers
    assert max(a["capacity"] for _, _, a in G.edges(data=True)) == 40


def test_n2p_import(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<network description="test" name="n2p test" version="5">
  <node id="10" name="Madrid" xCoord="-3.7" yCoord="40.4" isUp="true"/>
  <node id="11" name="Barcelona" xCoord="2.17" yCoord="41.39"/>
  <node id="12" name="Valencia" xCoord="-0.37" yCoord="39.47"/>
  <layer id="0" isDefaultLayer="true" name="WDM">
    <link id="1" originNodeId="10" destinationNodeId="11" capacity="50" lengthInKm="505"/>
    <link id="2" originNodeId="11" destinationNodeId="10" capacity="50" lengthInKm="505"/>
    <link id="3" originNodeId="10" destinationNodeId="12" capacity="50.0" lengthInKm="302"/>
    <demand id="1" ingressNodeId="10" egressNodeId="11" offeredTraffic="3"/>
    <demand id="2" ingressNodeId="12" egressNodeId="10" offeredTraffic="2.0"/>
  </layer>
</network>"""
    p = tmp_path / "lab.n2p"
    p.write_text(xml)
    G = network.load_topology(str(p))
    assert G.graph["name"] == "n2p test"
    assert G.edges["Madrid", "Barcelona"]["capacity"] == 50
    assert G.edges["Madrid", "Valencia"]["length"] == 302
    assert len(G.graph["embedded_traffic"]) == 2
    from pynet2plan import traffic
    D = traffic.load_traffic(str(p), G)
    assert [(d.origin, d.destination, d.traffic) for d in D] == [("Madrid", "Barcelona", 3), ("Valencia", "Madrid", 2)]


def test_random_topology_is_reproducible_and_connected():
    a = network.random_topology(10, 4, seed=3)
    b = network.random_topology(10, 4, seed=3)
    c = network.random_topology(10, 4, seed=4)
    assert list(a.edges) == list(b.edges)
    assert list(a.edges) != list(c.edges)
    assert nx.is_strongly_connected(a)
    assert a.number_of_edges() == 2 * (9 + 4)


def test_normalize_fills_positions():
    G = nx.DiGraph()
    G.add_edge("x", "y", capacity=10)
    G.add_edge("y", "x")
    network.normalize(G)
    assert all("x" in a and "y" in a for _, a in G.nodes(data=True))
    assert G.edges["y", "x"]["capacity"] == network.DEFAULT_CAPACITY
    assert G.edges["x", "y"]["length"] > 0


def test_rename_and_remove():
    G = small_network()
    network.rename_node(G, "A", "Alpha")
    assert G.has_edge("Alpha", "B") and "A" not in G
    with pytest.raises(TopologyError):
        network.rename_node(G, "B", "C")
    network.remove_link(G, "Alpha", "B")
    assert not G.has_edge("Alpha", "B")
    network.remove_node(G, "E")
    assert "E" not in G and not G.has_edge("C", "E")


def test_reference_topologies_load():
    names = ["spain7", "nsfnet14", "cost239", "italy10", "example_cities"]
    for n in names:
        G = network.load_topology(os.path.join(DATA, "topologies", f"{n}.json"))
        assert nx.is_strongly_connected(G), n
        assert all(a["capacity"] == 40 or n == "example_cities" for _, _, a in G.edges(data=True))
    G = network.load_topology(os.path.join(DATA, "topologies", "nsfnet14.json"))
    assert (G.number_of_nodes(), G.number_of_edges()) == (14, 42)
    G = network.load_topology(os.path.join(DATA, "topologies", "cost239.json"))
    assert (G.number_of_nodes(), G.number_of_edges()) == (11, 52)


def test_graphml_topology_zoo_style(tmp_path):
    """Undirected GraphML with labels, Latitude/Longitude and a parallel edge."""
    M = nx.MultiGraph()
    M.add_node("0", label="Milan", Latitude=45.46, Longitude=9.19)
    M.add_node("1", label="Rome", Latitude=41.9, Longitude=12.5)
    M.add_edge("0", "1", capacity=10)
    M.add_edge("0", "1", capacity=30)
    p = str(tmp_path / "zoo.graphml")
    nx.write_graphml(M, p)
    G = network.load_topology(p)
    assert set(G.nodes) == {"Milan", "Rome"}
    assert G.edges["Milan", "Rome"]["capacity"] == 40 and G.edges["Rome", "Milan"]["capacity"] == 40
    assert 450 < G.edges["Milan", "Rome"]["length"] < 500
    assert any("merged" in w for w in G.graph["load_warnings"])


def test_json_with_bom(tmp_path):
    G = small_network()
    p = tmp_path / "bom.json"
    network.save_topology(G, str(p))
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    assert network.load_topology(str(p)).number_of_edges() == 14


def test_from_networkx_generators():
    import networkx as nx
    H = nx.cycle_graph(6)
    G = network.from_networkx(H, capacity=12, name="Ring 6")
    assert G.graph["name"] == "Ring 6" and G.number_of_nodes() == 6 and G.number_of_edges() == 12
    assert all(a["capacity"] == 12 and a["length"] > 0 for _, _, a in G.edges(data=True))
    assert nx.is_strongly_connected(G) and set(G.nodes) == {str(i) for i in range(6)}
    G = network.from_networkx(nx.grid_2d_graph(2, 3))
    assert "0-1" in G and G.number_of_edges() == 2 * 7
    W = nx.waxman_graph(12, beta=0.9, alpha=0.4, seed=3)              # nodes have a 'pos' attribute
    G = network.from_networkx(W)
    xs = [a["x"] for _, a in G.nodes(data=True)]
    assert max(xs) <= 1000 and min(xs) >= 0
    G = network.from_networkx(nx.DiGraph([(0, 1), (1, 2)]))            # directed: one link per edge
    assert G.number_of_edges() == 2 and not G.has_edge("1", "0")
    G = network.from_networkx(nx.MultiGraph([(0, 1), (0, 1), (1, 1)]))  # parallel edges, self-loop
    assert G.number_of_edges() == 2
    with pytest.raises(TopologyError):
        network.from_networkx(nx.Graph())
