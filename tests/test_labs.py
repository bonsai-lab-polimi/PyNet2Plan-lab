"""The lab scripts run from start to end and give the values quoted in the handouts (docs/lab/)."""

import os
import subprocess
import sys

from conftest import ROOT, needs_solutions


def run_script(name, *args, timeout=600):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "labs", name), *args], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=timeout)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    return p.stdout


def test_networkx_tour(tmp_path):
    out = run_script("lab1_networkx_tour.py", "--out", str(tmp_path))
    assert "DiGraph - Spain-7 - 7 nodes, 16 links" in out
    assert "fewest hops : Sevilla > Madrid > Valencia" in out
    assert "shortest km : Sevilla > Malaga > Murcia > Valencia" in out
    assert "tightest cut: traffic into ['Malaga', 'Murcia'] = 68 λ over 2 links  ->  every link needs C >= 34" in out
    assert "it is exactly data/traffic/spain7_traffic_split_vs_unsplit.csv: True" in out
    assert "408 wavelengths used in total" in out
    for f in ["nx_spain7.png", "nx_shortest_paths.png", "nx_k_shortest_paths.png", "nx_cut.png",
              "nx_generated.png", "waxman12.json"]:
        assert os.path.getsize(tmp_path / f) > 1000, f
    from pynet2plan import network
    import networkx as nx
    assert nx.is_strongly_connected(network.load_topology(str(tmp_path / "waxman12.json")))


def test_first_ilp(tmp_path):
    out = run_script("lab1_first_ilp.py", "--out", str(tmp_path), "--sweep", "32-36,40,56-58")
    assert "LP relaxation" not in out and "integer=False" not in out
    assert "status OPTIMAL, objective 425.0" in out
    assert "objective - lower bound = 425 - 408 = 17 extra wavelengths" in out
    assert "total extra = 17" in out
    assert "smallest feasible capacity: C = 34;  the lower bound 408 is reached from C = 57" in out
    assert "time: mean ± standard deviation of 5 runs" in out
    assert next(l for l in out.splitlines() if l.strip().startswith("40 ")).split()[-2] == "±"
    assert "no failure: OPTIMAL 408.0" in out
    for line, value in [("Madrid-Zaragoza", "472.0"), ("Madrid-Valencia", "469.0"),
                        ("Barcelona-Zaragoza", "442.0"), ("Barcelona-Valencia", "455.0"),
                        ("Madrid-Sevilla", "INFEASIBLE"), ("Valencia-Murcia", "INFEASIBLE"),
                        ("Sevilla-Malaga", "INFEASIBLE"), ("Malaga-Murcia", "INFEASIBLE")]:
        row = next(r for r in out.splitlines() if r.strip().startswith(f"cut {line} "))
        assert value in row, row
    figs = tmp_path / "lab1_first_ilp"
    for f in ["ilp_map_c40", "ilp_objective_vs_capacity", "ilp_split_and_full_links", "ilp_fiber_cuts_c60"]:
        assert os.path.getsize(figs / f"{f}.png") > 1000, f
        assert open(figs / f"{f}.pdf", "rb").read(5) == b"%PDF-", f
        assert os.path.getsize(figs / f"{f}.json") > 100, f            # data of the figure (TikZ version)


def test_objective_slope_and_solvers():
    """Values quoted in docs/lab/03: same with both solvers; -1 λ per extra unit of capacity."""
    from pynet2plan import network, runner, traffic
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    for solver in ("cbc", "highs"):
        objs = {}
        for c in (33, 34, 40, 50, 56, 57, 60):
            H = G.copy()
            network.set_uniform_capacity(H, c)
            r = runner.run_algorithm(H, D, "splittable_flow", save=False, solver=solver)
            objs[c] = r.summary["objective"] if r.ok else None
        assert objs == {33: None, 34: 431, 40: 425, 50: 415, 56: 409, 57: 408, 60: 408}, (solver, objs)


# ---------------------------------------------------------------- Lab 2 (docs/lab/04)
def test_lab2_stops_until_the_exercise_is_complete(tmp_path):
    """With the exercise as distributed the script explains what is missing and stops."""
    p = subprocess.run([sys.executable, os.path.join(ROOT, "labs", "lab2_unsplittable.py"), "--out", str(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg"), timeout=300)
    from pynet2plan import loader
    info = loader.load_formulation(os.path.join(ROOT, "formulations", "unsplittable_flow.py"))
    if info.todo_count == 0:
        import pytest
        pytest.skip("the exercise has been completed in this copy")
    assert p.returncode == 1
    assert "status NOT_COMPLETED" in p.stdout and "TODO 1" in p.stdout
    assert "then run this script again" in p.stdout


@needs_solutions
def test_lab2_with_the_reference_solution(tmp_path):
    out = run_script("lab2_unsplittable.py", "--formulation", "solutions/unsplittable_flow", "--out", str(tmp_path),
                     "--sweep", "33-35,40-44,56,57", "--large-sweep", "18", "--repetitions", "2")
    assert "test network: status OPTIMAL, objective 21" in out
    lines = out.splitlines()
    split_row = next(l for l in lines if l.startswith("splittable ") and "OPTIMAL" in l)
    unsplit_row = next(l for l in lines if l.startswith("unsplittable ") and "OPTIMAL" in l)
    assert split_row.split()[2:4] == ["425", "17"] and split_row.split()[4:6] == ["384", "184"]
    assert unsplit_row.split()[2:4] == ["443", "35"] and unsplit_row.split()[4:6] == ["384", "184"]
    assert "both infeasible: 33;  only the unsplittable one: 34;  same optimum: 41, 43, 57" in out
    assert "Sevilla->Malaga: 57 λ  (demands 9, 10, 11, 16)" in out
    assert "Madrid->Sevilla: 50 λ  (demands 2, 9, 10, 19)" in out
    assert "demand 10 (14 λ)  Zaragoza > Madrid > Valencia > Murcia > Malaga: +1 hop, 14 extra λ" in out
    assert "time in seconds: mean ± standard deviation of 2 runs" in out
    row = next(l for l in lines if l.strip().startswith("18 "))
    assert row.split()[1] == "898" and row.split()[3] == "±" and row.split()[5] == "903"   # GEANT2
    import json
    times = json.load(open(tmp_path / "lab2_unsplittable" / "lab2_time_large.json", encoding="utf-8"))
    assert times["rows"][0]["runs"] == 2 and times["rows"][0]["splittable_std"] >= 0
    figs = tmp_path / "lab2_unsplittable"
    for f in ["lab2_maps_c40", "lab2_objective_vs_capacity", "lab2_difference", "lab2_time_large"]:
        assert os.path.getsize(figs / f"{f}.png") > 1000, f
        assert open(figs / f"{f}.pdf", "rb").read(5) == b"%PDF-", f        # vector version
        assert os.path.getsize(figs / f"{f}.json") > 100, f


@needs_solutions
def test_lab2_values_quoted_in_the_handout():
    """Handout 4 and LAB2_PLAN: comparison values (both solvers), mistakes and the two-fiber question."""
    from pynet2plan import network, runner, traffic
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    U = "solutions/unsplittable_flow"

    def obj(name, H, solver=None):
        r = runner.run_algorithm(H, D, name, save=False, solver=solver)
        return round(r.summary["objective"], 6) if r.ok else None

    for solver in ("cbc", "highs"):
        got = {}
        for c in (34, 35, 36, 40, 41, 42, 43, 56, 57):
            H = G.copy()
            network.set_uniform_capacity(H, c)
            got[c] = (obj("splittable_flow", H, solver), obj(U, H, solver))
        assert got == {34: (431, None), 35: (430, 460), 36: (429, 443), 40: (425, 443), 41: (424, 424),
                       42: (423, 424), 43: (422, 422), 56: (409, 422), 57: (408, 408)}, solver
    H = G.copy()
    network.set_uniform_capacity(H, 40)
    network.set_link_fibers(H, "Sevilla", "Malaga", 2)                  # question 6
    assert (obj("splittable_flow", H), obj(U, H)) == (418, 422)
    H = G.copy()
    network.set_uniform_capacity(H, 50)
    network.set_link_fibers(H, "Sevilla", "Malaga", 2)
    assert (obj("splittable_flow", H), obj(U, H)) == (408, 408)


# ---------------------------------------------------------------- Lab 2, route formulation (docs/lab/05)
def test_lab2_route_stops_until_the_exercise_is_complete(tmp_path):
    from pynet2plan import loader
    info = loader.load_formulation(os.path.join(ROOT, "formulations", "route_formulation_vwp.py"))
    if info.todo_count == 0:
        import pytest
        pytest.skip("the exercise has been completed in this copy")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "labs", "lab2_route_formulation.py"), "--out", str(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg"), timeout=300)
    assert p.returncode == 1
    assert "status NOT_COMPLETED" in p.stdout and "TODO 1" in p.stdout
    assert "then run this script again" in p.stdout


@needs_solutions
def test_lab2_route_with_the_reference_solution(tmp_path):
    """The values quoted in handout 5 and in LAB2_PLAN."""
    out = run_script("lab2_route_formulation.py", "--formulation", "solutions/route_formulation_vwp",
                     "--out", str(tmp_path), "--large-sweep", "18,20", "--large-k", "5,8", "--repetitions", "2")
    assert "test network: status OPTIMAL, objective 20" in out
    rows = {l[:18].strip(): l.split()[-5:] for l in out.splitlines()
            if l.startswith(("flow formulation", "route, k = "))}
    # the optimum is unique, the number of split demands is not: it depends on the CBC version
    assert rows["flow formulation"][:4] == ["OPTIMAL", "425", "384", "184"]
    assert int(rows["flow formulation"][4]) >= 1
    assert rows["route, k = 1"][0] == "INFEASIBLE"
    assert rows["route, k = 2"][:4] == ["OPTIMAL", "425", "48", "40"]
    assert rows["route, k = 3"][:4] == ["OPTIMAL", "425", "72", "40"]
    cost = {int(l.split()[0]): l.split()[1:] for l in out.splitlines()
            if l.strip() and l.split()[0].isdigit() and len(l.split()) == 6}
    assert cost[7] == ["213", "infeas.", "infeas.", "infeas.", "216"]
    assert cost[8] == ["209", "infeas.", "225", "213", "209"]
    assert cost[11][1:] == ["infeas.", "203", "203", "203"] and cost[6][0] == "infeas."
    assert "k = 2: same optimum as the flow formulation for C = 11-15" in out
    assert "k = 4: same optimum as the flow formulation for C = 8-15" in out
    big = [l.split() for l in out.splitlines() if l.strip().startswith(("18 ", "20 "))]
    assert ["18", "flow", "898", "6600"] == big[0][:4]
    assert big[1][:4] == ["18", "k", "=", "5"] and big[1][4] == "infeas."
    assert big[2][:7] == ["18", "k", "=", "8", "898", "468", big[2][6]]
    assert ["20", "k", "=", "5", "888"] == big[4][:5]
    figs = tmp_path / "lab2_route_formulation"
    for f in ["lab2r_objective_vs_k", "lab2r_time_large"]:
        assert os.path.getsize(figs / f"{f}.png") > 1000, f
        assert open(figs / f"{f}.pdf", "rb").read(5) == b"%PDF-", f
        assert os.path.getsize(figs / f"{f}.json") > 100, f


@needs_solutions
def test_lab2_route_answers():
    """LAB2_PLAN, answers to handout 5: k = 1 feasibility, GEANT2 sizes, paths by length."""
    import networkx as nx
    from itertools import islice
    from pynet2plan import network, runner, traffic

    def at(G, c):
        H = G.copy()
        network.set_uniform_capacity(H, c)
        return H
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    route = "solutions/route_formulation_vwp"
    assert runner.run_algorithm(at(G, 56), D, route, {"k": 1}, save=False).status == "INFEASIBLE"
    assert runner.run_algorithm(at(G, 57), D, route, {"k": 1}, save=False).summary["objective"] == 408
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "cost239.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "cost239_traffic.csv"), G)
    assert runner.run_algorithm(at(G, 21), D, route, {"k": 1}, save=False).status == "INFEASIBLE"
    assert runner.run_algorithm(at(G, 22), D, route, {"k": 1}, save=False).summary["objective"] == 196
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "real", "top22_geant2.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "real", "top22_geant2_traffic.csv"), G)
    short = [(d.origin, d.destination) for d in D
             if len(list(islice(nx.shortest_simple_paths(G, d.origin, d.destination), 8))) < 8]
    assert sorted(short) == [("Dublin", "London"), ("Oslo", "Stockholm")]
    r = runner.run_algorithm(at(G, 18), D, "splittable_flow", save=False)
    assert r.summary["num_constraints"] == 2210


# ---------------------------------------------------------------- Lab 1, NetworkX exercises (docs/lab/02)
def test_lab1_exercises_skeleton():
    out = run_script("lab1_exercises.py")
    assert "Exercise 1. Paths from Sevilla to Valencia" in out and "Exercise 7." in out
    if "not completed yet" not in out:
        import pytest
        pytest.skip("the exercises have been completed in this copy")
    assert "not completed yet: TODO 1:" in out


@needs_solutions
def test_lab1_exercises_answers():
    """The answers of LAB1_PLAN (handout 2 and the interface exercises of handout 1)."""
    p = subprocess.run([sys.executable, os.path.join(ROOT, "solutions", "labs", "lab1_exercises.py")], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg"), timeout=600)
    assert p.returncode == 0, p.stderr
    out = p.stdout
    assert "not completed" not in out
    assert "fewest hops Sevilla > Madrid > Valencia (2 hops, 693 km)" in out
    assert "after the cut : fewest hops Sevilla > Malaga > Murcia > Valencia (3 hops, 658 km)" in out
    assert "disconnected" not in out
    assert "cut Madrid-Sevilla: 560 wavelengths (+152)" in out and "most harmful cut: Madrid-Sevilla" in out
    assert "45 λ from ['Barcelona', 'Madrid', 'Valencia', 'Zaragoza']" in out and "C >= 23" in out
    assert "Madrid       63 λ in transit" in out
    assert "traffic: 30 demands, 316 wavelengths, fewest-hop bound 569" in out
    assert "first connected network: seed 5" in out
    assert "GEANT2 (real topology #22)      35   110   3.14        8" in out
    # exercise 5 in the graphical interface, exercises of handout 1
    from pynet2plan import network, runner, traffic

    def at(G, c):
        H = G.copy()
        network.set_uniform_capacity(H, c)
        return H
    H = network.load_topology(os.path.join(ROOT, "results", "lab1_exercises", "spain8.json"))
    D8 = traffic.load_traffic(os.path.join(ROOT, "results", "lab1_exercises", "spain8_traffic.csv"), H)
    assert runner.run_algorithm(H, D8, "splittable_flow", save=False).status == "INFEASIBLE"
    assert runner.run_algorithm(at(H, 47), D8, "splittable_flow", save=False).status == "INFEASIBLE"
    assert runner.run_algorithm(at(H, 48), D8, "splittable_flow", save=False).summary["objective"] == 571
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "nsfnet14.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "nsfnet14_traffic.csv"), G)
    r = runner.run_algorithm(G, D, "splittable_flow", save=False)
    top = max(r.tables["links"], key=lambda l: l["used"])
    # the optimum is unique, the most loaded link is not: it depends on the CBC version
    cases = {("Pittsburgh", "Ithaca"): (19, 240), ("Salt Lake City", "Palo Alto"): (18, 236)}   # PuLP 4, PuLP 3
    link = (top["origin"], top["destination"])
    assert r.summary["objective"] == 216 and link in cases and top["used"] == cases[link][0]
    H = G.copy()
    for e in (link, link[::-1]):
        network.set_link_up(H, *e, False)
    assert runner.run_algorithm(H, D, "splittable_flow", save=False).summary["objective"] == cases[link][1]
    assert runner.run_algorithm(at(G, 11), D, "splittable_flow", save=False).status == "INFEASIBLE"
    assert runner.run_algorithm(at(G, 12), D, "splittable_flow", save=False).status == "OPTIMAL"
    D7 = traffic.random_traffic(G, 30, 4, 16, seed=7)
    assert traffic.total_traffic(D7) == 269
    assert runner.run_algorithm(G, D7, "splittable_flow", save=False).summary["objective"] == 590
