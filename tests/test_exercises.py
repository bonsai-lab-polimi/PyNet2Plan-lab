"""Self-check of the exercises:   python -m pytest tests/test_exercises.py -v

The tests of an exercise are SKIPPED while its file still contains
'raise NotCompletedError' lines. Once you have completed it, they check that
your formulation gives valid and optimal results.
"""

import os

import networkx as nx
import pytest

from pynet2plan import loader, network, runner

from conftest import DATA, FORMULATIONS


def completed(name):
    path = os.path.join(FORMULATIONS, f"{name}.py")
    if not os.path.isfile(path):
        pytest.skip(f"{name}.py is not part of this copy yet (it comes with a later lab)")
    info = loader.load_formulation(path)
    assert info.ok, info.error
    if info.todo_count:
        pytest.skip(f"{name}.py is not completed yet ({info.todo_count} TODO left)")
    return info


@pytest.fixture(scope="module")
def spain():
    from pynet2plan import traffic
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    return G, traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic.csv"), G)


def with_capacity(G, c):
    H = G.copy()
    network.set_uniform_capacity(H, c)
    return H


def run(name, G, D, **params):
    return runner.run_algorithm(G, D, f"formulations/{name}", params, save=False)


def test_unsplittable_flow(spain):
    completed("unsplittable_flow")
    r = runner.check_formulation("formulations/unsplittable_flow")
    assert r.status == "OPTIMAL", r.message
    assert r.summary["objective"] == pytest.approx(21)       # optimum of the test network
    G, D = spain
    G = with_capacity(G, 23)
    un = run("unsplittable_flow", G, D)
    sp = run("splittable_flow", G, D)
    assert un.status == "OPTIMAL", un.message
    assert un.summary["split_demands"] == 0
    assert un.summary["objective"] >= sp.summary["objective"] - 1e-6
    assert run("unsplittable_flow", with_capacity(G, 15), D).status == "INFEASIBLE"
    # a traffic matrix where splitting matters: known optimal values
    from pynet2plan import traffic
    D2 = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    assert run("unsplittable_flow", with_capacity(G, 34), D2).status == "INFEASIBLE"
    r = run("unsplittable_flow", with_capacity(G, 40), D2)
    assert r.status == "OPTIMAL" and r.summary["objective"] == pytest.approx(443)
    assert run("unsplittable_flow", with_capacity(G, 50), D2).summary["objective"] == pytest.approx(422)


def test_route_formulation_vwp(spain):
    completed("route_formulation_vwp")
    r = runner.check_formulation("formulations/route_formulation_vwp")
    assert r.status == "OPTIMAL", r.message
    assert r.summary["objective"] == pytest.approx(20)       # same as the splittable formulation
    G, D = spain
    G = with_capacity(G, 23)
    sp = run("splittable_flow", G, D)
    v = {k: run("route_formulation_vwp", G, D, k=k) for k in (1, 2, 3)}
    assert v[1].status == "INFEASIBLE"                       # one path per demand is not enough
    assert v[2].status == v[3].status == "OPTIMAL", v[2].message
    assert v[2].summary["objective"] >= v[3].summary["objective"] >= sp.summary["objective"] - 1e-6
    assert v[3].summary["num_variables"] <= 3 * len(D)      # one variable per candidate path
    # the matrix of Lab 2: with 3 candidate paths the route formulation reaches the flow optimum
    from pynet2plan import traffic
    D2 = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    r = run("route_formulation_vwp", with_capacity(G, 40), D2, k=3)
    assert r.status == "OPTIMAL" and r.summary["objective"] == pytest.approx(425)


def test_route_formulation_wp(spain):
    completed("route_formulation_wp")
    r = runner.check_formulation("formulations/route_formulation_wp")
    assert r.status == "OPTIMAL", r.message
    assert r.summary["objective"] == pytest.approx(20)
    G, D = spain
    G = with_capacity(G, 23)
    wp = run("route_formulation_wp", G, D, k=2)
    sp = run("splittable_flow", G, D)
    assert wp.status == "OPTIMAL", wp.message
    assert wp.summary["objective"] >= sp.summary["objective"] - 1e-6
    assert wp.tables["wavelengths"]                          # wavelengths are listed
    assert run("route_formulation_wp", G, D, k=1).status == "INFEASIBLE"


def test_ksp_first_fit(spain):
    completed("ksp_first_fit")
    r = runner.check_formulation("formulations/ksp_first_fit")
    assert r.status in ("FEASIBLE", "BLOCKING"), r.message
    G, D = spain
    # with plenty of capacity and k=1 every demand follows its shortest path (by km)
    big = with_capacity(G, 10_000)
    r = run("ksp_first_fit", big, D, k=1)
    assert r.status == "FEASIBLE", r.message
    expected = sum(d.traffic * (len(nx.shortest_path(big, d.origin, d.destination, weight="length")) - 1)
                   for d in D)
    assert r.summary["wavelength_links"] == expected
    # with little capacity some demands are blocked, never over capacity
    r = run("ksp_first_fit", with_capacity(G, 15), D, k=3)
    assert r.status == "BLOCKING", r.message
    assert r.summary["blocked_traffic"] > 0 and r.summary["max_utilization"] <= 1 + 1e-9
    r2 = run("ksp_first_fit", with_capacity(G, 15), D, k=3, order="largest_first")
    assert r2.status in ("FEASIBLE", "BLOCKING"), r2.message
