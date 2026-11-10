"""Optical reach without 3R regenerators: a network-level limit on the length of every
lightpath (working and backup), set in File > Limit the optical reach and saved with the
topology. The three protection-lab algorithms skip longer paths; the checker rejects them."""

import os

import pytest

from conftest import DATA, ROOT  # noqa: F401
from pynet2plan import network, runner, traffic
from pynet2plan.errors import TopologyError
from pynet2plan.solution import Solution
from pynet2plan.validation import has_errors, validate_solution

RF = "solutions/protection_route_formulation"        # the reference solution (the exercise has TODOs)
# the student copy has the exercise (with TODOs) but not the reference solution
HAS_RF = os.path.isfile(os.path.join(ROOT, "solutions", "protection_route_formulation.py"))
needs_rf = pytest.mark.skipif(not HAS_RF, reason="the reference route formulation is not part of this copy")
ALGS = ("greedy_no_protection", "greedy_1plus1_protection", RF)


@pytest.fixture
def spain_prot():
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_protection.csv"), G)
    return G, D


def test_reach_is_off_by_default_and_saved_with_the_topology(spain_prot, tmp_path):
    G, _ = spain_prot
    assert network.optical_reach(G) is None
    assert network.within_reach(G, ["Madrid", "Zaragoza", "Barcelona"])
    network.set_optical_reach(G, 1000)
    path = str(tmp_path / "t.json")
    network.save_topology(G, path)
    assert network.optical_reach(network.load_topology(path)) == 1000
    network.set_optical_reach(G, None)                       # switched off
    network.save_topology(G, path)
    assert network.optical_reach(network.load_topology(path)) is None
    G.graph["optical_reach_km"] = -5
    with pytest.raises(TopologyError):
        network.normalize(G)


def test_validator_rejects_a_path_longer_than_the_reach(spain_prot):
    G, D = spain_prot
    d = D[0]
    import networkx as nx
    path = nx.shortest_path(G, d.origin, d.destination, weight="length")
    km = network.path_length(G, path)
    sol = Solution()
    sol.add_route(d, path, d.traffic, wavelengths=list(range(int(d.traffic))))
    network.set_optical_reach(G, km)                         # exactly the reach: allowed
    assert not has_errors(validate_solution(G, [d], sol, splittable=False, allows_blocking=True))
    network.set_optical_reach(G, km - 1)                     # 1 km too long
    issues = validate_solution(G, [d], sol, splittable=False, allows_blocking=True)
    assert has_errors(issues) and any("optical reach" in i.message for i in issues)


@pytest.mark.parametrize("reach,served,far", [(700, (23, 3, 3), 7), (1000, (30, 17, 17), 0),
                                              (1400, (30, 28, 28), 0)])
def test_algorithms_respect_the_reach(spain_prot, reach, served, far):
    """1000 km: every demand fits without protection, but the backup paths are longer, so
    1+1 can protect only 17 of 30 -- the motivation for 3R regenerators."""
    G, D = spain_prot
    network.set_optical_reach(G, reach)
    got = []
    for alg in ALGS:
        if alg == RF and not HAS_RF:
            got.append(served[2])                      # student copy: no reference solution
            continue
        res = runner.run_algorithm(G, D, alg, save=False)
        assert res.summary["errors"] == 0, res.message
        assert res.summary["optical_reach_km"] == reach
        assert res.summary["out_of_reach_demands"] == far
        assert all(network.path_length(G, r.path) <= reach for r in res.solution.routes)
        got.append(len(D) - res.summary["blocked_demands"])
    assert tuple(got) == served


@needs_rf
def test_route_formulation_never_worse_than_greedy_with_a_reach():
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7_tight.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_tight.csv"), G)
    for reach in (900, 1100, 1200):
        network.set_optical_reach(G, reach)
        h = runner.run_algorithm(G, D, "greedy_1plus1_protection", save=False).summary
        r = runner.run_algorithm(G, D, RF, save=False).summary
        assert r["errors"] == 0 and r["blocked_demands"] <= h["blocked_demands"]


def test_report_mentions_the_reach(spain_prot, tmp_path):
    G, D = spain_prot
    network.set_optical_reach(G, 700)
    res = runner.run_algorithm(G, D, "greedy_no_protection", output_root=str(tmp_path))
    with open(os.path.join(res.folder, "report.txt"), encoding="utf-8") as fh:
        text = fh.read()
    assert "Optical reach:     700 km" in text and "7 demand(s) are farther" in text
    from pynet2plan.results import load_run
    assert network.optical_reach(load_run(res.folder).G) == 700     # kept in the run folder


# ---------------------------------------------------------------------------------------------
# 3R regenerators: greedy_3r may use paths longer than the reach, regenerated on the way
# ---------------------------------------------------------------------------------------------
def test_regenerator_sites_go_as_far_as_possible():
    G = network.new_network("line")
    for n, x in (("A", 0), ("B", 1), ("C", 2), ("D", 3), ("E", 4)):
        network.add_node(G, n, x=x * 100, y=0)
    for (u, v, km) in (("A", "B", 300), ("B", "C", 300), ("C", "D", 300), ("D", "E", 300)):
        network.add_link(G, u, v, capacity=4, length=km)
    path = ["A", "B", "C", "D", "E"]
    assert network.regenerator_sites(G, path) == []              # no reach: no 3R
    network.set_optical_reach(G, 650)
    assert network.regenerator_sites(G, path) == ["C"]           # 600 km, then 600 km
    network.set_optical_reach(G, 500)
    assert network.regenerator_sites(G, path) == ["B", "C", "D"]
    network.set_optical_reach(G, 250)
    assert network.regenerator_sites(G, path) is None            # a single link is too long


def test_validator_checks_every_stretch_between_regenerators(spain_prot):
    G, _ = spain_prot
    path = ["Sevilla", "Madrid", "Zaragoza", "Barcelona"]
    d = traffic.Demand(99, "Sevilla", "Barcelona", 2)
    network.set_optical_reach(G, network.path_length(G, path) - 1)
    wl = list(range(int(d.traffic)))

    def check(regs):
        sol = Solution()
        sol.add_route(d, path, d.traffic, wavelengths=wl, regenerators=regs)
        return validate_solution(G, [d], sol, splittable=False, allows_blocking=True)

    assert has_errors(check(None))                               # too long, no 3R
    assert not has_errors(check(network.regenerator_sites(G, path)))
    issues = check(["Valencia"])                                 # not on the path
    assert has_errors(issues) and any("not an intermediate node" in i.message for i in issues)


def test_cost239_3r_example(tmp_path):
    """The GUI example: reach 800 km; without 3R 16 of 25 demands are served, with 3R all 25,
    using 42 regenerators in 5 nodes; every stretch is within the reach."""
    G = network.load_topology(os.path.join(DATA, "topologies", "cost239_3r.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "cost239_traffic.csv"), G)
    assert network.optical_reach(G) == 800 and len(D) == 25
    plain = runner.run_algorithm(G, D, "greedy_no_protection", save=False).summary
    assert plain["blocked_demands"] == 9 and plain["out_of_reach_demands"] == 9
    assert plain["regenerators"] == 0
    res = runner.run_algorithm(G, D, "greedy_3r", output_root=str(tmp_path))
    s = res.summary
    assert res.status == "FEASIBLE" and s["errors"] == 0 and s["blocked_demands"] == 0
    assert (s["regenerators"], s["regenerator_sites"]) == (42, 5)
    for r in res.solution.routes:
        stops = [0] + [r.path.index(n) for n in r.regenerators or []] + [len(r.path) - 1]
        assert all(network.path_length(G, r.path[a:b + 1]) <= 800 for a, b in zip(stops, stops[1:]))
    from pynet2plan.results import load_run
    run = load_run(res.folder)                                   # what the GUI map shows
    counts = run.regenerator_counts()
    assert sum(counts.values()) == 42 and len(counts) == 5
    with open(os.path.join(res.folder, "report.txt"), encoding="utf-8") as fh:
        assert "3R regenerators:   42" in fh.read()


def test_3r_without_reach_is_the_plain_greedy():
    G = network.load_topology(os.path.join(DATA, "topologies", "cost239.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "cost239_traffic.csv"), G)
    a = runner.run_algorithm(G, D, "greedy_no_protection", {"weight": "length"}, save=False).solution  # 3R: km
    b = runner.run_algorithm(G, D, "greedy_3r", save=False).solution
    assert [(r.path, r.wavelengths) for r in a.routes] == [(r.path, r.wavelengths) for r in b.routes]
    assert b.num_regenerators() == 0


def test_map_draws_the_3r_marks():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from pynet2plan import plotting
    G = network.load_topology(os.path.join(DATA, "topologies", "cost239_3r.json"))
    ax = Figure().add_subplot(111)
    plotting.draw_network(ax, G, link_used={}, regenerators={"Paris": 8, "Berlin": 7})
    texts = [t.get_text() for t in ax.texts]
    assert "3R×8" in texts and "3R×7" in texts
    assert any("3R regenerators (15 in 2 nodes)" in t.get_text() for t in ax.get_legend().get_texts())
