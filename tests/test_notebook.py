"""labs/lab1_exercises.ipynb: self-contained, up to date, with the TODOs, and with a toolbox that
gives the same results as PyNet2Plan."""

import contextlib
import importlib.util
import io
import json
import os
import random

import networkx as nx
import pytest

from conftest import ROOT

_spec = importlib.util.spec_from_file_location("make_notebook", os.path.join(ROOT, "tools", "make_notebook.py"))
mn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mn)

SOLVED = os.path.join(ROOT, "solutions", "labs", "lab1_exercises.py")


def code_cells(path):
    nb = json.load(open(path, encoding="utf-8"))
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_notebook_is_up_to_date():
    """The notebook is made from the script, the data and the table of handout 2: regenerate it after changing them."""
    with open(mn.NOTEBOOK, encoding="utf-8") as fh:
        assert fh.read() == mn.dumps(mn.notebook(mn.SCRIPT)), "run: python tools/make_notebook.py --solutions"


def test_notebook_structure():
    nb = json.load(open(mn.NOTEBOOK, encoding="utf-8"))
    assert nb["nbformat"] == 4 and nb["metadata"]["kernelspec"]["name"] == "python3"
    code = "".join(code_cells(mn.NOTEBOOK))
    text = "".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
    assert code.count("raise NotCompletedError(") == 7 and "colab.research.google.com" in text
    # self-contained: no PyNet2Plan, no repository, no download
    assert "pynet2plan import" not in code and "import pynet2plan" not in code
    assert "git clone" not in code and "http" not in code and "subprocess" not in code
    assert all(c.get("outputs", []) == [] for c in nb["cells"])          # distributed without outputs
    assert len({c["id"] for c in nb["cells"]}) == len(nb["cells"])
    questions = mn.handout_questions()
    assert sorted(questions) == list(range(1, 8)) and "Bilbao" in questions[5][0]


def run_cells(path, cwd, monkeypatch, upto=None):
    """Runs the code cells as a notebook would, from cwd, without showing the figures."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    monkeypatch.chdir(cwd)
    ns = {"__name__": "__main__"}
    for k, src in enumerate(code_cells(path)[:upto]):
        exec(compile(src, f"cell {k}", "exec"), ns)
    plt.close("all")
    return ns


def test_toolbox_is_pynet2plan(monkeypatch, tmp_path):
    """Data, network.* and traffic.* of the notebook give the same results as PyNet2Plan."""
    from pynet2plan import network, traffic
    ns = run_cells(mn.NOTEBOOK, tmp_path, monkeypatch, upto=2)          # data and toolbox only
    tb_net, tb_traffic = ns["network"], ns["traffic"]

    def same_graph(A, B, xy=False):
        assert A.graph["name"] == B.graph["name"] and list(A.nodes) == list(B.nodes)
        keys = ("x", "y") if xy else ("lat", "lon")
        for n in A:
            assert all(A.nodes[n].get(k) == B.nodes[n].get(k) for k in keys + ("up",)), n
        assert list(A.edges) == list(B.edges)
        for u, v, a in A.edges(data=True):
            assert {k: a[k] for k in ("capacity", "fibers", "length", "up")} == \
                   {k: B.edges[u, v].get(k) for k in ("capacity", "fibers", "length", "up")}, (u, v)
        assert ns["describe"](A) == network.describe(B)

    for rel in mn.TOPOLOGY_FILES:
        G = network.load_topology(os.path.join(ROOT, *rel.split("/")))
        same_graph(tb_net.load_topology(os.path.join(".", *rel.split("/"))), G)
    for rel in mn.TRAFFIC_FILES:
        D = traffic.load_traffic(os.path.join(ROOT, *rel.split("/")))
        assert [tuple(d) for d in tb_traffic.load_traffic(rel)] == [(d.id, d.origin, d.destination, d.traffic) for d in D]
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "nsfnet14.json"))
    H = tb_net.load_topology("data/topologies/nsfnet14.json")
    for args in [(30, 4, 16, 3), (24, 4, 16, 9), (500, 1, 8, 1), (5, 2, 2, 0)]:
        expected = [(d.id, d.origin, d.destination, d.traffic) for d in traffic.random_traffic(G, *args)]
        assert [tuple(d) for d in tb_traffic.random_traffic(H, *args)] == expected, args
    # Spain-8 of exercise 5, written by the toolbox and read by PyNet2Plan
    G8 = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    network.add_city(G8, "Bilbao", allow_online=False)
    H8 = tb_net.load_topology("data/topologies/spain7.json")
    tb_net.add_city(H8, "Bilbao", allow_online=False)
    for other in ("Madrid", "Zaragoza"):
        network.add_link(G8, "Bilbao", other, capacity=40, bidirectional=True)
        tb_net.add_link(H8, "Bilbao", other, capacity=40, bidirectional=True)
    same_graph(H8, G8)
    tb_net.save_topology(H8, str(tmp_path / "s8.json"))
    same_graph(network.load_topology(str(tmp_path / "s8.json")), G8)
    D8 = tb_traffic.random_traffic(H8, 30, 4, 16, seed=3)
    tb_traffic.save_traffic(D8, str(tmp_path / "s8.csv"))
    assert [(d.id, d.origin, d.destination, d.traffic) for d in traffic.load_traffic(str(tmp_path / "s8.csv"), G8)] \
        == [tuple(d) for d in D8]
    # Waxman network of exercise 6
    W = nx.waxman_graph(15, beta=0.6, alpha=0.3, seed=5)
    A, B = tb_net.from_networkx(W, capacity=40, name="W"), network.from_networkx(W, capacity=40, name="W")
    same_graph(A, B, xy=True)
    tb_net.save_topology(A, str(tmp_path / "w.json"))
    same_graph(network.load_topology(str(tmp_path / "w.json")), B, xy=True)
    random.seed()                                                        # nothing global is left seeded


def test_starter_notebook_runs_anywhere(monkeypatch, tmp_path, capsys):
    """It runs in an empty folder (as in Colab), with every exercise still to be completed."""
    run_cells(mn.NOTEBOOK, tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "Spain-7: 7 nodes, 16 links (16 up), capacity 40 λ" in out and out.count("not completed yet: TODO") == 7
    # Part 1, the introduction to NetworkX: the values quoted in its text and in handout 2
    assert "fewest hops: Sevilla > Madrid > Valencia  (2 hops, 693 km)" in out
    assert "shortest km: Sevilla > Malaga > Murcia > Valencia  (3 hops, 658 km)" in out
    assert "path 1: Zaragoza > Madrid > Sevilla > Malaga" in out
    assert "Madrid -> Murcia after the cut : Madrid > Sevilla > Malaga > Murcia" in out
    assert "gives the same demands: True" in out and "fewest-hop routing: 408 wavelengths" in out
    assert "most restrictive set: ['Barcelona', 'Madrid', 'Sevilla', 'Valencia', 'Zaragoza'] -> C >= 34" in out


def test_intro_part():
    cells = mn.intro_part()
    kinds = [k for k, _ in cells]
    assert kinds[0] == "markdown" and cells[0][1].startswith("# Part 1.") and kinds.count("code") >= 10
    assert all(not src.startswith("```") and "<!--" not in src for _, src in cells)
    headings = [src.split("\n")[0] for k, src in cells if k == "markdown" and src.startswith("## ")]
    assert headings[0] == "## 1. Graphs, nodes and links" and len(headings) == 8


@pytest.mark.skipif(not os.path.isfile(SOLVED), reason="solutions/ folder not present")
def test_solved_notebook_matches_the_script(monkeypatch, tmp_path, capsys):
    with open(mn.SOLVED_NOTEBOOK, encoding="utf-8") as fh:
        assert fh.read() == mn.dumps(mn.notebook(SOLVED, solved=True)), "run: python tools/make_notebook.py --solutions"
    ns = run_cells(mn.SOLVED_NOTEBOOK, tmp_path, monkeypatch)
    nb_out = capsys.readouterr().out
    assert "not completed" not in nb_out
    assert (tmp_path / "results" / "lab1_exercises" / "spain8.json").is_file()
    assert (tmp_path / "results" / "lab1_exercises" / "waxman15.json").is_file()
    ns["draw"](ns["G"], [["Sevilla", "Madrid", "Valencia"], ["Sevilla", "Malaga", "Murcia", "Valencia"]])
    # the same answers as the solved script run with PyNet2Plan
    spec = importlib.util.spec_from_file_location("lab1_solved", SOLVED)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "OUT", str(tmp_path / "script"))
    from pynet2plan import network, traffic
    G = network.load_topology(script.TOPOLOGY)
    D = traffic.load_traffic(script.TRAFFIC, G)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for n in sorted(script.EXERCISES):
            script.EXERCISES[n](G, D)

    def answers(text):
        return [ln for ln in text.splitlines() if ln.startswith("  ") and "saved " not in ln]
    part2 = nb_out.split(script.exercise_1.__doc__.split("\n")[0], 1)[1]       # after Part 1
    assert answers(part2) == answers(buf.getvalue()) and len(answers(part2)) > 30
