"""Links with several fibers: data model, files, validation, algorithms and results."""

import json
import os

import networkx as nx
import pytest

from pynet2plan import network, plotting, results, runner
from pynet2plan.errors import TopologyError
from pynet2plan.solution import Solution
from pynet2plan.traffic import Demand
from pynet2plan.validation import has_errors, validate_solution

from conftest import ROOT, needs_solutions, small_demands, small_network


def line_network(capacity=1, fibers=1):
    """A -> B -> C with one link per direction."""
    G = network.new_network("line")
    for n, x in (("A", 0), ("B", 100), ("C", 200)):
        network.add_node(G, n, x=x, y=0)
    network.add_link(G, "A", "B", capacity=capacity, fibers=fibers, bidirectional=True)
    network.add_link(G, "B", "C", capacity=capacity, fibers=fibers, bidirectional=True)
    return G


# ---------------------------------------------------------------- data model
def test_default_is_one_fiber():
    G = small_network()
    assert all(a["fibers"] == 1 for _, _, a in G.edges(data=True))
    H = nx.DiGraph()
    H.add_edge("x", "y", capacity=10)
    network.normalize(H)
    assert H.edges["x", "y"]["fibers"] == 1
    assert network.total_capacity(H, "x", "y") == 10


def test_fibers_helpers_and_errors():
    G = line_network(capacity=40, fibers=2)
    assert network.total_capacity(G, "A", "B") == 80
    network.set_link_fibers(G, "A", "B", 3)
    assert network.total_capacity(G, "A", "B") == 120
    network.set_uniform_fibers(G, 1)
    assert {a["fibers"] for _, _, a in G.edges(data=True)} == {1}
    for bad in (0, 1.5, -2):
        with pytest.raises(TopologyError):
            network.set_link_fibers(G, "A", "B", bad)
    with pytest.raises(TopologyError, match="fibers"):
        network.add_link(G, "A", "C", fibers=0)
    s = network.summary(line_network(capacity=40, fibers=2))
    assert s["total_capacity"] == 4 * 80 and s["max_fibers"] == 2
    assert "2 fibers per link" in network.describe(line_network(capacity=40, fibers=2))
    assert "fibers" not in network.describe(small_network())


def test_files_keep_the_fibers(tmp_path):
    G = small_network()
    network.set_link_fibers(G, "A", "B", 2)
    p = tmp_path / "n.json"
    network.save_topology(G, str(p))
    links = json.loads(p.read_text())["links"]
    assert [l["fibers"] for l in links if (l["origin"], l["destination"]) == ("A", "B")] == [2]
    assert all("fibers" not in l for l in links if (l["origin"], l["destination"]) != ("A", "B"))
    H = network.load_topology(str(p))
    assert H.edges["A", "B"]["fibers"] == 2 and H.edges["B", "A"]["fibers"] == 1
    g = tmp_path / "n.graphml"
    network.save_topology(G, str(g))
    assert network.load_topology(str(g)).edges["A", "B"]["fibers"] == 2
    p.write_text(json.dumps({"nodes": [{"name": "A"}, {"name": "B"}],
                             "links": [{"origin": "A", "destination": "B", "fibers": 0}]}))
    with pytest.raises(TopologyError, match="at least 1"):
        network.load_topology(str(p))


def test_parallel_links_become_fibers(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<network><node id="1" name="Milan" xCoord="0" yCoord="0"/><node id="2" name="Rome" xCoord="1" yCoord="1"/>
<link id="1" originNodeId="1" destinationNodeId="2" capacity="40"/>
<link id="2" originNodeId="1" destinationNodeId="2" capacity="40"/>
<link id="3" originNodeId="2" destinationNodeId="1" capacity="40"/></network>"""
    p = tmp_path / "two.n2p"
    p.write_text(xml)
    G = network.load_topology(str(p))
    assert (G.edges["Milan", "Rome"]["fibers"], G.edges["Milan", "Rome"]["capacity"]) == (2, 40)
    assert G.edges["Rome", "Milan"]["fibers"] == 1
    assert any("2 fibers of 40" in w for w in G.graph["load_warnings"])
    # the converted real topologies: two parallel edges in the dataset -> 2 fibers
    R = network.load_topology(os.path.join(ROOT, "data", "topologies", "real", "top5_dt17.json"))
    assert max(a["fibers"] for _, _, a in R.edges(data=True)) == 2
    assert {a["capacity"] for _, _, a in R.edges(data=True)} == {40}


# ---------------------------------------------------------------- validation
def test_validation_with_fibers():
    G = line_network(capacity=2, fibers=2)                 # 4 wavelengths per link
    D = [Demand(0, "A", "C", 3), Demand(1, "B", "C", 1)]
    s = Solution()
    s.add_route(0, ["A", "B", "C"], 3)
    s.add_route(1, ["B", "C"], 1)                          # B->C carries 4 = 2 x 2
    assert not has_errors(validate_solution(G, D, s))
    D2 = D + [Demand(2, "B", "C", 1)]
    s.add_route(2, ["B", "C"], 1)                          # 5 > 4
    msgs = " ".join(i.message for i in validate_solution(G, D2, s))
    assert "capacity is 4 (2 fibers x 2)" in msgs

    # wavelength continuity: a wavelength can be used once per fiber
    D = [Demand(0, "A", "C", 1), Demand(1, "B", "C", 1), Demand(2, "B", "C", 1)]
    s = Solution()
    s.add_route(0, ["A", "B", "C"], 1, wavelengths=[0])
    s.add_route(1, ["B", "C"], 1, wavelengths=[0])         # second fiber
    s.add_route(2, ["B", "C"], 1, wavelengths=[1])
    assert not has_errors(validate_solution(G, D, s, wavelength_continuity=True))
    s.routes[2].wavelengths = [0]                          # third use of wavelength 0
    msgs = " ".join(i.message for i in validate_solution(G, D, s, wavelength_continuity=True))
    assert "Wavelength 0 is used by 3 routes on link B->C (which has only 2 fibers)" in msgs
    s.routes[2].wavelengths = [2]                          # index 2 does not exist (2 per fiber)
    msgs = " ".join(i.message for i in validate_solution(G, D, s, wavelength_continuity=True))
    assert "wavelength 2 does not exist" in msgs


# ---------------------------------------------------------------- algorithms
def _objective(name, G, D, **params):
    r = runner.run_algorithm(G, D, name, params, save=False)
    return r.status, (r.summary.get("objective") if r.ok else None)


@pytest.mark.parametrize("name", ["splittable_flow", "solutions/route_formulation_vwp", "solutions/unsplittable_flow"])
def test_flow_formulations_see_the_total_capacity(name):
    """2 fibers of C wavelengths are the same as 1 fiber of 2C for formulations without continuity."""
    if name.startswith("solutions/") and not os.path.isdir(os.path.join(ROOT, "solutions")):
        pytest.skip("solutions/ folder not present")
    D = small_demands()
    two = small_network(capacity=2)
    network.set_uniform_fibers(two, 2)
    assert _objective(name, two, D) == _objective(name, small_network(capacity=4), D)
    assert _objective(name, small_network(capacity=2), D)[0] == "INFEASIBLE"


@needs_solutions
def test_wavelength_continuity_with_two_fibers():
    D = [Demand(0, "A", "C", 1), Demand(1, "B", "C", 1)]   # both need B->C, 1 wavelength per fiber
    status, obj = _objective("solutions/route_formulation_wp", line_network(capacity=1, fibers=1), D, k=1)
    assert status == "INFEASIBLE"
    r = runner.run_algorithm(line_network(capacity=1, fibers=2), D, "solutions/route_formulation_wp",
                             {"k": 1}, save=False)
    assert r.status == "OPTIMAL" and r.summary["objective"] == 3
    assert [route.wavelengths for route in r.solution.routes] == [[0], [0]]   # same wavelength, 2 fibers


@needs_solutions
def test_heuristic_with_two_fibers():
    D = [Demand(0, "A", "C", 2)]
    status, _ = _objective("solutions/ksp_first_fit", line_network(capacity=1, fibers=1), D)
    assert status == "BLOCKING"
    r = runner.run_algorithm(line_network(capacity=1, fibers=2), D, "solutions/ksp_first_fit", {}, save=False)
    assert r.status == "FEASIBLE" and r.summary["wavelength_links"] == 4 and r.summary["blocked_traffic"] == 0


# ---------------------------------------------------------------- results and plots
def test_results_tables_and_wavelength_grid(tmp_path):
    G = line_network(capacity=1, fibers=2)
    D = [Demand(0, "A", "C", 1), Demand(1, "B", "C", 1)]
    r = runner.run_algorithm(G, D, "splittable_flow", {}, output_root=str(tmp_path))
    run = results.load_run(r.folder)
    bc = next(l for l in run.links if (l["origin"], l["destination"]) == ("B", "C"))
    assert (bc["fibers"], bc["wavelengths_per_fiber"], bc["capacity"], bc["used"]) == (2, 1, 2, 2)
    assert run.G.edges["B", "C"]["fibers"] == 2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    wl_rows = [dict(origin="A", destination="B", wavelength=0, demand_id=0),
               dict(origin="B", destination="C", wavelength=0, demand_id=0),
               dict(origin="B", destination="C", wavelength=0, demand_id=1)]
    plotting.plot_wavelength_grid(ax, wl_rows, run.links)
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert "B → C, fiber 1" in labels and "B → C, fiber 2" in labels
    plotting.draw_network(ax, G, label_mode="capacity", legend=False)
    assert "2×1" in [t.get_text() for t in ax.texts]
    plt.close(fig)
